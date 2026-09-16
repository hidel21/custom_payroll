import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Códigos de regla salarial que llevan comisiones. Se deja como parámetro
# porque no es una constante del dominio: cada compañía puede nombrar sus
# reglas como quiera, y en esta base conviven COMISIONES —la que calcula— y
# COMISIONPR —la entrada manual que se suma a la anterior—.
PARAMETRO_REGLAS = "custom_payroll.commission_rule_codes"
REGLAS_POR_DEFECTO = "COMISIONES"

# Estados de recibo en los que su comisión ya está pagada. El recibo se confirma
# para cerrar el mes y puede quedarse ahí semanas antes de marcarse como pagado;
# en ambos el dinero ya salió, así que los dos liquidan.
ESTADOS_LIQUIDADOS = ("done", "paid")


class HrPayslip(models.Model):
    """Enlaza el recibo con las comisiones que lo componen.

    El dato ya existía —``invoice.commission.line`` guarda su ``payslip_id``
    desde que se calcula el recibo—, pero no había forma de recorrerlo en
    sentido contrario. Sin eso, saber qué facturas hay detrás de un importe
    obligaba a salir del recibo, ir al informe de comisiones y filtrar a mano.
    """

    _inherit = "hr.payslip"

    commission_line_ids = fields.One2many(
        comodel_name="invoice.commission.line",
        inverse_name="payslip_id",
        string="Comisiones",
        readonly=True,
    )
    commission_count = fields.Integer(compute="_compute_commission_count")

    @api.depends("commission_line_ids")
    def _compute_commission_count(self):
        # Se lee con sudo porque quien liquida la nómina no tiene por qué tener
        # permiso sobre las comisiones, y el número de facturas no revela nada
        # que no esté ya en el propio recibo.
        agrupado = {}
        if self.ids:
            agrupado = {
                recibo.id: cuenta
                for recibo, cuenta in self.env["invoice.commission.line"]
                .sudo()
                ._read_group(
                    [("payslip_id", "in", self.ids)], ["payslip_id"], ["__count"]
                )
            }
        for recibo in self:
            recibo.commission_count = agrupado.get(recibo.id, 0)

    def _commission_rule_codes(self):
        parametro = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(PARAMETRO_REGLAS, REGLAS_POR_DEFECTO)
        )
        return [c.strip() for c in parametro.split(",") if c.strip()]

    def _commission_payslip_amount(self):
        """Lo que el recibo dice que se paga de comisiones.

        Se suma sobre las líneas del recibo y no sobre las comisiones, porque
        el objetivo es justamente poder comparar las dos cifras.
        """
        self.ensure_one()
        codigos = self._commission_rule_codes()
        lineas = self.line_ids.filtered(lambda l: l.code in codigos)
        return sum(lineas.mapped("total"))

    # ------------------------------------------------------------------
    # Confirmar la hoja liquida sus comisiones
    # ------------------------------------------------------------------

    def _settle_commission_lines(self):
        """Sella la fecha de liquidación de las comisiones de este recibo.

        Hasta ahora esa fecha solo la ponía el lote, al generar los
        comprobantes. Y los lotes se quedan en borrador: de las 145 comisiones
        enlazadas a un recibo confirmado, ninguna tenía fecha. El resultado era
        que Recursos Humanos confirmaba la hoja, daba la comisión por pagada, y
        el sistema seguía diciendo «Por Liquidar» indefinidamente.

        El hecho que liquida la comisión es que se pagó en un recibo, y eso
        ocurre al confirmarlo. El lote sigue haciendo su parte —cerrar— sin
        cambios: solo rellena las que aún no tengan fecha.

        Se usa ``date_to`` y no el día de hoy porque la comisión se pagó en ese
        periodo de nómina, no el día en que alguien pulsó el botón.
        """
        Comision = self.env["invoice.commission.line"].sudo()
        for recibo in self:
            lineas = Comision.search(
                [("payslip_id", "=", recibo.id), ("settlement_date", "=", False)]
            )
            if not lineas:
                continue
            lineas.write(
                {"settlement_date": recibo.date_to or fields.Date.context_today(recibo)}
            )
            _logger.info(
                "custom_payroll: %s liquida %s comisión(es).",
                recibo.number or recibo.id,
                len(lineas),
            )

    def _unsettle_commission_lines(self):
        """Devuelve a pendiente lo que este recibo había liquidado.

        Si el recibo deja de estar confirmado, su comisión no está pagada. Sin
        esto quedaría marcada como liquidada para siempre y no la recogería
        ningún recibo posterior: dinero que el comercial no cobra y que nadie
        echa en falta, porque el sistema lo da por pagado.
        """
        Comision = self.env["invoice.commission.line"].sudo()
        for recibo in self:
            lineas = Comision.search(
                [("payslip_id", "=", recibo.id), ("settlement_date", "!=", False)]
            )
            if lineas:
                lineas.write({"settlement_date": False})

    def write(self, vals):
        """El estado de la comisión sigue al del recibo, venga por donde venga.

        Engancharse a los botones no basta. El estado del recibo se escribe
        desde varios sitios —``action_payslip_done``, el cierre del lote, y una
        vía de la localización colombiana que lo pone en «Pagada» sin pasar por
        ningún botón—, y cada uno que se olvide deja comisiones diciendo lo que
        no es.

        Todos acaban aquí, así que aquí es donde hay que mirar. Se comparan los
        estados antes y después para actuar solo sobre los recibos que de verdad
        cambiaron: ``write`` se llama constantemente por motivos que no tienen
        nada que ver.
        """
        if "state" not in vals:
            return super().write(vals)

        antes = {recibo.id: recibo.state for recibo in self}
        res = super().write(vals)

        liquidar = self.browse()
        soltar = self.browse()
        for recibo in self:
            if recibo.state == antes.get(recibo.id):
                continue
            if recibo.state in ESTADOS_LIQUIDADOS:
                liquidar |= recibo
            elif antes.get(recibo.id) in ESTADOS_LIQUIDADOS:
                # Solo se suelta si venía de estar liquidado. Pasar de borrador
                # a cancelado no tiene nada que soltar, y buscar por buscar en
                # cada guardado es trabajo tirado.
                soltar |= recibo

        if liquidar:
            liquidar._settle_commission_lines()
        if soltar:
            soltar._unsettle_commission_lines()
        return res

    def action_view_commission_detail(self):
        """Abre el desglose en una ventana emergente sobre el recibo."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Comisiones de %s", self.employee_id.name),
            "res_model": "commission.payslip.detail",
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_model": "hr.payslip",
                "active_id": self.id,
                "default_payslip_id": self.id,
            },
        }


class HrPayslipLine(models.Model):
    """Un botón en la línea de comisiones, que es donde se mira el importe.

    Yeny pidió poder pulsar sobre el monto. Hacer clicable la celda exigiría un
    componente propio; un botón en la misma fila llega al mismo sitio con las
    piezas estándar de Odoo, que es lo que conviene en un módulo que hereda de
    otros dos.
    """

    _inherit = "hr.payslip.line"

    is_commission_line = fields.Boolean(compute="_compute_is_commission_line")

    @api.depends("code")
    def _compute_is_commission_line(self):
        codigos = self.env["hr.payslip"]._commission_rule_codes()
        for linea in self:
            linea.is_commission_line = linea.code in codigos

    def action_open_commission_detail(self):
        self.ensure_one()
        return self.slip_id.action_view_commission_detail()
