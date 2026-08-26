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
