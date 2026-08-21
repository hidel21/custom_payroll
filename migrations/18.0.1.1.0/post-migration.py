from odoo.addons.custom_payroll.hooks import ajustar_reglas_de_comision


def migrate(cr, version):
    """Ajusta las reglas en instalaciones donde el módulo ya estaba.

    El ``post_init_hook`` solo corre al instalar, así que sin esto una base que
    ya tuviera el módulo se quedaría con las reglas viejas y la nómina dejaría
    de recoger comisiones.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    ajustar_reglas_de_comision(env)
