from odoo import models


class AccountMove(models.Model):
    """Añade el motivo de nómina a la congelación de comisiones.

    ``account_custom`` sabe que una comisión Liquidada o Cerrada no se toca,
    porque ese dinero ya salió. Lo que no puede saber, porque no depende de
    contabilidad, es que una comisión metida en un recibo ya confirmado tampoco
    se puede mover: el recibo dice una cifra, y recalcular la factura la
    dejaría diciendo otra.
    """

    _inherit = "account.move"

    def _commission_lines_frozen(self, lines):
        if super()._commission_lines_frozen(lines):
            return True
        return any(line.payslip_locked for line in lines)
