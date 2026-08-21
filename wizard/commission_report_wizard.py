from odoo import api, fields, models
from odoo.exceptions import UserError


class CommissionReportWizard(models.TransientModel):
    """Genera el Reporte de Comisiones en PDF o en Excel.

    Existe para que el reporte se **genere**, con los criterios elegidos y
    siempre con las mismas columnas, en lugar de exportar la lista a mano cada
    vez y armarlo como una plantilla. El resultado es reproducible: los mismos
    criterios dan el mismo documento.
    """

    _name = 'commission.report.wizard'
    _description = 'Generar Reporte de Comisiones'

    # ── periodo ──
    date_from = fields.Date(
        string='Desde',
        help="Se filtra por la fecha de la factura. Déjelo vacío para no "
             "acotar por fecha.")
    date_to = fields.Date(string='Hasta')

    # ── a quién y a qué ──
    company_ids = fields.Many2many(
        comodel_name='res.company', string='Compañías',
        help="Vacío significa todas las compañías a las que tenga acceso.")
    employee_ids = fields.Many2many(
        comodel_name='hr.employee', string='Empleados')
    department_ids = fields.Many2many(
        comodel_name='hr.department', string='Departamentos')
    partner_ids = fields.Many2many(
        comodel_name='res.partner', string='Clientes',
        domain=[('is_company', '=', True)])

    # ── qué situación ──
    situacion = fields.Selection(
        selection=[
            ('todas', 'Todas'),
            ('pendientes', 'Pendientes de liquidar'),
            ('liquidadas', 'Ya liquidadas'),
            ('sin_importe', 'Calculadas en cero'),
        ],
        string='Situación',
        default='pendientes',
        required=True,
        help="«Pendientes de liquidar» son las que el cliente ya pagó y aún no "
             "se le han pagado al comercial: es la lista de trabajo de cada "
             "nómina.")

    formato = fields.Selection(
        selection=[('xlsx', 'Excel'), ('pdf', 'PDF')],
        string='Formato', default='xlsx', required=True,
        help="Excel lleva las diecisiete columnas en plano, con filtros y "
             "totales. El PDF va agrupado por empleado, para revisar y firmar.")

    line_count = fields.Integer(
        string='Comisiones que saldrán', compute='_compute_line_count')

    # ------------------------------------------------------------------

    def _domain(self):
        """Traduce los criterios elegidos a un dominio de búsqueda."""
        self.ensure_one()
        dominio = [('state', '!=', 'draft')]
        if self.date_from:
            dominio.append(('invoice_date', '>=', self.date_from))
        if self.date_to:
            dominio.append(('invoice_date', '<=', self.date_to))
        if self.company_ids:
            dominio.append(('company_id', 'in', self.company_ids.ids))
        if self.employee_ids:
            dominio.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            dominio.append(('department_id', 'in', self.department_ids.ids))
        if self.partner_ids:
            dominio.append(('partner_id', 'in', self.partner_ids.ids))

        if self.situacion == 'pendientes':
            dominio += [('payment_date_invoice', '!=', False),
                        ('settlement_date', '=', False)]
        elif self.situacion == 'liquidadas':
            dominio.append(('settlement_date', '!=', False))
        elif self.situacion == 'sin_importe':
            dominio.append(('commission_amount', '=', 0))
        return dominio

    @api.depends('date_from', 'date_to', 'company_ids', 'employee_ids',
                 'department_ids', 'partner_ids', 'situacion')
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = self.env['invoice.commission.line'].search_count(
                wizard._domain())

    def _criterios(self):
        """Frase que resume los criterios, para la cabecera del documento."""
        self.ensure_one()
        partes = [dict(self._fields['situacion'].selection)[self.situacion]]
        if self.date_from or self.date_to:
            partes.append('del %s al %s' % (
                self.date_from or 'inicio', self.date_to or 'hoy'))
        for campo, titulo in (('company_ids', 'compañías'),
                              ('department_ids', 'departamentos'),
                              ('employee_ids', 'empleados'),
                              ('partner_ids', 'clientes')):
            registros = self[campo]
            if registros:
                partes.append('%s: %s' % (titulo, ', '.join(
                    registros.mapped('name')[:4])
                    + (' y %s más' % (len(registros) - 4)
                       if len(registros) > 4 else '')))
        return ' · '.join(partes)

    def action_generate(self):
        self.ensure_one()
        lines = self.env['invoice.commission.line'].search(
            self._domain(), order='employee_id, invoice_date, id')
        if not lines:
            raise UserError(
                "No hay comisiones que cumplan esos criterios. Pruebe a "
                "ampliar las fechas o a cambiar la situación.")

        referencia = ('custom_payroll.action_report_commission_pdf'
                      if self.formato == 'pdf'
                      else 'custom_payroll.action_report_commission_xlsx')
        return self.env.ref(referencia).report_action(
            lines, data={'criterios': self._criterios()})
