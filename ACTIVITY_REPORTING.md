# AEYE: reportes de actividad

Este modulo convierte los conteos anonimos de cada camara en reportes diarios
por puesto. No identifica empleados y no vincula movimientos entre camaras.

## Estado actual

El sistema ya puede:

- guardar conteos dentro de una region de interes (ROI) por camara;
- medir ocupacion media, minima, maxima, horas-persona y cobertura de datos;
- comparar la ocupacion con una dotacion fija por puesto;
- estimar cupos que llegaron tarde, se retiraron antes o siguieron presentes
  despues del turno;
- estimar pausas iniciadas durante la ventana de comida y sus excesos;
- registrar tracks locales y temporales en bano y comedor;
- medir entradas, salidas y duraciones anonimas con una linea de acceso;
- consultar reportes diarios, semanales y mensuales desde el dashboard;
- revisar cobertura, ocupacion y eventos por cada turno del reporte diario;
- comparar llegadas tarde, salidas anticipadas y alertas por puesto;
- abrir una subpestana por camara con ocupacion horaria y evidencia diaria;
- descargar el reporte diario en CSV y el semanal o mensual como PNG o PDF.

La camara 7 esta configurada como `restroom` y la 8 como `dining`. Sus
lineas de acceso quedan desactivadas hasta dibujarlas sobre una imagen real.
Mientras tanto se guardan ocupacion y tracks visibles, pero no se presenta una
duracion de visita como si fuera fiable.

## Configuracion de turnos

Esta instalacion usa dos turnos de lunes a viernes:

```json
"reporting": {
  "enabled": true,
  "timezone": "America/Argentina/Buenos_Aires",
  "workdays": [0, 1, 2, 3, 4],
  "shift": {
    "arrival_grace_minutes": 5,
    "early_departure_tolerance_minutes": 5,
    "overtime_tolerance_minutes": 10,
    "overtime_observation_minutes": 180
  },
  "shifts": [
    {
      "id": "morning",
      "name": "Turno mañana",
      "start": "07:00",
      "end": "16:00",
      "meal": {
        "window_start": "12:30",
        "window_end": "13:00",
        "allowed_minutes": 30
      }
    },
    {
      "id": "afternoon",
      "name": "Turno tarde",
      "start": "16:00",
      "end": "00:00",
      "meal": {
        "window_start": "21:30",
        "window_end": "22:00",
        "allowed_minutes": 30
      }
    }
  ]
}
```

Los dias usan lunes `0` a domingo `6`. Los horarios son locales y usan
`HH:MM`. Un turno cuya salida es anterior al inicio se interpreta como un
turno que cruza medianoche. Cada pausa se evalua solamente dentro de la
ventana del turno correspondiente: 12:30-13:00 por la manana y 21:30-22:00 por
la tarde.

Los puestos se ordenan por nombre operativo: Montaje 1, Montaje 2, Montaje 3,
Montaje 4, Montaje 5 y Portico 2. Las camaras fisicas asociadas son 1, 2, 5,
4, 3 y 6 respectivamente.

En cada puesto, completar el nombre, zona y cantidad fija:

```json
{
  "id": "cam02",
  "name": "Puesto de armado",
  "zone": "Armado",
  "role": "workstation",
  "reporting_enabled": true,
  "expected_people": 2,
  "monitor_staffing": true,
  "roi": [[0.12, 0.18], [0.91, 0.18], [0.91, 0.96], [0.12, 0.96]]
}
```

En las camaras 1 a 6, `expected_people: 2` significa dos personas simultaneas
por turno. El sistema evalua por separado hasta dos llegadas a las 07:00 y
otras dos a las 16:00. `monitor_staffing` solo genera incidentes durante los
turnos y se suspende de 00:00 a 07:00 y en dias no laborables. Bano y comedor
no tienen dotacion esperada ni generan alertas de personal.

La ROI usa coordenadas normalizadas entre 0 y 1. AEYE cuenta un track cuando el
centro inferior de su caja esta dentro del poligono. La ROI inicial cubre toda
la imagen y debe ajustarse para excluir pasillos o puestos vecinos.

## Linea de acceso

Para las camaras 7 y 8 hay que ubicar una linea que toda persona cruce al entrar:

```json
"access_line": {
  "enabled": true,
  "start": [0.20, 0.52],
  "end": [0.82, 0.52],
  "inside_side": "left",
  "hysteresis": 0.015
}
```

`start` y `end` tambien son coordenadas normalizadas. Si entradas y salidas
aparecen invertidas, cambiar `inside_side` entre `left` y `right`.

Las duraciones se emparejan por orden FIFO: la primera salida cierra la entrada
abierta mas antigua. Esto es una estimacion anonima razonable cuando el acceso
es angosto y bien visible. Pierde fiabilidad con cruces simultaneos, oclusiones,
otra puerta, permanencias fuera de cuadro o reinicios. Las visitas abiertas al
reiniciar se marcan como abortadas y no se inventa una duracion.

## Como se calculan las metricas

- **Ocupacion media:** integral del conteo suavizado durante intervalos validos.
- **Cobertura de datos:** tiempo con muestras validas dividido por el periodo.
- **Dotacion completa:** tiempo valido con conteo mayor o igual a la cantidad
  esperada.
- **Horas-persona faltantes:** integral de la diferencia entre cantidad esperada
  y conteo observado.
- **Llegadas tarde:** primera hora en que cada cupo anonimo aparece, comparada
  con el inicio y su tolerancia.
- **Salida anticipada:** ultima presencia de cada cupo antes de terminar el
  turno.
- **Despues de hora:** cupos que siguen observados despues de la tolerancia de
  salida.
- **Pausa de comida:** ausencia de un cupo que comienza dentro de la ventana de
  comida.

Un cupo anonimo no es un empleado. Por ejemplo, en un puesto de dos personas,
el sistema razona sobre "cupo 1" y "cupo 2" segun el conteo, sin saber quien
es quien. Por eso estas metricas sirven para operacion agregada, no para
sanciones individuales.

Si al comenzar un turno se esperan tres personas y el conteo es uno, existen dos cupos
sin cubrir. Esos cupos se consideran llegadas tarde solo si siguen ausentes al
terminar `arrival_grace_minutes` (cinco minutos en la configuracion actual) y
hay al menos 80 % de cobertura en la ventana inicial de 15 minutos. Cuando el
conteo alcanza dos y luego tres, se registra la demora estimada de cada cupo.
Una oclusion, una ROI incorrecta o una persona fuera de su puesto pueden parecer
una demora; por eso no equivale a una marcacion de ingreso.

En el relevo de las 16:00, si salen dos personas y entran otras dos sin cambiar
el conteo, AEYE solo puede afirmar que el turno tarde comenzo con dos cupos
cubiertos. Sin identificacion o control de acceso no puede demostrar que las
personas efectivamente cambiaron.

Las **alertas emitidas** son incidentes de dotacion que superaron el tiempo de
confirmacion y alcanzaron `alert_after_seconds`. No son todas las variaciones
de ocupacion ni son lo mismo que las llegadas tarde estimadas. Fuera de los
turnos no se abren alertas de faltantes.

Los intervalos `no_data` reducen la cobertura y nunca se convierten en cero
personas. En el dia actual, la cobertura usa solamente el tiempo laboral ya
transcurrido; cada turno distingue `not_started`, `in_progress`
y `complete`. Los eventos cuya ventana aun no termino usan
`pending`, no `insufficient_data`. Si falta configuracion o
evidencia suficiente, la API devuelve `null` y el dashboard muestra
`Pendiente` o `Sin datos`.

## Dashboard y API

`./run.sh` inicia el motor de vision y FastAPI en el mismo contenedor.

- Dashboard de reportes: `http://aeye.local/`
- OpenAPI: `http://aeye.local/docs`
- Respaldo directo: `http://IP_DE_LA_JETSON:8000`
- Reporte JSON: `GET /api/reports/daily?day=AAAA-MM-DD`
- Reporte semanal JSON: `GET /api/reports/weekly?week=AAAA-MM-DD`
- Reporte mensual JSON: `GET /api/reports/monthly?month=AAAA-MM-DD`
- Descarga CSV: `GET /api/reports/daily.csv?day=AAAA-MM-DD`
- Configuracion efectiva: `GET /api/reporting/configuration`

La vista semanal toma de lunes a domingo y la mensual usa el mes calendario.
Cada periodo ofrece una subpestana `General` y una por camara. En un puesto se
muestran ocupacion por hora con su porcentaje exacto, puntualidad, salidas,
pausas, alertas y evolucion diaria. En bano y comedor no se muestran eventos
laborales de llegada porque no existe una dotacion de puesto atribuible.

Las vistas semanal y mensual permiten descargar una imagen PNG. El boton
`Guardar PDF` abre la impresion del navegador con una hoja A4 horizontal;
seleccionar `Guardar como PDF` genera el archivo para jefatura.

Por decision de esta instalacion, el puerto 8000 no usa usuario ni contrasena:
cualquier equipo de la red local puede ver los reportes. No debe publicarse en
Internet ni reenviarse desde el router. El visor con imagenes en el puerto 8080
queda ligado a `127.0.0.1` y solo es accesible desde la Jetson.

## Limites y validacion

La configuracion de horarios todavia no esta versionada. Los datos anteriores
a la migracion de multiples turnos del 8 de septiembre de 2026 no se certifican
como historicos de dos turnos; se interpretan con la configuracion actual.

Antes de usar porcentajes como indicadores formales conviene validar por camara:

1. ajustar la ROI y la linea de acceso con imagenes reales;
2. comparar conteos contra anotaciones humanas en varios turnos;
3. exigir una cobertura de datos alta, idealmente superior al 95 %;
4. revisar por separado oclusiones, cambios de luz y horas de mayor movimiento;
5. usar entre 24 y 72 horas de observacion continua antes de fijar una linea base.

La auditoria reproducible abre SQLite en modo solo lectura:

```bash
python3 tools/audit_activity_data.py   --day AAAA-MM-DD   --configuration-valid-from 2026-09-09   --visual-labels /ruta/local/conteos.csv
```

El CSV visual permanece en la Jetson y contiene
`camera_id,shift_id,observed_at,reported_count,manual_count`. Para las ocho camaras y dos turnos son 160 observaciones locales. Para
aprobar cada combinacion de camara y turno se requieren 10 observaciones,
cobertura temporal minima de 95 % y al menos 90 % de conteos exactos. El
resultado tambien informa error absoluto medio, sesgo, sobreconteos y
subconteos. Sin etiquetas suficientes, el estado queda `pending`.

AEYE no puede afirmar quien llego tarde, quien fue al bano ni si una ausencia
esta justificada. Tampoco vincula por ahora un faltante de un puesto con una
entrada al bano o al comedor. Esas inferencias quedaron explicitamente fuera de
este MVP.
