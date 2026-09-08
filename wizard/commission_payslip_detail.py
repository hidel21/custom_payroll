from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommissionPayslipDetail(models.TransientModel):
    """El desglose de las comisiones que hay dentro de un recibo de nómina.

    Existe para responder a una pregunta concreta que hoy obliga a abrir otra
    pestaña: de dónde salen los 900.000 pesos de comisiones que aparecen en el
    recibo de Óscar. La respuesta está en las facturas enlazadas al recibo, y
    esto las enseña sin salir de él.

    Es transitorio a propósito: no guarda nada, solo reúne lo que ya existe.
    """

    _name = "commission.payslip.detail"
    _description = "Desglose de comisiones del recibo"

    payslip_id = fields.Many2one(
        comodel_name="hr.payslip",
        string="Recibo",
        required=True,
        readonly=True,
    )
    employee_id = fields.Many2one(
        related="payslip_id.employee_id", string="Empleado", readonly=True
    )
    date_from = fields.Date(related="payslip_id.date_from", readonly=True)
    date_to = fields.Date(related="payslip_id.date_to", readonly=True)

    line_ids = fields.Many2many(
        comodel_name="invoice.commission.line",
        string="Facturas",
        readonly=True,
    )

    currency_id = fields.Many2one(
        related="payslip_id.company_id.currency_id", readonly=True
    )
    total_lines = fields.Monetary(
        string="Suma de las facturas",
        compute="_compute_totales",
        help="Lo que suman las comisiones enlazadas a este recibo, ya "
        "convertidas a la moneda de la compañía.",
    )
    total_payslip = fields.Monetary(
        string="Importe en el recibo",
        compute="_compute_totales",
        help="Lo que dice la línea de comisiones del recibo.",
    )
    difference = fields.Monetary(string="Diferencia", compute="_compute_totales")
    mismatch_warning = fields.Char(compute="_compute_totales")

    multicurrency_note = fields.Char(compute="_compute_multicurrency_note")

    # ------------------------------------------------------------------
    # Apertura
    # ------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        valores = super().default_get(fields_list)
        recibo = self._recibo_del_contexto()
        valores["payslip_id"] = recibo.id
        valores["line_ids"] = [
            fields.Command.set(recibo.sudo().commission_line_ids.ids)
        ]
        return valores

    @api.model
    def _recibo_del_contexto(self):
        """El recibo desde el que se abrió, venga del botón que venga."""
        contexto = self.env.context
        if contexto.get("active_model") == "hr.payslip" and contexto.get("active_id"):
            return self.env["hr.payslip"].browse(contexto["active_id"])
        if contexto.get("default_payslip_id"):
            return self.env["hr.payslip"].browse(contexto["default_payslip_id"])
        raise UserError(
            _("Este desglose se abre desde un recibo de nómina, no por su cuenta.")
        )

    # ------------------------------------------------------------------
    # Totales
    # ------------------------------------------------------------------

    @api.depends("line_ids", "payslip_id")
    def _compute_totales(self):
        """Suma las facturas y la contrasta con lo que dice el recibo.

        Las dos cifras deberían ser la misma, y por eso se enseñan las dos: si
        se separan, es que el recibo se calculó en un momento y las comisiones
        cambiaron después. Verlo aquí es la forma barata de detectarlo, en
        lugar de descubrirlo al cuadrar el cierre.
        """
        for asistente in self:
            recibo = asistente.payslip_id
            moneda = recibo.company_id.currency_id

            total = 0.0
            for linea in asistente.line_ids:
                importe = linea.commission_amount_employee or linea.commission_amount
                origen = linea.employee_currency_id or linea.currency_id
                if origen and moneda and origen != moneda:
                    importe = origen._convert(
                        importe,
                        moneda,
                        recibo.company_id,
                        linea.conversion_date
                        or linea.invoice_date
                        or fields.Date.context_today(linea),
                    )
                total += importe

            asistente.total_lines = total
            asistente.total_payslip = recibo._commission_payslip_amount()
            asistente.difference = asistente.total_payslip - total

            if moneda and not moneda.is_zero(asistente.difference):
                asistente.mismatch_warning = _(
                    "El recibo dice %(recibo)s y las facturas suman %(facturas)s: "
                    "%(dif)s de diferencia. Suele significar que el recibo se "
                    "calculó antes de que cambiara alguna de estas comisiones.",
                    recibo=recibo.company_id.currency_id.format(
                        asistente.total_payslip
                    ),
                    facturas=moneda.format(total),
                    dif=moneda.format(asistente.difference),
                )
            else:
                asistente.mismatch_warning = False

    @api.depends("line_ids")
    def _compute_multicurrency_note(self):
        """Avisa de que hay conversión de por medio, y con qué tasa.

        Un total en pesos que sale de facturas en dólares se explica solo si se
        dice; si no, parece que no cuadra.
        """
        for asistente in self:
            monedas = asistente.line_ids.mapped(
                lambda l: l.employee_currency_id or l.currency_id
            )
            propia = asistente.payslip_id.company_id.currency_id
            otras = {m.name for m in monedas if m and m != propia}
            if otras:
                asistente.multicurrency_note = _(
                    "Hay facturas en %(otras)s convertidas a %(propia)s. "
                    "Las columnas «Importe original» y «Convertido» enseñan las "
                    "dos cifras.",
                    otras=", ".join(sorted(otras)),
                    propia=propia.name,
                )
            else:
                asistente.multicurrency_note = False

    # ------------------------------------------------------------------
    # Descargas
    # ------------------------------------------------------------------

    def _lineas_para_descargar(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(
                _("No hay comisiones enlazadas a este recibo, así que no hay "
                  "nada que descargar.")
            )
        return self.line_ids

    def action_download_xlsx(self):
        """Reutiliza el informe de comisiones que ya existe.

        Se pasa exactamente el conjunto que está en pantalla, así que el Excel
        trae lo mismo que se está viendo y ni una línea más. Era el requisito:
        poder descargar el reporte del empleado consultado sin pasar por la
        sección general de informes.
        """
        return self.env.ref("custom_payroll.action_report_commission_xlsx").report_action(
            self._lineas_para_descargar()
        )

    def action_download_pdf(self):
        return self.env.ref("custom_payroll.action_report_commission_pdf").report_action(
            self._lineas_para_descargar()
        )

    def action_open_list(self):
        """Salida a la lista completa, para quien quiera filtrar y agrupar."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Comisiones de %s", self.employee_id.name),
            "res_model": "invoice.commission.line",
            "view_mode": "list,form",
            "domain": [("id", "in", self.line_ids.ids)],
            "target": "current",
        }
