"""Que el tope del 40% reparta la comisión y no cambie lo que cobra nadie.

El caso que dio origen a esto: a Óscar Cely se le pagaron 4.022.969,18 de
comisiones sobre un salario básico de 3.200.000, y la bonificación que se
reporta a la DIAN no puede pasar del 40% del básico. El excedente no se deja
de pagar: se entrega como anticipo y se cruza después.

La regla de oro, y lo que más vigilan estos tests: **la suma de las dos
partes es siempre el total**. Esto clasifica, no decide cuánto se paga. Si
algún día un cambio hiciera que las partes no sumaran el total, alguien
cobraría de menos sin que nada avisara.
"""

from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

RUTA = (
    "odoo.addons.custom_payroll.models.invoice_commission_line"
    ".InvoiceCommissionLine._get_employee_commision"
)


class ReciboDePrueba:
    """Lo mínimo que el reparto necesita de un recibo: su moneda.

    Un hr.payslip de verdad arrastra empleado, contrato y estructura salarial,
    y nada de eso interviene en el reparto. Montarlo solo haría el test lento
    y frágil frente a cambios de nómina que no tienen que ver con esto.
    """

    def __init__(self, company):
        self.company_id = company


@tagged("post_install", "-at_install")
class TestTopeNoSalarial(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Comision = cls.env["invoice.commission.line"]
        cls.empleado = cls.env["hr.employee"].create({"name": "Empleado de prueba"})
        cls.recibo = ReciboDePrueba(cls.env.company)
        cls.basico = 3200000.0

    def _repartir(self, total, basico=None, otros=0.0):
        with patch(RUTA, return_value=total):
            return self.Comision._comision_con_tope(
                self.empleado,
                self.recibo,
                self.basico if basico is None else basico,
                otros,
            )

    # ── el caso que lo originó ───────────────────────────────────────
    def test_el_caso_de_septiembre(self):
        dentro, excedente = self._repartir(4022969.18)
        self.assertAlmostEqual(dentro, 1280000.00, places=2)
        self.assertAlmostEqual(excedente, 2742969.18, places=2)

    # ── la regla de oro ──────────────────────────────────────────────
    def test_las_partes_siempre_suman_el_total(self):
        for total in (0.0, 500000.0, 1280000.0, 1280000.01, 4022969.18, 99999999.99):
            with self.subTest(total=total):
                dentro, excedente = self._repartir(total)
                self.assertAlmostEqual(dentro + excedente, total, places=2)

    # ── cuándo NO hay que partir nada ────────────────────────────────
    def test_por_debajo_del_tope_no_se_parte(self):
        dentro, excedente = self._repartir(947518.15)
        self.assertAlmostEqual(dentro, 947518.15, places=2)
        self.assertEqual(excedente, 0.0)

    def test_justo_en_el_tope_no_se_parte(self):
        dentro, excedente = self._repartir(1280000.0)
        self.assertAlmostEqual(dentro, 1280000.0, places=2)
        self.assertEqual(excedente, 0.0)

    def test_sin_comision_no_se_parte(self):
        self.assertEqual(self._repartir(0.0), (0.0, 0.0))

    def test_un_ajuste_a_la_baja_no_es_una_bonificacion(self):
        """Un total negativo no se reparte: no hay nada que topar."""
        dentro, excedente = self._repartir(-50000.0)
        self.assertAlmostEqual(dentro, -50000.0, places=2)
        self.assertEqual(excedente, 0.0)

    def test_sin_salario_basico_no_hay_tope(self):
        """Sin base no se puede calcular un porcentaje, así que no se parte."""
        dentro, excedente = self._repartir(4022969.18, basico=0.0)
        self.assertAlmostEqual(dentro, 4022969.18, places=2)
        self.assertEqual(excedente, 0.0)

    # ── lo que se añade a mano entra en el reparto ───────────────────
    def test_lo_anadido_a_mano_tambien_cuenta(self):
        """El input de comisiones suma antes de aplicar el tope.

        Si quedara fuera, bastaría con teclear la comisión a mano para
        saltarse el tope sin querer.
        """
        dentro, excedente = self._repartir(1000000.0, otros=500000.0)
        self.assertAlmostEqual(dentro, 1280000.00, places=2)
        self.assertAlmostEqual(excedente, 220000.00, places=2)

    # ── el porcentaje es configurable ────────────────────────────────
    def test_el_porcentaje_se_puede_cambiar(self):
        """El criterio es contable, no técnico: tiene que moverse sin código."""
        self.env["ir.config_parameter"].sudo().set_param(
            "custom_payroll.tope_no_salarial", "50")
        dentro, excedente = self._repartir(4022969.18)
        self.assertAlmostEqual(dentro, 1600000.00, places=2)
        self.assertAlmostEqual(excedente, 2422969.18, places=2)

    def test_por_defecto_es_el_cuarenta_por_ciento(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "custom_payroll.tope_no_salarial", "")
        dentro, _excedente = self._repartir(4022969.18)
        self.assertAlmostEqual(dentro, 1280000.00, places=2)
