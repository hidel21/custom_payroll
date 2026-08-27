import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Rellena la moneda de pago de los empleados que ya existían.

    El campo es calculado y almacenado, así que Odoo lo rellena solo al
    instalar. Pero un cálculo sobre miles de registros puede quedarse a medias
    si algo falla, y dejar el campo vacío significa que la comisión de esa
    persona no se convierte a ninguna moneda. Esto lo asegura por SQL, que es
    rápido y no depende de que ningún compute se dispare.

    Solo toca los que están vacíos: si alguien ya tenía una moneda puesta a
    mano —el caso de quien cobra en una moneda distinta a la de su compañía—,
    se respeta.
    """
    cr.execute(
        """
        UPDATE hr_employee e
           SET commission_currency_id = c.currency_id
          FROM res_company c
         WHERE c.id = e.company_id
           AND e.commission_currency_id IS NULL
        """
    )
    rellenados = cr.rowcount

    cr.execute(
        "SELECT count(*) FROM hr_employee WHERE commission_currency_id IS NULL"
    )
    sin_moneda = cr.fetchone()[0]

    _logger.info(
        "custom_payroll: moneda de pago rellenada en %s empleado(s) a partir "
        "de su compañía. Quedan %s sin moneda.",
        rellenados,
        sin_moneda,
    )
    if sin_moneda:
        _logger.warning(
            "custom_payroll: %s empleado(s) se han quedado sin moneda de pago, "
            "probablemente porque no tienen compañía. Sus comisiones no se "
            "convertirán hasta que se les asigne una.",
            sin_moneda,
        )
