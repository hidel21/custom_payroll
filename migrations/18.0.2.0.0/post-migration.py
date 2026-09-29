"""Rescata las marcas de «Liquidada» que la sincronización venía deshaciendo.

Hasta ahora el estado se deducía solo de las fechas, así que marcar una
comisión como Liquidada a mano no duraba: la siguiente sincronización la
devolvía a Por Cobrar y no entraba en ninguna nómina. Quien lo intentaba
acababa cruzando pagos provisionales a mano.

Las que están en ese estado justo ahora son las que alguien marcó y el sistema
todavía no ha deshecho. Se les enciende la autorización para que la intención
sobreviva a la actualización en lugar de perderse en el primer cron.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE invoice_commission_line
           SET settlement_authorized = TRUE
         WHERE state = 'paid'
           AND settlement_date IS NULL
           AND COALESCE(settlement_authorized, FALSE) IS FALSE
        """
    )
    _logger.info(
        "custom_payroll: %s comisión(es) marcadas a mano como Liquidadas pasan "
        "a tener el pago autorizado sin cobro.",
        cr.rowcount,
    )
