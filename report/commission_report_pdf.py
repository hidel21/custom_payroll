from odoo import models


class CommissionReportPdf(models.AbstractModel):
    """Datos del Reporte de Comisiones en PDF.

    El PDF se agrupa por empleado con subtotales, porque es como se revisa: una
    persona liquida empleado por empleado. La hoja de cálculo, en cambio, va en
    plano con todas las columnas, para poder filtrar y cruzar.
    """

    _name = 'report.custom_payroll.commission_pdf'
    _description = 'Reporte de Comisiones en PDF'

    def _get_report_values(self, docids, data=None):
        lines = self.env['invoice.commission.line'].browse(docids)
        etiquetas = dict(lines._fields['state'].selection)

        # Se agrupa en Python y no con read_group para conservar el orden de
        # lectura y poder mostrar los datos del empleado una sola vez.
        grupos = []
        for empleado in lines.employee_id:
            suyas = lines.filtered(lambda l: l.employee_id == empleado)
            grupos.append({
                'empleado': empleado,
                'lineas': suyas.sorted(
                    lambda l: (l.invoice_date or l.create_date.date(), l.id)),
                'base': sum(suyas.mapped('commission_base')),
                'importe': sum(suyas.mapped('commission_amount')),
            })
        grupos.sort(key=lambda g: (g['empleado'].name or '').lower())

        return {
            'doc_model': 'invoice.commission.line',
            'docs': lines,
            'grupos': grupos,
            'etiquetas': etiquetas,
            'criterios': (data or {}).get('criterios') or '',
            'total_base': sum(lines.mapped('commission_base')),
            'total_importe': sum(lines.mapped('commission_amount')),
        }
