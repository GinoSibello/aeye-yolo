# AEYE YOLO

Sistema multi-camara para detectar personas en streams RTSP, medir ocupacion por
zona y alertar cuando la dotacion permanece fuera de un rango configurado.
Esta pensado para ejecutarse en NVIDIA Jetson mediante Docker, con inferencia
TensorRT.

> Estado: prototipo operativo. Los IDs `P001`, `P002`, etc. son trayectorias
> locales y temporales. No identifican empleados ni se conservan entre camaras
> o reinicios.

## Trabajo con agentes de IA

La [guia de agentes y skills](AGENT_WORKFLOW.md) explica como usar Codex y
OpenCode con instrucciones por area, especialistas y revision independiente.
El mapa para agentes esta en [AGENTS.md](AGENTS.md); no cambia el runtime.

## Funcionalidades

- Lectura concurrente de multiples camaras RTSP.
- Deteccion de personas con un engine YOLO optimizado para TensorRT.
- Batching configurable entre camaras con timeout y validacion del engine.
- IDs temporales por camara mediante ByteTrack.
- Conteo de personas y reglas de dotacion minima/maxima por zona.
- Conteo suavizado, histeresis y estado explicito `no_data`.
- Alertas por consola o webhook despues de un tiempo configurable.
- Captura JPEG del frame que origina cada alerta.
- Dashboard diario de puestos, horarios, pausas y areas comunes.
- ROI por camara y lineas de acceso opcionales para visitas anonimas.
- Persistencia SQLite de ocupacion, tracks locales, cruces e incidentes.
- API FastAPI para consultar metricas agregadas.
- Reportes diarios, semanales y mensuales con detalle por camara.
- Descarga CSV diaria y exportacion semanal o mensual a PNG/PDF.
- Herramienta para medir la latencia del engine TensorRT.
- Baseline reproducible con latencias por etapa y telemetria de la Jetson.

## Arquitectura

```text
Camaras RTSP
    |
    v
CameraReader (FFmpeg o GStreamer/NVDEC, conserva el frame mas reciente)
    |
    v
BatchScheduler (batch 1 o lote dinamico con timeout corto)
    |
    v
YOLO / TensorRT (detecta cajas de clase persona)
    |
    +--> ByteTrack (asigna IDs locales P001, P002...)
    |
    +--> StaffingStateMachine (suaviza, confirma y compara con minimo/maximo)
              |
              +--> SQLite: ocupacion e incidentes
              +--> logs/alerts.jsonl e imagen de evidencia
              +--> webhook opcional

Visor privado :8080              Dashboard y API LAN :8000
```

## Requisitos

- NVIDIA Jetson con una version de JetPack compatible con la imagen base.
- Docker configurado con NVIDIA Container Runtime.
- Acceso de red desde la Jetson a las camaras RTSP.
- Almacenamiento suficiente para base de datos, logs e imagenes de alerta.
- Engine TensorRT (`.engine`) generado para la misma Jetson y entorno de software.

La ruta RTSP actual sigue el formato de camaras Hikvision:
`/Streaming/Channels/<canal>`. Para otra marca se debe adaptar
`CameraReader.build_url` en `main.py`.

La captura usa OpenCV/FFmpeg cuando `system.capture` no esta configurado.
Existe un backend experimental `gstreamer_nvdec` para H.264/H.265 y un
fallback configurable a FFmpeg. La prueba de etapa 2 confirmo NVDEC real, pero
no redujo CPU total con la conversion BGR actual; por eso FFmpeg sigue siendo
el valor recomendado. La configuracion completa esta en
`cameras.example.json` y los resultados en
[STAGE2_NVDEC.md](STAGE2_NVDEC.md).

## Instalacion

```bash
git clone <URL_DEL_REPOSITORIO>
cd aeye-yolo
cp cameras.example.json cameras.json
```

Editar `cameras.json` con las IPs, zonas, canales y reglas reales. Este archivo
esta ignorado por Git para no publicar informacion de la red local.

Construir la imagen:

```bash
sudo docker build -t aeye-yolo:dev .
```

Colocar `yolov8n.engine` en la raiz del proyecto. El engine debe haberse generado
en la misma Jetson y con versiones compatibles de TensorRT, CUDA, JetPack e
`imgsz`. Los engines estan excluidos del repositorio por su tamano y porque no
son portables entre plataformas.

## Credencial de las camaras

La contrasena no debe guardarse en `cameras.json`, el Dockerfile ni Git. El
proyecto espera un secreto protegido en `/etc/aeye/camera_password` y lo monta
como archivo de solo lectura dentro del contenedor.

Crearlo una sola vez:

```bash
sudo install -d -m 700 /etc/aeye
sudo install -m 600 -o root -g root /dev/null /etc/aeye/camera_password
read -rsp "Contrasena de las camaras: " CAMERA_PASSWORD; echo
printf '%s' "$CAMERA_PASSWORD" | sudo tee /etc/aeye/camera_password >/dev/null
unset CAMERA_PASSWORD
```

Para usar otro archivo, definir `AEYE_CAMERA_PASSWORD_FILE` antes de ejecutar
`run.sh`. Como compatibilidad de desarrollo, `main.py` tambien admite la
variable `CAMERA_PASSWORD`, pero el arranque normal utiliza el archivo secreto.

## Configuracion

La configuracion se divide en seis secciones:

| Seccion | Responsabilidad |
| --- | --- |
| `system` | Engine TensorRT, resolucion, frecuencia, batching y pipeline |
| `preview` | Visor local, puerto y calidad JPEG |
| `alerts` | Salida por consola o webhook |
| `database` | Activacion y ruta de SQLite |
| `reporting` | Zona horaria, turnos, comida y tolerancias |
| `cameras` | Conexion y regla de cada camara |

Campos principales de cada camara:

| Campo | Descripcion |
| --- | --- |
| `enabled` | Incluye la camara en el proceso |
| `ip`, `port`, `channel` | Conexion RTSP |
| `username` | Usuario RTSP; la contrasena se obtiene del secreto |
| `zone` | Nombre operativo usado en metricas |
| `role` | `workstation`, `restroom`, `dining` u `other` |
| `reporting_enabled` | Guarda muestras para reportes |
| `expected_people` | Dotacion simultanea esperada en cada turno |
| `roi` | Poligono normalizado que delimita la zona |
| `access_line` | Linea opcional de entrada/salida |
| `monitor_staffing` | Evalua dotacion dentro del horario y genera incidentes |
| `min_people`, `max_people` | Rango esperado en la zona |

Variables de entorno admitidas:

| Variable | Valor predeterminado |
| --- | --- |
| `AEYE_CONFIG` | `/workspace/aeye-yolo/cameras.json` |
| `AEYE_LOG_DIR` | `/workspace/aeye-yolo/logs` |
| `AEYE_PERFORMANCE_PATH` | `<AEYE_LOG_DIR>/performance_summary.json` |
| `AEYE_DB_PATH` | Valor de `database.path` |
| `AEYE_API_HOST` | `0.0.0.0` |
| `AEYE_API_PORT` | `8000` |
| `CAMERA_PASSWORD_FILE` | `/run/secrets/camera_password` |
| `CAMERA_PASSWORD` | Alternativa de desarrollo si no existe el archivo |

Controles de estabilidad en `system`:

| Campo | Funcion |
| --- | --- |
| `confidence` | Umbral minimo entregado a ByteTrack; permite detecciones de baja confianza |
| `smoothing_window_seconds` | Ventana usada para obtener la mediana del conteo |
| `incident_confirmation_seconds` | Tiempo anormal continuo antes de abrir un incidente |
| `recovery_confirmation_seconds` | Tiempo normal continuo antes de cerrar un incidente |
| `alert_after_seconds` | Tiempo desde la confirmacion hasta enviar la alerta |
| `tracker` | Umbrales, asociacion y tolerancia a oclusiones de ByteTrack |
| `pipeline.copy_latest_frame` | Copia el snapshot o comparte el ultimo frame de solo lectura |
| `pipeline.result_transfer` | Usa transferencias `split` o una matriz `packed` |

La configuracion de ejemplo acepta detecciones desde `0.1` para que ByteTrack
pueda recuperar trayectorias debiles, pero exige `0.4` para crear una nueva.
Estos valores deben calibrarse con imagenes reales de cada instalacion.

## Ejecucion

```bash
./run.sh
```

El script crea el contenedor persistente `aeye-runtime` en segundo plano con
la politica `unless-stopped`. Docker lo inicia de nuevo automaticamente cuando
arranca la Jetson. Ejecutar `./run.sh` otra vez reutiliza el mismo contenedor.

Para consultar su estado y sus logs:

```bash
docker ps --filter name=aeye-runtime
docker logs --tail 50 -f aeye-runtime
```

El dashboard historico y la API se inician junto con el motor. La Jetson
publica el nombre mDNS `aeye.local` y las unidades versionadas de
`tools/systemd/` permiten usar una direccion sin IP ni puerto:

```text
http://aeye.local/
```

Para instalar el proxy local una sola vez:

```bash
sudo install -m 0644 tools/systemd/aeye-http.socket /etc/systemd/system/
sudo install -m 0644 tools/systemd/aeye-http.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aeye-http.socket
```

El acceso directo `http://IP_DE_LA_JETSON:8000` se conserva como
respaldo. Si el Wi-Fi empresarial bloquea mDNS, el area de IT debe crear un
registro DNS interno hacia la IP reservada de la Jetson. Cualquier equipo de la
red local puede abrir el dashboard. Por ahora no tiene usuario ni contrasena,
por lo que los puertos 80 y 8000 no deben exponerse a Internet.

El visor en vivo permanece en `http://127.0.0.1:8080` y solo se abre desde la
Jetson. El preview esta desactivado inicialmente para evitar trabajo de
codificacion JPEG cuando no se necesita. Los conteos y reportes siguen
funcionando con el preview apagado.

Cada tarjeta del visor permite ampliar una camara y ocultar temporalmente las
demas. El boton `Todas las camaras` o la tecla `Escape` restaura la vista de
cuadricula.

La configuracion inicial de puestos y horarios se explica en
[ACTIVITY_REPORTING.md](ACTIVITY_REPORTING.md).

## Reglas, incidentes y alertas

Para una zona configurada con `min_people: 1` y `max_people: 2`:

- Un conteo suavizado de `0` sostenido durante el tiempo de confirmacion abre
  un incidente `missing`.
- Un conteo suavizado de `3` o mas sostenido abre un incidente `extra`.
- Volver al rango durante el tiempo de recuperacion cierra el incidente.
- Permanecer fuera del rango durante `alert_after_seconds` genera una alerta.

Cada muestra conserva el conteo crudo y el suavizado. Si no hay frame valido o
falla la inferencia, se guarda `data_status: no_data`, con conteos nulos y estado
`unknown`. Ese intervalo no se interpreta como cero personas ni se suma a los
minutos de faltantes.

Cuando AEYE arranca, cierra los incidentes que quedaron abiertos en una ejecucion
anterior usando la ultima muestra valida y el motivo `process_restart`. El tiempo
apagado queda fuera del incidente. Si el problema continua, se confirma y abre
un incidente nuevo.

Las alertas se escriben en `logs/alerts.jsonl`. El frame asociado se guarda en
`logs/alert_images/` y su ruta queda incluida en el evento. Con
`alerts.mode: "webhook"`, el mismo evento se envia como JSON mediante HTTP POST.

## Datos y API analitica

SQLite se inicializa automaticamente con las migraciones de
`database/migrations/`. Guarda camaras, muestras de ocupacion, incidentes,
configuracion efectiva, tracks locales, cruces y visitas anonimas.

`run.sh` inicia la vision y la API en el mismo contenedor. La documentacion
interactiva queda en:

```text
http://aeye.local/docs
```

Rutas de reporte:

- `GET /api/reports/daily?day=AAAA-MM-DD`
- `GET /api/reports/weekly?week=AAAA-MM-DD`
- `GET /api/reports/monthly?month=AAAA-MM-DD`
- `GET /api/reports/daily.csv?day=AAAA-MM-DD`
- `GET /api/reporting/configuration`

Consultas disponibles:

- Porcentaje de faltantes y ocupacion promedio por hora.
- Minutos debajo del minimo.
- Ocupacion minima, maxima y promedio por hora.
- Cantidad de incidentes largos.
- Tasa de falsos positivos revisados.
- Tiempo individual por zona y transiciones, solo cuando una integracion externa
  haya generado sesiones e identidades verificables.

Ver [ANALYTICS.md](ANALYTICS.md) para ejemplos de consultas.

## Inferencia TensorRT

TensorRT es el unico backend de produccion. `cameras.json` indica el archivo:

```json
"tensorrt_engine": "yolov8n.engine"
```

AEYE tuvo anteriormente un backend PyTorch que se utilizo como referencia para
comparar rendimiento. Las pruebas en la Jetson mostraron una mejora suficiente
con TensorRT y ese camino fue retirado para reducir configuracion y mantenimiento.
El runtime no carga archivos `.pt` ni permite seleccionar otro backend. La
herramienta `tools/export_batch_engine.sh` exporta en un contenedor temporal,
separado del arranque de produccion, y copia el engine validado al proyecto.

Un `.engine` debe regenerarse si cambian la GPU, TensorRT, CUDA, JetPack, la
imagen Docker o `imgsz`. Ver [TENSORRT.md](TENSORRT.md).

## Diagnostico de rendimiento

La metodologia, configuracion observada y limites de las metricas se documentan
en [STAGE0_BASELINE.md](STAGE0_BASELINE.md). Para capturar el baseline
predeterminado de 120 segundos con preview desactivado:

```bash
tools/run_stage0_baseline.sh
```

La comparacion controlada de 2, 4, 6 y 8 FPS por camara se documenta en
[STAGE1_FPS.md](STAGE1_FPS.md). La serie completa utiliza configuraciones
temporales y no modifica `cameras.json`:

```bash
tools/run_stage1_fps.sh 120
```

El prototipo GStreamer/NVDEC y su comparacion controlada con FFmpeg se
documentan en [STAGE2_NVDEC.md](STAGE2_NVDEC.md):

```bash
tools/run_stage2_nvdec.sh 120
```

El batching entre camaras, el engine dinamico batch 8 y la comparacion contra
la ruta secuencial se documentan en [STAGE3_BATCHING.md](STAGE3_BATCHING.md):

```bash
tools/run_stage3_batching.sh 120
```

El perfil de copias CPU y transferencias GPU, junto con la comparacion A/B de
las rutas optimizadas, se documenta en [STAGE4_PIPELINE.md](STAGE4_PIPELINE.md):

```bash
tools/run_stage4_pipeline.sh 120
```

La comparacion FP16 de YOLO11/YOLO26, nano/small y 640/960x544, incluyendo
precision sobre COCO anotado y validacion con ocho camaras, se documenta en
[STAGE5_MODELS.md](STAGE5_MODELS.md):

```bash
tools/prepare_coco_val.sh
tools/run_stage5_accuracy.sh
tools/run_stage5_operational.sh 120
```

## Pruebas

Las pruebas unitarias no requieren camaras conectadas:

```bash
python3 -m unittest discover -v
```

Para medir TensorRT sobre una imagen:

```bash
python3 tools/benchmark_detector.py imagen.jpg
```

El dataset auxiliar puede prepararse con:

```bash
python3 tools/download_people_images.py --count 20
```

Las imagenes descargadas no se incluyen en Git. El benchmark mide latencia y
conteos, pero no precision si las imagenes no fueron anotadas manualmente.

## Estructura del proyecto

```text
api/                 Dashboard y API FastAPI de reportes
database/            Repositorio SQLite, modelos y migraciones
identity/            Enlace temporal con identidades externas verificables
metrics/             Registro, reglas y reportes de actividad
tools/               Benchmark y utilidades de Jetson
vision/              Captura, pipeline, batching, tracking y TensorRT
main.py              Orquestacion RTSP, tracking, reglas y visor local
ACTIVITY_REPORTING.md Configuracion y limites del reporte diario
cameras.example.json Plantilla publica de configuracion
Dockerfile           Entorno NVIDIA reproducible
run.sh               Arranque local con secreto montado
```

## Limites y uso responsable

- ByteTrack mejora cruces y oclusiones, pero aun puede cambiar IDs en escenas
  complejas y necesita calibracion por instalacion.
- Los IDs son anonimos, locales por camara y se reinician con el proceso.
- El conteo no distingue empleados, clientes o proveedores.
- Cada ROI debe calibrarse; una ROI completa puede contar pasillos o puestos
  vecinos.
- Una deteccion visual no demuestra productividad, intencion ni cumplimiento
  individual.
- Las metricas deben validarse contra conteos humanos representativos antes de
  tomar decisiones operativas.
- No deben automatizarse medidas laborales o disciplinarias a partir de estas
  detecciones.
- Una instalacion real necesita politicas de acceso, retencion de imagenes,
  revision humana y cumplimiento de la normativa aplicable.

Para identidad individual se recomienda integrar badge, QR o RFID y mantener
la asociacion solo durante una sesion corta. El proyecto no implementa
reconocimiento facial.

## Archivos que no se publican

`.gitignore` excluye deliberadamente:

- `cameras.json` con IPs y configuracion local.
- Bases SQLite y sus archivos WAL/SHM.
- Logs e imagenes de evidencia.
- Modelos y artefactos de inferencia (`.pt`, `.onnx`, `.engine`, `.plan`).
- Datasets descargados, caches de Python y copias `.orig`.
- Archivos `.env` y nombres que contengan `password`.

Antes de cada publicacion conviene ejecutar `git status` y revisar todos los
archivos que se van a incluir.

Ver [ROADMAP.md](ROADMAP.md) para el estado de mejoras completadas y pendientes.
