from odoo import api, models


class CommissionMaintenanceWizard(models.TransientModel):
    """Añade al mantenimiento la puesta al día de los estados de liquidación.

    La operación vive aquí y no en ``account_custom`` porque depende de la fecha
    de liquidación, que la aporta este módulo. Extender la lista en lugar de
    editarla mantiene la regla de siempre: cada módulo trae lo suyo y ninguno
    tiene que saber de los demás.
    """

    _inherit = "commission.maintenance.wizard"

    @api.model
    def _maintenance_tasks(self):
        tareas = super()._maintenance_tasks()
        tareas.append(
            {
                "key": "payroll_states",
                "name": "Poner al día los estados de liquidación",
                "help": "Repasa todas las comisiones y pone su estado de "
                "acuerdo con las fechas: si el cliente ya pagó queda en "
                "Pagada, si se le pagó al comercial en Liquidada, y si el lote "
                "de nómina se cerró en Cerrada.\n\nHace falta después de "
                "instalar o de corregir fechas a mano, porque el estado de las "
                "comisiones que ya existían no se recalcula solo. No toca las "
                "que están en Borrador, Fuera de Corte ni En Mora.",
            }
        )
        return tareas

    def _run_payroll_states(self):
        Linea = self.env["invoice.commission.line"]
        antes = {}
        for estado, _etiqueta in Linea._fields["state"].selection:
            antes[estado] = Linea.search_count([("state", "=", estado)])

        Linea._cron_sync_payroll_state()
        self.env.flush_all()

        etiquetas = dict(Linea._fields["state"].selection)
        lineas = ["Estados después de la puesta al día:", ""]
        movidas = 0
        for estado, etiqueta in Linea._fields["state"].selection:
            ahora = Linea.search_count([("state", "=", estado)])
            if not ahora and not antes[estado]:
                continue
            diferencia = ahora - antes[estado]
            movidas += max(diferencia, 0)
            lineas.append(
                "   %-16s %5s %s"
                % (
                    etiquetas.get(estado, estado),
                    ahora,
                    "(%+d)" % diferencia if diferencia else "",
                )
            )
        lineas += [
            "",
            "%s comisión(es) han cambiado de estado." % movidas
            if movidas
            else "Ninguna comisión ha cambiado de estado: ya estaban al día.",
        ]
        return "\n".join(lineas)
