import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Estados de lote de nómina que significan «esto ya se pagó y no se toca».
LOTES_CERRADOS = ("close", "paid", "done")


class InvoiceCommissionLine(models.Model):
    """La cara de nómina de una comisión: cuándo y cómo se le paga al comercial.

    El cálculo del importe y su desglose viven en ``account_custom``. Aquí solo
    está el circuito de liquidación, que se apoya en dos fechas distintas y es
    importante no confundirlas:

    * **Fecha de Pago** — cuando el **cliente** pagó la factura. La calcula el
      módulo original a partir de los pagos del asiento.
    * **Fecha de Liquidación** — cuando se le pagó la comisión al **comercial**.
      La sella este módulo al generar los comprobantes del lote de nómina.
    """

    _inherit = "invoice.commission.line"

    settlement_date = fields.Date(
        string="Fecha de Liquidación",
        copy=False,
        index=True,
        help="Fecha en que la comisión se le pagó al comercial. La pone la "
        "nómina al generar los comprobantes del lote. No confundir con la "
        "Fecha de Pago, que es cuando pagó el cliente.",
    )

    # ------------------------------------------------------------------
    # Quién corrigió el estado a mano
    # ------------------------------------------------------------------
    # El estado se deduce de las fechas, así que tocarlo a mano es siempre una
    # excepción: alguien marcó como liquidado lo que no lo estaba. Estos tres
    # campos no intervienen en ningún cálculo; existen para poder responder
    # meses después a «¿quién deshizo esto y por qué?».

    state_change_uid = fields.Many2one(
        comodel_name="res.users",
        string="Cambio manual por",
        readonly=True,
        copy=False,
        help="Quién cambió a mano el estado de liquidación por última vez.",
    )

    state_change_date = fields.Datetime(
        string="Fecha del cambio manual",
        readonly=True,
        copy=False,
    )

    state_change_reason = fields.Char(
        string="Motivo del cambio",
        readonly=True,
        copy=False,
        help="Lo que escribió quien lo cambió, en el momento de hacerlo.",
    )

    def _firmar_cambio(self, motivo=None):
        """Valores con los que se firma un cambio de estado hecho a mano."""
        return {
            "state_change_uid": self.env.uid,
            "state_change_date": fields.Datetime.now(),
            "state_change_reason": motivo or False,
        }

    # ------------------------------------------------------------------
    # El estado sigue a las fechas
    # ------------------------------------------------------------------

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("sin_sincronizar_estado") and (
            "settlement_date" in vals
            or "payment_date_invoice" in vals
            or "payslip_id" in vals
            or "state" in vals
        ):
            self._sync_payroll_state()
        return res

    def _sync_payroll_state(self):
        """Pone el estado de acuerdo con los hechos, no al revés.

        Cada estado tiene un hecho que lo justifica, y por eso se puede deducir
        en lugar de pedir que alguien lo cambie a mano:

        * hay fecha de liquidación y el lote está cerrado → **Cerrada**
        * hay fecha de liquidación → **Liquidada**
        * hay fecha de pago del cliente → **Pagada**
        * no hay ninguna de las dos → **Por Liquidar**

        Los estados que no dependen de fechas —Borrador, Fuera de Corte y En
        Mora— no se tocan: el primero es anterior al cálculo y los otros dos se
        marcan a mano.
        """
        contexto = {"sin_sincronizar_estado": True}
        destino = {}

        for line in self:
            if line.state in ("draft", "out_of_cycle", "overdue"):
                continue
            if line.settlement_date:
                cerrado = line.payslip_id.payslip_run_id.state in LOTES_CERRADOS
                nuevo = "closed" if cerrado else "paid"
            elif line.payment_date_invoice:
                nuevo = "client_paid"
            else:
                nuevo = "calculated"
            if nuevo != line.state:
                destino[nuevo] = destino.get(nuevo, self.browse()) | line

        for estado, lineas in destino.items():
            lineas.with_context(**contexto).write({"state": estado})

    @api.depends("payment_date_invoice", "settlement_date")
    def _compute_ready_to_pay(self):
        """Lista para pagar es lo cobrado al cliente y aún sin liquidar.

        El módulo original lo definía como «calculada y cobrada», atado a un
        estado. Atarlo a las dos fechas lo hace independiente de por dónde haya
        pasado el estado.
        """
        for record in self:
            record.ready_to_pay = bool(
                record.payment_date_invoice and not record.settlement_date
            )

    # ------------------------------------------------------------------
    # Recogida para el recibo de nómina
    # ------------------------------------------------------------------

    @api.model
    def _get_employee_commision(self, employee, payslip, state="calculated"):
        """Comisiones que le toca cobrar a este empleado en este recibo.

        Sustituye a la del módulo original, que filtraba por estado. El estado
        cambiaba al pulsar el botón de generar comprobantes, así que si nadie lo
        pulsaba la comisión seguía disponible y el siguiente lote la volvía a
        pagar. Aquí la guarda es la fecha de liquidación, que es un hecho.

        Se admite lo que ya está en **este** recibo para que recalcularlo no
        vacíe la comisión, y se excluye lo que esté en otro.

        Convierte la moneda, que la regla salarial de la base no hacía: una
        comisión en dólares se sumaba como si fueran pesos.
        """
        lines = self.sudo().search(
            [
                ("employee_id", "=", employee.id),
                # Una comisión en Borrador es una que todavía no está bien
                # calculada —le falta la cuenta analítica del proyecto, o nadie
                # ha pulsado Compute—. Pagarla sería pagar un número provisional.
                ("state", "!=", "draft"),
                ("settlement_date", "=", False),
                ("payment_date_invoice", "!=", False),
                ("payment_date_invoice", "<=", payslip.date_to),
                "|",
                ("payslip_id", "=", False),
                ("payslip_id", "=", payslip.id),
            ]
        )
        if not lines:
            return 0.0

        lines.write({"payslip_id": payslip.id})

        company_currency = payslip.company_id.currency_id
        total = 0.0
        for line in lines:
            amount = line.commission_amount
            if line.currency_id and line.currency_id != company_currency:
                amount = line.currency_id._convert(
                    amount,
                    company_currency,
                    payslip.company_id,
                    line.payment_date_invoice,
                )
            total += amount
        return total

    # ------------------------------------------------------------------
    # Mantenimiento
    # ------------------------------------------------------------------

    @api.model
    def _cron_sync_payroll_state(self):
        """Pone al día estados y la marca de lista para pagar.

        Hace falta cuando algo quedó descuadrado: comisiones dentro de una
        nómina ya pagada que se quedaron en Por Liquidar porque nadie pulsó el
        botón de generar comprobantes, o cambios de fórmula que Odoo no
        recalcula por sí solo en campos almacenados.
        """
        lines = self.sudo().search(
            [("state", "not in", ("draft", "out_of_cycle", "overdue"))]
        )
        lines._sync_payroll_state()

        self.env.add_to_compute(self._fields["ready_to_pay"], lines)
        lines.flush_recordset(["ready_to_pay"])
        self.env.flush_all()

        reparto = {}
        for line in lines:
            reparto[line.state] = reparto.get(line.state, 0) + 1
        _logger.info(
            "custom_payroll: estados puestos al día en %s comisiones — %s; "
            "%s listas para pagar.",
            len(lines),
            ", ".join("%s: %s" % (e, n) for e, n in sorted(reparto.items())),
            len(lines.filtered("ready_to_pay")),
        )
        return {
            "revisadas": len(lines),
            "reparto": reparto,
            "listas_para_pagar": len(lines.filtered("ready_to_pay")),
        }
