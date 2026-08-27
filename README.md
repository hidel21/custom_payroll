# custom_payroll — Liquidación de comisiones en nómina

Todo lo que tiene que ver con **pagarle la comisión al comercial**, separado de
cómo se calcula. El cálculo y el desglose viven en
[`account_custom`](https://github.com/hidel21/account_custom); aquí vive el
circuito de liquidación.

> El nombre técnico es `custom_payroll`, con guion bajo: Odoo exige que el
> nombre del módulo sea un identificador Python válido.

## Por qué está separado

`account_custom` responde a «cuánto se le debe y por qué». Este módulo responde
a «cuándo se le pagó». Son dos ciclos de vida distintos, los llevan dos áreas
distintas, y mezclarlos obligaba a tocar contabilidad para arreglar nómina.

## Las dos fechas, que no son lo mismo

| Fecha | Qué significa | Quién la pone |
|---|---|---|
| **Fecha de Pago** | Cuándo pagó **el cliente** la factura | El sistema, al registrarse el pago |
| **Fecha de Liquidación** | Cuándo se le pagó la comisión **al comercial** | La nómina, o RRHH con el asistente |

Confundirlas era el origen del problema: el sistema sabía que el cliente había
pagado, pero no guardaba en ninguna parte que la comisión ya se hubiera
liquidado.

## Los estados siguen a los hechos

```
Borrador → Por Cobrar → Por Liquidar → Liquidada → Cerrada
                     y aparte: Fuera de Corte · En Mora
```

| Estado | Lo que lo provoca |
|---|---|
| `draft` **Borrador** | Se añadió el empleado, aún sin calcular |
| `calculated` **Por Cobrar** | Calculada, el cliente todavía no ha pagado |
| `client_paid` **Por Liquidar** | Hay fecha de pago: pagó el cliente, falta pagarle al comercial |
| `paid` **Liquidada** | Hay fecha de liquidación: se le pagó al comercial |
| `closed` **Cerrada** | Además, el lote de nómina está cerrado |
| `out_of_cycle` **Fuera de Corte** | Cobró tras el cierre; se liquida en la siguiente |
| `overdue` **En Mora** | El cliente lleva meses sin pagar |

Los cuatro primeros se deducen de las fechas y del estado del lote. Los dos
últimos se marcan a mano. Ninguno se teclea a dedo, de modo que dos personas no
puedan interpretarlo distinto.

## Qué aporta

**El asistente «Marcar como liquidada».** En el Reporte de Comisiones se
seleccionan las comisiones ya pagadas y se marcan de una vez, con fecha
editable —hace falta para registrar liquidaciones de meses anteriores—. Dejan de
entrar en los cálculos de nómina siguientes.

**Filtros de trabajo.** *Pendientes de liquidar*, *Ya liquidadas* y *Calculadas
en cero*, más la agrupación por fecha de liquidación.

**La recogida de comisiones para el recibo**, que sustituye a la del módulo
original. Descarta lo ya liquidado, admite recalcular el mismo recibo sin
vaciarlo, y convierte la moneda.

## Lo que corrige del módulo original

El original marcaba las comisiones como pagadas **solo si alguien pulsaba** el
botón de generar comprobantes del lote. Si no se pulsaba, la comisión seguía
disponible y el cálculo del mes siguiente la volvía a incluir.

Además su regla salarial llevaba una copia de la lógica de recogida dentro del
código de la regla, con dos fallos: no comprobaba si la comisión ya estaba en
otro recibo —podía pagarse dos veces— y no convertía la moneda, así que una
comisión en dólares se sumaba como si fueran pesos.

Al instalarse, este módulo **ajusta esas reglas** para que llamen al método del
módulo. Es idempotente y conservador: si una regla no tiene la forma esperada no
la toca, solo avisa en el log.

## Instalación

Depende de `account_custom` y `om_hr_payroll`.

```bash
./odoo-bin -c odoo.conf -d <bd> -i custom_payroll --stop-after-init
```

Si `account_custom` cambia de versión en el mismo despliegue, hay que actualizar
los dos **en la misma orden**: mover un campo almacenado entre módulos en dos
pasos separados le borra la columna.

## Después de instalar

Lanzar una vez, desde *Ajustes → Técnico → Acciones planificadas*, la acción
**Comisiones: poner al día estados de liquidación**. Pone el estado de acuerdo
con las fechas en lo que ya existía; sin ella, lo antiguo se queda como estaba
porque nadie va a volver a escribir en esas líneas.

## Documentación

`doc/ajustes_funcionales.html` y su PDF explican, sin lenguaje técnico, qué
cambia para Recursos Humanos y qué validar.

## Comisiones en varias monedas

Hay comerciales contratados en un país que venden en otro. Kerlyn está en la
compañía de Estados Unidos y cobra en dólares, pero factura en Venezuela y en
Colombia; Andrés está en la de Colombia y cobra en pesos. La comisión nace en la
moneda de la venta y hay que pagarla en la de la persona.

### El módulo que se extiende

Todo el cálculo de comisiones vive en **`intelli_commision`** (módulo de
terceros, no se toca su código). Su modelo central es
**`invoice.commission.line`**: una línea por empleado y factura.

| Campo | Qué es |
|---|---|
| `commission_amount` | El importe de la comisión. **Siempre en la moneda de la factura** |
| `currency_id` | La moneda de origen. Es un *related* a `invoice_id.currency_id` |
| `company_id` | *Related* a la compañía de la factura |

Este módulo lo extiende por herencia (`_inherit`) y le añade la otra punta:

| Campo añadido | Qué es |
|---|---|
| `employee_currency_id` | Moneda en la que cobra el comercial |
| `conversion_date` | Día cuya tasa se aplicó |
| `commission_amount_employee` | **El importe que se paga**, ya convertido |
| `conversion_warning` | Se rellena cuando la conversión no es de fiar |

Los tres últimos son calculados y almacenados, así que se pueden filtrar,
agrupar y sacar en informes.

### La moneda de pago de un empleado

Se configura en **Empleados → la ficha → pestaña Ajustes → Información de
Comisiones**, campo *Moneda de pago de comisiones*.

Se rellena sola con la moneda de la compañía del empleado y se puede cambiar a
mano. Una vez cambiada se respeta: cambiar de compañía no la pisa. Al instalar,
una migración la rellena en todos los empleados que ya existían.

**No se llama `currency_id` a propósito.** Ese nombre ya está ocupado en
`hr.employee` por el propio Odoo, como *related* a `company_id.currency_id`, y
lo usan la nómina y los contratos. Redefinirlo para hacerlo editable cambiaría
su significado por debajo a todo lo que ya lo lee.

### Con qué fecha se convierte

En **Ajustes → Nómina → Comisiones**: la fecha de la factura (por defecto) o la
del cobro. Al cambiarlo se recalculan todas las comisiones no liquidadas.

La conversión usa el método estándar de Odoo, `_convert`, que redondea con los
decimales de la moneda de destino. Si origen y destino son la misma moneda no se
convierte nada: el importe queda idéntico, sin redondeos de ida y vuelta.

### De dónde salen las tasas de cambio

De `res.currency.rate`, que alimenta el módulo **`currency_rate_live`** de
Enterprise. El proveedor se elige por compañía en *Ajustes → Contabilidad →
Monedas*, y hoy está así:

| Compañía | Moneda | Proveedor |
|---|---|---|
| Intelli Next S.A.S, Joobpay S.A.S, My Intelli S.A.S | COP | `banrepco` (Banco de la República) |
| Intelli Next Corp., Joobpay Inc. | USD | `ecb` (Banco Central Europeo) |
| My Intelli SL. | EUR | `ecb` |
| Intelli Next C.A | VEF | `ecb` |

**El bolívar no lo cubre ninguno de los dos**, así que tiene proveedor propio:
`bcv`, añadido por `account_custom` al mismo desplegable. Lee la tasa oficial
del Banco Central de Venezuela desde `ve.dolarapi.com`, en JSON y sin clave. Se
prefiere a leer la web del propio BCV porque esa sirve una cadena de
certificados incompleta —habría que saltarse la verificación TLS— y publica la
tasa dentro del HTML de la portada.

Un cron diario lleva además esa tasa a **todas** las compañías, no solo a la
venezolana: una venta facturada en Venezuela puede comisionar a alguien de
Colombia, y sin tasa de VES en esa compañía la conversión no se hace.

### El histórico

Las comisiones se convierten con la tasa del día de su factura, así que sin
serie histórica no se pueden valorar hacia atrás. La operación
`_cron_cargar_historico` la trae de tres sitios, porque ninguno cubre todo:

| Fuente | Qué aporta |
|---|---|
| Banco Central Europeo | Serie diaria desde 1999, 41 monedas. Dólar, euro y peso mexicano |
| TRM del Banco de la República | Peso colombiano, vía datos abiertos |
| `ve.dolarapi.com` | Tasa oficial del BCV desde enero de 2023 |

Es repetible: lo ya guardado no se vuelve a escribir.

### Cuando la tasa no es de fiar

Odoo, cuando no encuentra tasa, convierte 1:1 en silencio. Un peso colombiano
no vale un dólar, así que ese resultado parece correcto y no lo es. Por eso el
campo `conversion_warning` se rellena en dos casos:

* **No hubo conversión real**: el importe convertido salió idéntico al
  original habiendo cambiado de moneda.
* **La tasa es vieja**: la más cercana anterior está a más de siete días de la
  fecha usada. Se aplica igualmente —es el comportamiento estándar de Odoo,
  usar la anterior más cercana— pero queda marcado para revisión.

En el Reporte de Comisiones hay un filtro **Conversión a revisar** que las lista.

### Lo que cobra la nómina

`_get_employee_commision` suma **`commission_amount_employee`**, nunca el
importe original. Si el recibo se emite en una moneda distinta a la de pago del
comercial, hace un último salto con la misma fecha de referencia.

### El bolívar: VEF y VES

La compañía venezolana se creó con la moneda **VEF**, el bolívar antiguo, pero
los importes que hay en la base ya son bolívares actuales: lo que estaba mal era
la etiqueta.

Cambiar `company.currency_id` no es el camino —Odoo lo prohíbe en cuanto hay
apuntes contables, y con razón: cambiar de registro de moneda no reconvierte los
importes, solo cambia con qué unidad se leen—. Lo que se hace es renombrar el
registro que ya está en uso, conservando id, asientos e importes:

```python
env['res.company'].migrar_bolivar_a_ves()
```

No está en ningún menú a propósito: es una operación de una vez y con copia de
seguridad delante. Se niega si hay asientos en las dos monedas.
