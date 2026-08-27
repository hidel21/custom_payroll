from odoo import api, fields, models


class HrEmployee(models.Model):
    """La moneda en la que se le paga a cada comercial.

    Hay gente contratada en un país que vende en otro: Kerlyn está en la
    compañía de Estados Unidos y cobra en dólares, pero factura en Venezuela y
    en Colombia. Su comisión nace en la moneda de la venta y hay que pagársela
    en la suya.

    **Por qué no se llama ``currency_id``.** Ese nombre ya está ocupado en
    ``hr.employee`` por el propio Odoo: es un campo *related* a
    ``company_id.currency_id`` que usan la nómina y los contratos. Redefinirlo
    para hacerlo editable cambiaría su significado por debajo a todo lo que ya
    lo lee, que es exactamente el tipo de cosa que rompe el cálculo de un
    salario sin avisar. Así que este campo es nuevo y se llama por lo que hace.
    """

    _inherit = "hr.employee"

    commission_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda de pago de comisiones",
        compute="_compute_commission_currency_id",
        store=True,
        readonly=False,
        help="Moneda en la que se le paga a esta persona, que no tiene por qué "
        "ser la de la compañía donde está asignada.\\n\\n"
        "Se rellena sola con la moneda de su compañía y se puede cambiar a "
        "mano. Una vez cambiada, se respeta: cambiar de compañía no la pisa.",
    )

    @api.depends("company_id")
    def _compute_commission_currency_id(self):
        """Propone la moneda de la compañía, pero no pisa lo que ya hay puesto.

        Es la forma de tener un valor por defecto sensato sin quitarle a nadie
        la decisión: si alguien puso dólares a mano y luego se le cambia de
        compañía, sigue cobrando en dólares.
        """
        for employee in self:
            if not employee.commission_currency_id:
                employee.commission_currency_id = employee.company_id.currency_id
