from odoo import _, api, fields, models

# Códigos de regla salarial que llevan comisiones. Se deja como parámetro
# porque no es una constante del dominio: cada compañía puede nombrar sus
# reglas como quiera, y en esta base conviven COMISIONES —la que calcula— y
# COMISIONPR —la entrada manual que se suma a la anterior—.
PARAMETRO_REGLAS = "custom_payroll.commission_rule_codes"
REGLAS_POR_DEFECTO = "COMISIONES"


class HrPayslip(models.Model):
    """Enlaza el recibo con las comisiones que lo componen.

    El dato ya existía —``invoice.commission.line`` guarda su ``payslip_id``
    desde que se calcula el recibo—, pero no había forma de recorrerlo en
    sentido contrario. Sin eso, saber qué facturas hay detrás de un importe
    obligaba a salir del recibo, ir al informe de comisiones y filtrar a mano.
    """

    _inherit = "hr.payslip"

    commission_line_ids = fields.One2many(
        comodel_name="invoice.commission.line",
        inverse_name="payslip_id",
        string="Comisiones",
        readonly=True,
    )
    commission_count = fields.Integer(compute="_compute_commission_count")

    @api.depends("commission_line_ids")
    def _compute_commission_count(self):
        # Se lee con sudo porque quien liquida la nómina no tiene por qué tener
        # permiso sobre las comisiones, y el número de facturas no revela nada
        # que no esté ya en el propio recibo.
        agrupado = {}
        if self.ids:
            agrupado = {
                recibo.id: cuenta
                for recibo, cuenta in self.env["invoice.commission.line"]
                .sudo()
                ._read_group(
                    [("payslip_id", "in", self.ids)], ["payslip_id"], ["__count"]
                )
            }
        for recibo in self:
            recibo.commission_count = agrupado.get(recibo.id, 0)

    def _commission_rule_codes(self):
        parametro = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(PARAMETRO_REGLAS, REGLAS_POR_DEFECTO)
        )
        return [c.strip() for c in parametro.split(",") if c.strip()]

    def _commission_payslip_amount(self):
        """Lo que el recibo dice que se paga de comisiones.

        Se suma sobre las líneas del recibo y no sobre las comisiones, porque
        el objetivo es justamente poder comparar las dos cifras.
        """
        self.ensure_one()
        codigos = self._commission_rule_codes()
        lineas = self.line_ids.filtered(lambda l: l.code in codigos)
        return sum(lineas.mapped("total"))

    def action_view_commission_detail(self):
        """Abre el desglose en una ventana emergente sobre el recibo."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Comisiones de %s", self.employee_id.name),
            "res_model": "commission.payslip.detail",
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_model": "hr.payslip",
                "active_id": self.id,
                "default_payslip_id": self.id,
            },
        }


class HrPayslipLine(models.Model):
    """Un botón en la línea de comisiones, que es donde se mira el importe.

    Yeny pidió poder pulsar sobre el monto. Hacer clicable la celda exigiría un
    componente propio; un botón en la misma fila llega al mismo sitio con las
    piezas estándar de Odoo, que es lo que conviene en un módulo que hereda de
    otros dos.
    """

    _inherit = "hr.payslip.line"

    is_commission_line = fields.Boolean(compute="_compute_is_commission_line")

    @api.depends("code")
    def _compute_is_commission_line(self):
        codigos = self.env["hr.payslip"]._commission_rule_codes()
        for linea in self:
            linea.is_commission_line = linea.code in codigos

    def action_open_commission_detail(self):
        self.ensure_one()
        return self.slip_id.action_view_commission_detail()
