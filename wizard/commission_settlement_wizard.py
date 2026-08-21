import logging

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CommissionSettlementWizard(models.TransientModel):
    """Marca varias comisiones como liquidadas de una vez.

    Es lo que pedía Recursos Humanos en la reunión: seleccionar las comisiones
    que ya se pagaron, marcarlas, y que dejen de aparecer como pendientes en los
    cálculos de nómina siguientes. Sin esto había que entrar una por una, y las
    ya pagadas volvían a colarse en el cálculo del mes siguiente.

    La fecha es editable a propósito: al ponerse al día hay que registrar
    comisiones pagadas en julio, no la fecha de hoy.
    """

    _name = 'commission.settlement.wizard'
    _description = 'Marcar Comisiones como Liquidadas'

    line_ids = fields.Many2many(
        comodel_name='invoice.commission.line',
        string='Comisiones',
        required=True)

    settlement_date = fields.Date(
        string='Fecha de liquidación',
        required=True,
        default=fields.Date.context_today,
        help="Fecha en que se le pagó la comisión al comercial. Se puede poner "
             "una fecha pasada para registrar liquidaciones de meses "
             "anteriores.")

    pending_count = fields.Integer(
        string='Se van a marcar',
        compute='_compute_resumen')

    already_count = fields.Integer(
        string='Ya estaban liquidadas',
        compute='_compute_resumen')

    total_amount = fields.Monetary(
        string='Importe que se liquida',
        currency_field='currency_id',
        compute='_compute_resumen')

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        compute='_compute_resumen')

    @api.model
    def default_get(self, fields_list):
        """Recoge la selección de la lista, al estilo de los asistentes de Odoo."""
        result = super().default_get(fields_list)
        if 'line_ids' not in fields_list or result.get('line_ids'):
            return result

        if self.env.context.get('active_model') != 'invoice.commission.line':
            raise UserError(
                "Este asistente se lanza desde el Reporte de Comisiones, "
                "seleccionando las comisiones que ya se pagaron.")

        lines = self.env['invoice.commission.line'].browse(
            self.env.context.get('active_ids', []))
        # Una comisión en borrador no se ha calculado todavía: liquidarla no
        # significaría nada, así que se descarta con un aviso claro.
        lines = lines.filtered(lambda l: l.state != 'draft')
        if not lines:
            raise UserError(
                "Ninguna de las comisiones seleccionadas está calculada. "
                "Primero hay que calcularlas en la factura.")

        result['line_ids'] = [Command.set(lines.ids)]
        return result

    @api.depends('line_ids', 'settlement_date')
    def _compute_resumen(self):
        for wizard in self:
            pendientes = wizard.line_ids.filtered(lambda l: not l.settlement_date)
            wizard.pending_count = len(pendientes)
            wizard.already_count = len(wizard.line_ids) - len(pendientes)
            wizard.currency_id = (
                wizard.line_ids[:1].currency_id or self.env.company.currency_id)
            wizard.total_amount = sum(pendientes.mapped('commission_amount'))

    def action_settle(self):
        self.ensure_one()
        pendientes = self.line_ids.filtered(lambda l: not l.settlement_date)
        if not pendientes:
            raise UserError(
                "Todas las comisiones seleccionadas están ya liquidadas.")

        # Escribir la fecha es lo único que hace falta: el estado la sigue solo.
        pendientes.write({'settlement_date': self.settlement_date})

        _logger.info(
            "custom_payroll: %s comisiones marcadas como liquidadas con fecha "
            "%s por %s (importe %s).",
            len(pendientes), self.settlement_date, self.env.user.login,
            sum(pendientes.mapped('commission_amount')))
        return {'type': 'ir.actions.act_window_close'}
