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
- consultar un dia desde el dashboard y descargar una fila por puesto en CSV.

La camara 7 esta configurada como `restroom` y la 8 como `dining`. Sus
lineas de acceso quedan desactivadas hasta dibujarlas sobre una imagen real.
Mientras tanto se guardan ocupacion y tracks visibles, pero no se presenta una
duracion de visita como si fuera fiable.

## Configuracion pendiente

Editar el bloque `reporting` de `cameras.json`:

```json
"reporting": {
  "enabled": true,
  "timezone": "America/Argentina/Buenos_Aires",
  "workdays": [0, 1, 2, 3, 4],
  "shift": {
    "start": "08:00",
    "end": "17:00",
    "arrival_grace_minutes": 5,
    "early_departure_tolerance_minutes": 5,
    "overtime_tolerance_minutes": 10,
    "overtime_observation_minutes": 180
  },
  "meal": {
    "window_start": "12:00",
    "window_end": "14:00",
    "allowed_minutes": 30
  }
}
```

Los dias usan lunes `0` a domingo `6`. Los horarios son locales y usan
`HH:MM`. Un turno cuya salida es anterior al inicio se interpreta como un
turno que cruza medianoche.

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

Cuando `expected_people` sea conocido, `monitor_staffing` puede quedar en
`true` para generar incidentes. Los puestos sin cantidad confirmada siguen
registrando ocupacion, pero no generan alertas ni metricas de cumplimiento.

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

Los intervalos `no_data` reducen la cobertura y nunca se convierten en cero
personas. Si falta configuracion o evidencia suficiente, la API devuelve
`null` y el dashboard muestra `Pendiente` o `Sin datos`.

## Dashboard y API

`./run.sh` inicia el motor de vision y FastAPI en el mismo contenedor.

- Dashboard de reportes: `http://IP_DE_LA_JETSON:8000`
- OpenAPI: `http://IP_DE_LA_JETSON:8000/docs`
- Reporte JSON: `GET /api/reports/daily?day=AAAA-MM-DD`
- Reporte semanal JSON: `GET /api/reports/weekly?week=AAAA-MM-DD`
- Descarga CSV: `GET /api/reports/daily.csv?day=AAAA-MM-DD`
- Configuracion efectiva: `GET /api/reporting/configuration`

La vista semanal toma de lunes a domingo y permite descargar una imagen PNG.
El boton `Guardar PDF` abre la impresion del navegador con una hoja A4
horizontal; seleccionar `Guardar como PDF` genera el archivo para jefatura.

Por decision de esta instalacion, el puerto 8000 no usa usuario ni contrasena:
cualquier equipo de la red local puede ver los reportes. No debe publicarse en
Internet ni reenviarse desde el router. El visor con imagenes en el puerto 8080
queda ligado a `127.0.0.1` y solo es accesible desde la Jetson.

## Limites y validacion

Antes de usar porcentajes como indicadores formales conviene validar por camara:

1. ajustar la ROI y la linea de acceso con imagenes reales;
2. comparar conteos contra anotaciones humanas en varios turnos;
3. exigir una cobertura de datos alta, idealmente superior al 95 %;
4. revisar por separado oclusiones, cambios de luz y horas de mayor movimiento;
5. usar entre 24 y 72 horas de observacion continua antes de fijar una linea base.

AEYE no puede afirmar quien llego tarde, quien fue al bano ni si una ausencia
esta justificada. Tampoco vincula por ahora un faltante de un puesto con una
entrada al bano o al comedor. Esas inferencias quedaron explicitamente fuera de
este MVP.

