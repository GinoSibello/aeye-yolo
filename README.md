# AEYE YOLO

Sistema multi-camara para detectar personas en streams RTSP, medir ocupacion por
zona y alertar cuando la dotacion permanece fuera de un rango configurado.
Esta pensado para ejecutarse en NVIDIA Jetson mediante Docker, con inferencia
PyTorch o TensorRT.

> Estado: prototipo operativo. Los IDs `P001`, `P002`, etc. son trayectorias
> locales y temporales. No identifican empleados ni se conservan entre camaras
> o reinicios.

## Funcionalidades

- Lectura concurrente de multiples camaras RTSP.
- Deteccion de personas con YOLO, usando PyTorch o TensorRT.
- IDs temporales por camara mediante tracking por centroides.
- Conteo de personas y reglas de dotacion minima/maxima por zona.
- Alertas por consola o webhook despues de un tiempo configurable.
- Captura JPEG del frame que origina cada alerta.
- Dashboard web con estado y preview opcional.
- Persistencia SQLite de muestras de ocupacion e incidentes.
- API FastAPI para consultar metricas agregadas.
- Herramientas para exportar TensorRT y comparar latencia.

## Arquitectura

```text
Camaras RTSP
    |
    v
CameraReader (un hilo por camara, conserva el frame mas reciente)
    |
    v
YOLO / TensorRT (detecta cajas de clase persona)
    |
    +--> CentroidTracker (asigna IDs locales P001, P002...)
    |
    +--> StaffingRule (compara conteo con minimo/maximo)
              |
              +--> SQLite: ocupacion e incidentes
              +--> logs/alerts.jsonl e imagen de evidencia
              +--> webhook opcional

Dashboard HTTP :8080              API analitica opcional :8000
```

## Requisitos

- NVIDIA Jetson con una version de JetPack compatible con la imagen base.
- Docker configurado con NVIDIA Container Runtime.
- Acceso de red desde la Jetson a las camaras RTSP.
- Almacenamiento suficiente para base de datos, logs e imagenes de alerta.
- Archivo de pesos YOLO (`.pt`) o engine TensorRT generado en el mismo equipo.

La ruta RTSP actual sigue el formato de camaras Hikvision:
`/Streaming/Channels/<canal>`. Para otra marca se debe adaptar
`CameraReader.build_url` en `main.py`.

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

Colocar `yolov8n.pt` en la raiz del proyecto. Tambien puede descargarse mediante
Ultralytics desde la imagen ya construida:

```bash
sudo docker run --rm -it \
  --runtime=nvidia \
  -v "$PWD:/workspace/aeye-yolo" \
  -w /workspace/aeye-yolo \
  aeye-yolo:dev \
  python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

Los modelos y engines estan excluidos del repositorio debido a su tamano y a
que un engine TensorRT no es portable entre distintas plataformas.

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

La configuracion se divide en cuatro secciones:

| Seccion | Responsabilidad |
| --- | --- |
| `system` | Modelo, backend, resolucion, confianza y frecuencias |
| `preview` | Dashboard, puerto y calidad JPEG |
| `alerts` | Salida por consola o webhook |
| `database` | Activacion y ruta de SQLite |
| `cameras` | Conexion y regla de cada camara |

Campos principales de cada camara:

| Campo | Descripcion |
| --- | --- |
| `enabled` | Incluye la camara en el proceso |
| `ip`, `port`, `channel` | Conexion RTSP |
| `username` | Usuario RTSP; la contrasena se obtiene del secreto |
| `zone` | Nombre operativo usado en metricas |
| `monitor_staffing` | Guarda metricas y evalua dotacion |
| `min_people`, `max_people` | Rango esperado en la zona |

Variables de entorno admitidas:

| Variable | Valor predeterminado |
| --- | --- |
| `AEYE_CONFIG` | `/workspace/aeye-yolo/cameras.json` |
| `AEYE_LOG_DIR` | `/workspace/aeye-yolo/logs` |
| `AEYE_DB_PATH` | Valor de `database.path` |
| `CAMERA_PASSWORD_FILE` | `/run/secrets/camera_password` |
| `CAMERA_PASSWORD` | Alternativa de desarrollo si no existe el archivo |

## Ejecucion

```bash
./run.sh
```

El dashboard queda disponible en:

```text
http://IP_DE_LA_JETSON:8080
```

Rutas integradas:

| Ruta | Funcion |
| --- | --- |
| `/` | Dashboard y estado de todas las camaras |
| `/state.json` | Estado actual en JSON |
| `/preview/on` | Activa la generacion de previews |
| `/preview/off` | Desactiva previews y libera las imagenes en memoria |
| `/camera/<id>.jpg` | Ultimo preview JPEG disponible |

El preview esta desactivado inicialmente para evitar trabajo de codificacion
JPEG cuando no se necesita. Los conteos siguen funcionando con el preview
apagado.

## Reglas, incidentes y alertas

Para una zona configurada con `min_people: 1` y `max_people: 2`:

- Un conteo de `0` abre un incidente `missing`.
- Un conteo de `3` o mas abre un incidente `extra`.
- Volver al rango cierra el incidente y calcula su duracion.
- Permanecer fuera del rango durante `alert_after_seconds` genera una alerta.

Las alertas se escriben en `logs/alerts.jsonl`. El frame asociado se guarda en
`logs/alert_images/` y su ruta queda incluida en el evento. Con
`alerts.mode: "webhook"`, el mismo evento se envia como JSON mediante HTTP POST.

## Datos y API analitica

SQLite se inicializa automaticamente mediante
`database/migrations/001_initial.sql`. Guarda camaras, muestras de ocupacion,
incidentes y estructuras preparadas para identidad no biometrica y sesiones por
zona.

La API no se inicia con `run.sh`. Puede ejecutarse como un segundo proceso:

```bash
sudo docker run --rm -it \
  --network host \
  -v "$PWD:/workspace/aeye-yolo" \
  -w /workspace/aeye-yolo \
  aeye-yolo:dev \
  uvicorn api.app:app --host 0.0.0.0 --port 8000
```

Documentacion interactiva:

```text
http://IP_DE_LA_JETSON:8000/docs
```

Consultas disponibles:

- Porcentaje de faltantes y ocupacion promedio por hora.
- Minutos debajo del minimo.
- Ocupacion minima, maxima y promedio por hora.
- Cantidad de incidentes largos.
- Tasa de falsos positivos revisados.
- Tiempo individual por zona y transiciones, solo cuando una integracion externa
  haya generado sesiones e identidades verificables.

Ver [ANALYTICS.md](ANALYTICS.md) para ejemplos de consultas.

## PyTorch y TensorRT

El backend se selecciona en `cameras.json`:

```json
"inference_backend": "pytorch"
```

o:

```json
"inference_backend": "tensorrt"
```

Para exportar un engine FP16 en la Jetson:

```bash
sudo docker run --rm -it \
  --runtime=nvidia \
  --network host \
  --ipc=host \
  -v "$PWD:/workspace/aeye-yolo" \
  -w /workspace/aeye-yolo \
  aeye-yolo:dev \
  python3 tools/export_tensorrt.py
```

Un `.engine` debe regenerarse si cambian la GPU, TensorRT, CUDA, JetPack, la
imagen Docker o `imgsz`. Ver [TENSORRT.md](TENSORRT.md) para el procedimiento y
el benchmark comparativo.

## Pruebas

Las pruebas unitarias no requieren camaras conectadas:

```bash
python3 -m unittest discover -v
```

Para comparar backends sobre imagenes:

```bash
python3 tools/benchmark_detector.py imagen.jpg --backend pytorch
python3 tools/benchmark_detector.py imagen.jpg --backend tensorrt
```

El dataset auxiliar puede prepararse con:

```bash
python3 tools/download_people_images.py --count 20
```

Las imagenes descargadas no se incluyen en Git. El benchmark mide latencia y
conteos, pero no precision si las imagenes no fueron anotadas manualmente.

## Estructura del proyecto

```text
api/                 API FastAPI de metricas
database/            Repositorio SQLite, modelos y migraciones
identity/            Enlace temporal con identidades externas verificables
metrics/             Registro de ocupacion y consultas analiticas
tools/               Exportacion, benchmark y utilidades de Jetson
vision/              Backends de deteccion YOLO/TensorRT
main.py              Orquestacion RTSP, tracking, reglas y dashboard
cameras.example.json Plantilla publica de configuracion
Dockerfile           Entorno NVIDIA reproducible
run.sh               Arranque local con secreto montado
```

## Limites y uso responsable

- El tracker actual usa centroides; puede cambiar IDs durante cruces u oclusiones.
- Los IDs son anonimos, locales por camara y se reinician con el proceso.
- El conteo no distingue empleados, clientes o proveedores.
- La aplicacion todavia no filtra regiones de interes dentro de una imagen.
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
- Pesos `.pt`, modelos `.onnx` y engines `.engine`.
- Datasets descargados, caches de Python y copias `.orig`.
- Archivos `.env` y nombres que contengan `password`.

Antes de cada publicacion conviene ejecutar `git status` y revisar todos los
archivos que se van a incluir.
