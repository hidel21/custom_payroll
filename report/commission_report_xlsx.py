import io

import xlsxwriter

from odoo import models

# Las columnas del Reporte de Comisiones, en el mismo orden en que se ven en
# pantalla. El ancho va en caracteres, que es la unidad de xlsxwriter.
COLUMNAS = [
    ('Empleado', 'employee', 30),
    ('Compañía', 'company', 22),
    ('Departamento', 'department', 20),
    ('Cliente', 'partner', 30),
    ('Factura', 'invoice', 16),
    ('Periodo', 'period', 10),
    ('Secuencia', 'sequence', 10),
    ('Fecha Factura', 'invoice_date', 13),
    ('Fecha de Pago', 'payment_date', 13),
    ('Fecha de Liquidación', 'settlement_date', 18),
    ('Moneda', 'currency', 8),
    ('Concepto', 'concept', 26),
    ('Base Comisión', 'base', 16),
    ('% Efectivo', 'effective', 11),
    ('Porcentajes', 'percentages', 30),
    ('Monto Comisión', 'amount', 16),
    ('Estado', 'state', 14),
]


class CommissionReportXlsx(models.AbstractModel):
    """Hoja de cálculo del Reporte de Comisiones.

    Lleva las mismas columnas que la pantalla y en el mismo orden, para que
    quien lo recibe reconozca lo que está viendo. Se genera desde el asistente
    de reportes, no exportando la lista a mano: así el resultado es siempre el
    mismo y trae los totales calculados.
    """

    _name = 'report.custom_payroll.commission_xlsx'
    _description = 'Reporte de Comisiones en Excel'

    def create_xlsx_report(self, docids, data):
        lines = self.env['invoice.commission.line'].browse(docids)
        etiquetas = dict(lines._fields['state'].selection)

        flujo = io.BytesIO()
        libro = xlsxwriter.Workbook(flujo, {'in_memory': True})
        hoja = libro.add_worksheet('Comisiones')

        titulo = libro.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#10201D'})
        subtitulo = libro.add_format({'font_size': 9, 'font_color': '#4E5F5B'})
        cabecera = libro.add_format({
            'bold': True, 'bg_color': '#E5ECEA', 'font_color': '#33463F',
            'border': 1, 'border_color': '#CFDBD8', 'text_wrap': True,
            'valign': 'vcenter'})
        texto = libro.add_format({'border': 1, 'border_color': '#DEE7E4'})
        fecha = libro.add_format({
            'border': 1, 'border_color': '#DEE7E4', 'num_format': 'dd/mm/yyyy',
            'align': 'center'})
        dinero = libro.add_format({
            'border': 1, 'border_color': '#DEE7E4', 'num_format': '#,##0.00'})
        porcentaje = libro.add_format({
            'border': 1, 'border_color': '#DEE7E4', 'num_format': '0.00',
            'align': 'right'})
        entero = libro.add_format({
            'border': 1, 'border_color': '#DEE7E4', 'align': 'right'})
        total = libro.add_format({
            'bold': True, 'top': 2, 'top_color': '#1D5F5A',
            'num_format': '#,##0.00'})
        total_texto = libro.add_format({
            'bold': True, 'top': 2, 'top_color': '#1D5F5A'})

        hoja.write(0, 0, 'Reporte de Comisiones', titulo)
        hoja.write(1, 0, data.get('criterios') or '', subtitulo)
        hoja.write(2, 0, '%s comisión(es)' % len(lines), subtitulo)

        fila_cabecera = 4
        for indice, (nombre, _clave, ancho) in enumerate(COLUMNAS):
            hoja.write(fila_cabecera, indice, nombre, cabecera)
            hoja.set_column(indice, indice, ancho)
        hoja.set_row(fila_cabecera, 28)
        # Se congela la cabecera y se activa el autofiltro: quien lo recibe
        # puede seguir filtrando sin volver a pedir el reporte.
        hoja.freeze_panes(fila_cabecera + 1, 0)
        hoja.autofilter(fila_cabecera, 0, fila_cabecera + len(lines),
                        len(COLUMNAS) - 1)

        fila = fila_cabecera + 1
        for line in lines:
            valores = {
                'employee': line.employee_id.name or '',
                'company': line.company_id.name or '',
                'department': line.department_id.name or '',
                'partner': line.partner_id.name or '',
                'invoice': line.invoice_id.name or '',
                'period': line.commission_period_name or '',
                'sequence': line.commission_sequence or 0,
                'invoice_date': line.invoice_date or '',
                'payment_date': line.payment_date_invoice or '',
                'settlement_date': line.settlement_date or '',
                'currency': line.currency_id.name or '',
                'concept': line.concept_summary or '',
                'base': line.commission_base or 0.0,
                'effective': line.effective_percentage or 0.0,
                'percentages': line.percentage_summary or '',
                'amount': line.commission_amount or 0.0,
                'state': etiquetas.get(line.state, line.state),
            }
            for indice, (_n, clave, _a) in enumerate(COLUMNAS):
                valor = valores[clave]
                if clave in ('invoice_date', 'payment_date', 'settlement_date'):
                    if valor:
                        hoja.write_datetime(fila, indice, valor, fecha)
                    else:
                        hoja.write(fila, indice, '', fecha)
                elif clave in ('base', 'amount'):
                    hoja.write_number(fila, indice, valor, dinero)
                elif clave == 'effective':
                    hoja.write_number(fila, indice, valor, porcentaje)
                elif clave == 'sequence':
                    hoja.write_number(fila, indice, valor, entero)
                else:
                    hoja.write(fila, indice, valor, texto)
            fila += 1

        # Totales solo de lo que tiene sentido sumar: la base y el importe. La
        # secuencia y el porcentaje efectivo no se suman, que era justo lo que
        # despistaba en la pantalla.
        indices = {clave: i for i, (_n, clave, _a) in enumerate(COLUMNAS)}
        hoja.write(fila, indices['concept'], 'TOTAL', total_texto)
        hoja.write_number(fila, indices['base'],
                          sum(lines.mapped('commission_base')), total)
        hoja.write_number(fila, indices['amount'],
                          sum(lines.mapped('commission_amount')), total)

        libro.close()
        return flujo.getvalue(), 'xlsx'
