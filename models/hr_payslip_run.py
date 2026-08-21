from odoo import fields, models


class HrPayslipRun(models.Model):
    """Sella la fecha de liquidación al pagar el lote, y la borra al deshacerlo.

    El módulo original solo cambiaba el estado de la comisión. Si el botón de
    generar comprobantes no se pulsaba, la comisión quedaba disponible y el
    siguiente lote la volvía a pagar. Dejar constancia con una fecha convierte
    esa protección en un dato y no en un efecto secundario.
    """

    _inherit = "hr.payslip.run"

    def generate_voucher_run(self):
        # El original recorre estados; se le deja hacer su trabajo sin que la
        # sincronización de este módulo le vaya cambiando el suelo.
        return super(
            HrPayslipRun, self.with_context(sin_sincronizar_estado=True)
        ).generate_voucher_run()

    def _commission_lines(self):
        return (
            self.env["invoice.commission.line"]
            .sudo()
            .search([("payslip_id", "in", self.slip_ids.ids)])
        )

    def _mark_commissions_as_paid(self):
        res = super()._mark_commissions_as_paid()
        pendientes = self._commission_lines().filtered(lambda l: not l.settlement_date)
        if pendientes:
            pendientes.write({"settlement_date": fields.Date.context_today(self)})
        return res

    def _reset_commissions_to_calculated(self):
        # Se borra la fecha antes de que el original mire los estados: con la
        # fecha puesta, cualquier vuelta atrás se desharía sola.
        lineas = self._commission_lines()
        if lineas:
            lineas.write({"settlement_date": False})
        return super()._reset_commissions_to_calculated()

    def write(self, vals):
        """Al cerrar o reabrir el lote, las comisiones siguen su suerte."""
        res = super().write(vals)
        if "state" in vals:
            self._commission_lines()._sync_payroll_state()
        return res
