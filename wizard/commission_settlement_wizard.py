import logging

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.invoice_commission_line import LOTES_CERRADOS

_logger = logging.getLogger(__name__)

GRUPO_CORRECCION = 'custom_payroll.group_commission_state_manager'


class CommissionSettlementWizard(models.TransientModel):
    """Mueve varias comisiones entre liquidada y sin liquidar, en los dos sentidos.

    Nació para lo primero que pidió Recursos Humanos: marcar de una vez las
    comisiones ya pagadas para que dejaran de colarse en el cálculo del mes
    siguiente. En la reunión del 21 de agosto apareció la otra mitad del
    problema, en palabras de Contabilidad: alguien marca por error una tanda y
    no hay forma de deshacerlo.

    Así que el mismo asistente hace las dos cosas, pero no para todo el mundo.
    Marcar como liquidada es trabajo corriente de nómina. **Deshacerlo es una
    corrección**, y esa se reserva a quien tenga el permiso «Comisiones:
    corregir estado»: solo esa persona ve el botón, y su nombre queda escrito en
    cada comisión que devuelve.

    Ni un caso ni el otro escriben el estado directamente. Se escriben las
    fechas, y el estado las sigue —igual que hace el resto del módulo—, de modo
    que no puede quedar una comisión en Liquidada sin fecha de liquidación.
    """

    _name = 'commission.settlement.wizard'
    _description = 'Estado de Liquidación de Comisiones'

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

    reason = fields.Char(
        string='Motivo',
        help="Queda escrito en cada comisión junto a su nombre y la fecha. "
             "Obligatorio al devolver una comisión al estado anterior: es lo "
             "que permite entender la corrección meses después.")

    pending_count = fields.Integer(
        string='Se van a marcar',
        compute='_compute_resumen')

    already_count = fields.Integer(
        string='Ya estaban liquidadas',
        compute='_compute_resumen')

    closed_count = fields.Integer(
        string='En lotes ya cerrados',
        compute='_compute_resumen')

    postponable_count = fields.Integer(
        string='Se pueden posponer',
        compute='_compute_resumen')

    postponed_count = fields.Integer(
        string='Ya pospuestas',
        compute='_compute_resumen')

    total_amount = fields.Monetary(
        string='Importe que se liquida',
        currency_field='currency_id',
        compute='_compute_resumen')

    revert_amount = fields.Monetary(
        string='Importe que se devuelve',
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
                "seleccionando las comisiones que se quieren marcar o corregir.")

        lines = self.env['invoice.commission.line'].browse(
            self.env.context.get('active_ids', []))
        # Una comisión en borrador no se ha calculado todavía: ni liquidarla ni
        # devolverla significarían nada, así que se descarta con un aviso claro.
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
            liquidadas = wizard.line_ids - pendientes
            wizard.pending_count = len(pendientes)
            wizard.already_count = len(liquidadas)
            # Las que están en un lote ya cerrado son las delicadas: ese dinero
            # ya salió hacia el comercial.
            wizard.closed_count = len(liquidadas.filtered(
                lambda l: l.payslip_id.payslip_run_id.state in LOTES_CERRADOS))
            wizard.currency_id = (
                wizard.line_ids[:1].currency_id or self.env.company.currency_id)
            wizard.total_amount = sum(pendientes.mapped('commission_amount'))
            wizard.revert_amount = sum(liquidadas.mapped('commission_amount'))
            # Posponer solo tiene sentido en lo que aún no se ha liquidado y
            # no está ya apartado ni sin calcular.
            wizard.postponed_count = len(
                wizard.line_ids.filtered(lambda l: l.state == 'out_of_cycle'))
            wizard.postponable_count = len(pendientes.filtered(
                lambda l: l.state not in ('draft', 'out_of_cycle')))

    # ------------------------------------------------------------------
    # Marcar como liquidada
    # ------------------------------------------------------------------

    def action_settle(self):
        self.ensure_one()
        pendientes = self.line_ids.filtered(lambda l: not l.settlement_date)
        if not pendientes:
            raise UserError(
                "Todas las comisiones seleccionadas están ya liquidadas. "
                "Para deshacerlo está el botón «Devolver al estado anterior».")

        # Escribir la fecha es lo único que hace falta: el estado la sigue solo.
        valores = {'settlement_date': self.settlement_date}
        valores.update(pendientes._firmar_cambio(self.reason))
        pendientes.write(valores)

        _logger.info(
            "custom_payroll: %s comisiones marcadas como liquidadas con fecha "
            "%s por %s (importe %s).",
            len(pendientes), self.settlement_date, self.env.user.login,
            sum(pendientes.mapped('commission_amount')))
        return {'type': 'ir.actions.act_window_close'}

    # ------------------------------------------------------------------
    # Posponer para más adelante
    # ------------------------------------------------------------------

    def action_postpone(self):
        """Aparta la comisión de esta nómina sin darla por mala.

        Recursos Humanos pidió poder decir «esta no la pago ahora». No es que
        esté mal calculada —para eso está Borrador— ni que ya se haya pagado:
        simplemente se deja para la siguiente. Por eso va a **Fuera de Corte**,
        que es el estado que ya existía para exactamente esto y que hasta ahora
        no se podía marcar desde ninguna pantalla.

        Mientras esté ahí la nómina no la recoge, y la sincronización de estados
        tampoco la toca: se queda quieta hasta que alguien la traiga de vuelta
        con «Devolver al estado anterior».
        """
        self.ensure_one()
        if not self.env.user.has_group(GRUPO_CORRECCION):
            raise AccessError(
                "Posponer una comisión está reservado a quien tenga el permiso "
                "«Comisiones: corregir estado».")

        candidatas = self.line_ids.filtered(
            lambda l: not l.settlement_date
            and l.state not in ('draft', 'out_of_cycle'))
        if not candidatas:
            raise UserError(
                "No hay nada que posponer: las seleccionadas están ya "
                "liquidadas, sin calcular o ya apartadas.")

        motivo = (self.reason or '').strip()
        valores = {'state': 'out_of_cycle'}
        valores.update(candidatas._firmar_cambio(motivo))
        candidatas.with_context(sin_sincronizar_estado=True).write(valores)

        _logger.info(
            "custom_payroll: %s comisiones pospuestas por %s (importe %s). "
            "Motivo: %s",
            len(candidatas), self.env.user.login,
            sum(candidatas.mapped('commission_amount')), motivo or '—')
        return {'type': 'ir.actions.act_window_close'}

    # ------------------------------------------------------------------
    # Devolver al estado anterior
    # ------------------------------------------------------------------

    def action_revert(self):
        """Deshace la liquidación: quita la fecha y suelta el recibo de nómina.

        No hay que decidir a qué estado vuelve. Al quedarse sin fecha de
        liquidación, la comisión vuelve sola a **Por Liquidar** si el cliente ya
        había pagado la factura, o a **Por Cobrar** si todavía no. Ese es el estado
        que le corresponde por los hechos, que es más fiable que recordar en
        cuál estaba antes.

        Soltar el recibo (``payslip_id``) no es un extra: sin eso la comisión
        queda enganchada a un recibo viejo y ``_get_employee_commision`` no la
        volvería a recoger nunca, con lo que la corrección la dejaría en un
        limbo del que solo se sale a mano.
        """
        self.ensure_one()
        if not self.env.user.has_group(GRUPO_CORRECCION):
            raise AccessError(
                "Devolver una comisión al estado anterior está reservado a "
                "quien tenga el permiso «Comisiones: corregir estado». "
                "Pídaselo a un administrador si le corresponde.")

        # Devolver sirve para dos cosas: deshacer una liquidación y traer de
        # vuelta lo que se apartó. Se resuelven juntas porque para quien lo usa
        # es el mismo gesto: «esto no debería estar donde está».
        pospuestas = self.line_ids.filtered(lambda l: l.state == 'out_of_cycle')
        liquidadas = self.line_ids.filtered(lambda l: l.settlement_date)
        if not liquidadas and not pospuestas:
            raise UserError(
                "Ninguna de las comisiones seleccionadas está liquidada ni "
                "pospuesta, así que no hay nada que devolver.")

        motivo = (self.reason or '').strip()
        if not motivo:
            raise UserError(
                "Escriba el motivo de la corrección. Queda firmado con su "
                "nombre en cada comisión, y es lo que permitirá entender "
                "dentro de unos meses por qué se deshizo esta liquidación.")

        firma = self.line_ids._firmar_cambio(motivo)

        # Lo apartado vuelve a «calculada» y la sincronización lo lleva desde
        # ahí a donde le toque según sus fechas.
        solo_pospuestas = pospuestas - liquidadas
        if solo_pospuestas:
            solo_pospuestas.write(dict(firma, state='calculated'))

        if liquidadas:
            liquidadas.write(
                dict(firma, settlement_date=False, payslip_id=False))

        # A propósito en warning y no en info: una liquidación deshecha es un
        # hecho excepcional que interesa encontrar rápido en el log.
        _logger.warning(
            "custom_payroll: %s comisiones devueltas al estado anterior por %s "
            "(importe %s, %s en lotes ya cerrados). Motivo: %s",
            len(liquidadas) + len(solo_pospuestas), self.env.user.login,
            sum((liquidadas | solo_pospuestas).mapped('commission_amount')),
            self.closed_count, motivo)
        return {'type': 'ir.actions.act_window_close'}
