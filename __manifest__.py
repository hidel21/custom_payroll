{
    'name': "Custom Payroll - Intelli Next",
    'summary': "Liquidación de comisiones en nómina",
    'description': """
Nómina a medida de Intelli Next
===============================

Todo lo que tiene que ver con **pagarle la comisión al comercial**, separado de
cómo se calcula. El cálculo y el desglose viven en ``account_custom``; aquí vive
el circuito de liquidación.

Qué contiene
------------

* ``settlement_date`` — la fecha en que la comisión se le pagó al comercial. Es
  un hecho registrado, no un estado que dependa de que alguien pulse un botón.
* Las transiciones de estado que dependen de la nómina: **Pagada** cuando el
  cliente paga la factura, **Liquidada** cuando se le paga al comercial y
  **Cerrada** cuando el lote de nómina queda cerrado.
* La recogida de comisiones para el recibo, que sustituye a la del módulo
  original: descarta lo ya liquidado, admite recalcular el mismo recibo sin
  vaciarlo y convierte la moneda.
* El sellado y borrado de la fecha al generar o deshacer los comprobantes del
  lote.

Por qué separado
----------------

``account_custom`` responde a «cuánto se le debe y por qué». Este módulo responde
a «cuándo se le pagó». Son dos ciclos de vida distintos, los llevan dos áreas
distintas, y mezclarlos obligaba a tocar contabilidad para arreglar nómina.
""",
    'author': "Hidelberg Martinez",
    'website': "https://intelli-next.com",
    'category': 'Human Resources/Payroll',
    'version': '18.0.1.3.0',
    'license': 'LGPL-3',
    'depends': [
        'account_custom',
        'om_hr_payroll',
        # El reporte en Excel se declara con report_type='xlsx', y ese valor lo
        # añade report_xlsx (OCA). Sin declararlo, en una base donde ese módulo
        # no esté instalado la carga del reporte falla y con ella la
        # instalación entera.
        'report_xlsx',
    ],
    'data': [
        'security/commission_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'report/report_actions.xml',
        'report/commission_report_templates.xml',
        'wizard/commission_settlement_wizard_views.xml',
        'wizard/commission_report_wizard_views.xml',
        'views/invoice_commission_line_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
