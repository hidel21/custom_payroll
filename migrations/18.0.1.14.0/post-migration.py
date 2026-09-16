import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Estados de recibo en los que la comisión ya se pagó.
RECIBOS_CERRADOS = ("done", "paid")


def migrate(cr, version):
    """Pone fecha de liquidación a lo que ya se pagó y no la tenía.

    A partir de esta versión, confirmar el recibo sella la fecha de
    liquidación. Pero eso solo arregla lo que venga: las comisiones ya pagadas
    en recibos confirmados seguirían diciendo «Por Liquidar» para siempre,
    porque su lote se quedó en borrador y nadie va a volver a confirmarlas.

    Se les pone la fecha de fin del recibo en el que se pagaron, que es cuando
    de verdad se liquidaron. Solo se tocan las que no tienen fecha: si alguna la
    tiene puesta, aunque sea otra, se respeta.
    """
    cr.execute(
        """
        UPDATE invoice_commission_line c
           SET settlement_date = p.date_to
          FROM hr_payslip p
         WHERE p.id = c.payslip_id
           AND p.state IN %s
           AND c.settlement_date IS NULL
           AND p.date_to IS NOT NULL
        """,
        (RECIBOS_CERRADOS,),
    )
    tocadas = cr.rowcount
    if not tocadas:
        _logger.info(
            "custom_payroll: no había comisiones pagadas sin fecha de liquidación."
        )
        return

    _logger.info(
        "custom_payroll: %s comisión(es) de recibos ya confirmados pasan a "
        "liquidadas; su estado se recalcula a continuación.",
        tocadas,
    )

    # El estado es un campo almacenado que se deduce de las fechas, y el UPDATE
    # de arriba va por SQL y se salta el ORM. Sin este paso, las líneas tendrían
    # ya la fecha y seguirían enseñando «Por Liquidar», que es exactamente el
    # problema que esta migración viene a quitar.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["invoice.commission.line"]._cron_sync_payroll_state()
    _logger.info("custom_payroll: estados de comisión resincronizados.")
