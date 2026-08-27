from odoo import api, fields, models

PARAMETRO_FECHA = "custom_payroll.commission_conversion_basis"


class ResConfigSettings(models.TransientModel):
    """Con qué fecha se toma la tasa de cambio de una comisión.

    No es un detalle menor: entre que se emite una factura y el cliente paga
    pueden pasar meses, y en monedas que se mueven mucho el mismo importe vale
    cosas muy distintas según qué día se mire. Por eso se elige, en lugar de
    quedar decidido dentro del programa.
    """

    _inherit = "res.config.settings"

    commission_conversion_basis = fields.Selection(
        selection=[
            ("invoice", "La fecha de la factura"),
            ("payment", "La fecha en que pagó el cliente"),
        ],
        string="Tasa de cambio de las comisiones",
        default="invoice",
        config_parameter=PARAMETRO_FECHA,
        help="Qué día se usa para convertir una comisión a la moneda en que se "
        "le paga al comercial.\\n\\n"
        "• La fecha de la factura: la comisión nace con la venta, así que "
        "cobrar tres meses más tarde no cambia lo que se le paga.\\n"
        "• La fecha del cobro: se convierte con la tasa del día en que entró "
        "el dinero.\\n\\n"
        "Al cambiarlo se recalculan todas las comisiones que no estén "
        "liquidadas.",
    )

    def set_values(self):
        """Al cambiar el criterio, las comisiones se ponen al día solas.

        Sin esto el ajuste parecería no hacer nada: los importes convertidos
        están almacenados y no dependen de un parámetro de configuración, así
        que Odoo no sabe por sí solo que hay que rehacerlos.
        """
        anterior = (
            self.env["ir.config_parameter"].sudo().get_param(PARAMETRO_FECHA)
        )
        res = super().set_values()
        if self.commission_conversion_basis != anterior:
            self.env["invoice.commission.line"]._recompute_conversion()
        return res
