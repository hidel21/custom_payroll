import logging
import re

_logger = logging.getLogger(__name__)

# Las reglas salariales de comisiones llevan su propia copia de la lógica de
# recogida dentro del campo de código Python, en lugar de llamar al módulo. Eso
# tiene tres problemas: filtra por un estado que con el circuito nuevo ya no se
# da —así que la nómina dejaría de recoger comisiones—, no comprueba si la
# comisión ya está en otro recibo, y no convierte la moneda.
#
# Se reconoce la regla por las dos señas de esa copia y se sustituye por una
# llamada al método del módulo, que hace las tres cosas bien. El nombre de la
# entrada manual (COMISIONES, COMISIONPR…) se conserva tal cual.
SENAS = ('invoice.commission.line', "'calculated'")

PLANTILLA = '''# Comisiones cobradas al cliente y aún no liquidadas al comercial.
#
# La lógica vive en el módulo custom_payroll, que descarta lo ya liquidado,
# admite recalcular este mismo recibo sin vaciarlo y convierte la moneda.
# Antes esta regla llevaba su propia copia, filtrando por un estado que el
# circuito de liquidación ya no usa.
other_com = (inputs.%(entrada)s and inputs.%(entrada)s.amount) or 0.0
result = other_com + payslip.env['invoice.commission.line']._get_employee_commision(employee, payslip)
'''


def ajustar_reglas_de_comision(env):
    """Deja las reglas salariales de comisiones llamando al módulo.

    Es idempotente: una regla ya ajustada se reconoce y se salta, así que se
    puede volver a ejecutar sin miedo. Y es conservadora: si una regla no tiene
    la forma esperada no se toca, solo se avisa en el log, porque cambiar a
    ciegas el cálculo de una nómina es peor que dejarlo como está.
    """
    reglas = env['hr.salary.rule'].sudo().with_context(active_test=False).search([])
    ajustadas, ya_estaban, revisar = [], [], []

    for regla in reglas:
        codigo = regla.amount_python_compute or ''
        if '_get_employee_commision' in codigo:
            ya_estaban.append(regla.code)
            continue
        if not all(sena in codigo for sena in SENAS):
            continue

        entradas = re.findall(r'inputs\.(\w+)', codigo)
        if not entradas:
            revisar.append(regla.code)
            continue

        regla.amount_python_compute = PLANTILLA % {'entrada': entradas[0]}
        ajustadas.append(regla.code)

    if ajustadas:
        _logger.info(
            "custom_payroll: %s regla(s) salarial(es) de comisiones ahora "
            "llaman al módulo: %s", len(ajustadas), ', '.join(ajustadas))
    if ya_estaban:
        _logger.info(
            "custom_payroll: %s regla(s) ya estaban ajustadas: %s",
            len(ya_estaban), ', '.join(ya_estaban))
    if revisar:
        _logger.warning(
            "custom_payroll: %s regla(s) parecen de comisiones pero no tienen "
            "la forma esperada y NO se han tocado; revíselas a mano: %s",
            len(revisar), ', '.join(revisar))

    return {'ajustadas': ajustadas, 'ya_estaban': ya_estaban,
            'revisar': revisar}


def post_init_hook(env):
    ajustar_reglas_de_comision(env)
