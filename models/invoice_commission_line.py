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
    # La comisión, en la moneda en que se le paga al comercial
    # ------------------------------------------------------------------
    # El importe de la comisión (``commission_amount``) nace siempre en la
    # moneda de la factura, y ``currency_id`` —que el módulo original toma de
    # la factura— es esa moneda de origen. Lo que falta es la otra punta: en
    # qué moneda cobra la persona y cuánto le toca en ella.

    employee_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda del comercial",
        related="employee_id.commission_currency_id",
        store=True,
        index=True,
        help="Moneda en la que se le paga a esta persona. Se configura en su "
        "ficha de empleado.",
    )

    conversion_date = fields.Date(
        string="Fecha de la tasa",
        compute="_compute_commission_amount_employee",
        store=True,
        help="Día cuya tasa de cambio se usó para convertir. Según el ajuste "
        "de nómina, la fecha de la factura o la del cobro.",
    )

    commission_amount_employee = fields.Monetary(
        string="Comisión a pagar",
        currency_field="employee_currency_id",
        compute="_compute_commission_amount_employee",
        store=True,
        help="El importe que hay que pagarle al comercial, ya en su moneda. "
        "Es el que usa la nómina.",
    )

    conversion_warning = fields.Char(
        string="Aviso de conversión",
        compute="_compute_commission_amount_employee",
        store=True,
        help="Se rellena cuando la conversión no es de fiar: normalmente "
        "porque no hay ninguna tasa de cambio registrada para esa fecha.",
    )

    @api.depends(
        "commission_amount",
        "currency_id",
        "employee_currency_id",
        "invoice_date",
        "payment_date_invoice",
        "company_id",
    )
    def _compute_commission_amount_employee(self):
        """Pasa la comisión a la moneda en que cobra el comercial.

        Tres cosas que parecen detalles y no lo son:

        * **Misma moneda, mismo importe.** Si se vende y se paga en la misma
          moneda no se convierte nada. Pasar por el conversor solo para volver
          al punto de partida introduce redondeos que luego nadie sabe explicar.
        * **La tasa es la de un día concreto**, el que diga el ajuste de
          nómina: el de la factura o el del cobro. Nunca la de hoy, que haría
          que una comisión cambiara de importe con solo volver a mirarla.
        * **Sin tasa no hay conversión fiable.** Odoo, cuando no encuentra
          ninguna, aplica 1:1 en silencio y el importe resultante parece
          correcto. Aquí eso se detecta y se marca para que alguien lo revise.
        """
        criterio = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("custom_payroll.commission_conversion_basis", "invoice")
        )
        for line in self:
            destino = line.employee_currency_id
            origen = line.currency_id

            fecha = (
                line.payment_date_invoice or line.invoice_date
                if criterio == "payment"
                else line.invoice_date or line.payment_date_invoice
            )
            line.conversion_date = fecha

            if not destino or not origen or destino == origen:
                # Sin moneda de destino todavía, o es la misma: el importe es
                # el que ya hay. Nada que convertir y nada que avisar.
                line.commission_amount_employee = line.commission_amount
                line.conversion_warning = False
                continue

            if not fecha:
                line.commission_amount_employee = line.commission_amount
                line.conversion_warning = (
                    "Sin fecha de factura ni de cobro: no hay día con el que "
                    "buscar la tasa, así que el importe está sin convertir."
                )
                continue

            convertido = origen._convert(
                line.commission_amount,
                destino,
                line.company_id or self.env.company,
                fecha,
            )
            line.commission_amount_employee = convertido
            line.conversion_warning = line._conversion_warning(
                origen, destino, fecha, line.commission_amount, convertido
            )

    def _conversion_warning(self, origen, destino, fecha, importe, convertido):
        """Avisa cuando la tasa aplicada no es de fiar.

        La comprobación no mira si existen registros de tasa, sino **la tasa
        que de verdad se aplicó**: cuando Odoo no encuentra ninguna devuelve el
        mismo importe, y eso es indistinguible de una conversión correcta.
        Mirar el resultado los distingue, y de paso cubre el caso de que falte
        la tasa de cualquiera de las dos monedas.

        Un peso colombiano no vale un dólar. Si el importe sale idéntico
        habiendo cambiado de moneda, la conversión no se hizo.
        """
        self.ensure_one()
        if importe and abs(convertido - importe) < 1e-9:
            return (
                "Sin conversión real: %s y %s han quedado con el mismo importe, "
                "así que falta la tasa de cambio para el %s. Revíselo antes de "
                "pagar." % (origen.name, destino.name, fecha)
            )

        Rate = self.env["res.currency.rate"].sudo()
        moneda_compania = (self.company_id or self.env.company).currency_id
        for moneda in (origen, destino):
            if moneda == moneda_compania:
                # La moneda de la compañía es la referencia: siempre vale 1.
                continue
            ultima = Rate.search(
                [("currency_id", "=", moneda.id), ("name", "<=", fecha)],
                order="name desc",
                limit=1,
            )
            if ultima and (fecha - ultima.name).days > 7:
                return (
                    "La tasa de %s más cercana es del %s, %s días antes de la "
                    "fecha usada."
                    % (moneda.name, ultima.name, (fecha - ultima.name).days)
                )
        return False

    @api.model
    def _recompute_conversion(self):
        """Rehace la conversión de todo lo que aún no se ha liquidado.

        Hace falta cuando cambia algo de lo que el cálculo no puede depender
        por sí solo: el criterio de fecha, que es un parámetro de
        configuración, o las tasas de cambio, que llegan por su cuenta.
        """
        lines = self.sudo().search([("state", "not in", ("paid", "closed"))])
        if lines:
            self.env.add_to_compute(
                self._fields["commission_amount_employee"], lines
            )
            lines.flush_recordset()
        _logger.info(
            "custom_payroll: conversión rehecha en %s comisión(es) no liquidadas.",
            len(lines),
        )
        return len(lines)

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
        * hay fecha de pago del cliente → **Por Liquidar**
        * no hay ninguna de las dos → **Por Cobrar**

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
        # Un concepto que agrupa el pago solo se liquida en sus meses de corte.
        # Con bloques de N meses contados desde enero, los cortes caen donde
        # (mes - 1) es múltiplo de N: con 3 son enero, abril, julio y octubre;
        # con 6, enero y julio. Fuera de ellos no entra, aunque la factura ya
        # esté cobrada y su bloque cerrado, y eso es justo lo que hace que una
        # factura cobrada tarde espere al corte siguiente.
        mes = payslip.date_to.month if payslip.date_to else 0
        # 0 y 1 son «no agrupa»: entran siempre.
        periodicidades = [0, 1] + [
            n for n in range(2, 13) if mes and (mes - 1) % n == 0
        ]

        dominio_periodicidad = [
            ("payable_from", "<=", payslip.date_to),
            ("payment_months", "in", periodicidades),
        ]

        lines = self.sudo().search(
            dominio_periodicidad
            + [
                ("employee_id", "=", employee.id),
                # Dos estados quedan fuera del recibo, por motivos distintos:
                # Borrador es una comisión que todavía no está bien calculada
                # —le falta la analítica, o nadie ha pulsado Compute—, y Fuera
                # de Corte es una que sí está bien pero que Recursos Humanos ha
                # decidido dejar para más adelante.
                ("state", "not in", ("draft", "out_of_cycle")),
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

        # El importe que se paga es el ya convertido a la moneda del comercial,
        # nunca el original de la factura. La conversión vive en la propia
        # comisión —con su fecha y su aviso si la tasa no era de fiar—, así que
        # aquí solo se suma.
        moneda_recibo = payslip.company_id.currency_id
        total = 0.0
        for line in lines:
            amount = line.commission_amount_employee or line.commission_amount
            moneda = line.employee_currency_id or line.currency_id

            # Último salto: si al comercial se le paga en una moneda y el recibo
            # se emite en otra, se lleva a la del recibo. Con la moneda de pago
            # bien configurada esto no debería hacer falta casi nunca.
            if moneda and moneda_recibo and moneda != moneda_recibo:
                amount = moneda._convert(
                    amount,
                    moneda_recibo,
                    payslip.company_id,
                    line.conversion_date
                    or line.invoice_date
                    or fields.Date.context_today(line),
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
        nómina ya pagada que se quedaron sin liquidar porque nadie pulsó el
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
