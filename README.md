# AEYE

AEYE es un sistema multicámara para NVIDIA Jetson que detecta personas en
streams RTSP, mide ocupación anónima por zona y genera reportes operativos por
puesto. Usa YOLO con TensorRT, tracking local con ByteTrack, persistencia
SQLite, una API FastAPI y dos interfaces web: el dashboard histórico y un
preview privado de cámaras.

> **Estado:** prototipo operativo pendiente de calibración y validación
> prolongada en cada instalación. Los identificadores P001, P002, etc. son
> trayectorias temporales dentro de una cámara y una sesión; no identifican
> empleados ni permiten seguir a una persona entre cámaras.

## Funcionalidad

- Lectura concurrente de varias cámaras RTSP mediante FFmpeg o un backend
  experimental GStreamer/NVDEC.
- Detección de personas con un engine YOLO TensorRT FP16.
- Inferencia secuencial o batching configurable entre cámaras.
- Tracking ByteTrack independiente por cámara.
- Regiones de interés (ROI) normalizadas para medir ocupación por zona.
- Conteo crudo y suavizado, histéresis y estado explícito no_data.
- Reglas de dotación mínima y máxima dentro de horarios configurados.
- Incidentes y alertas por consola o webhook, con captura JPEG opcional.
- Persistencia SQLite de muestras, incidentes, tracks locales, cruces y visitas
  anónimas.
- Reportes diarios, semanales y mensuales, con cobertura y detalle por cámara.
- Descarga diaria CSV y exportación semanal o mensual a PNG/PDF.
- Dashboard en la red local y preview en vivo limitado a la Jetson.
- Herramientas reproducibles para medir FPS, latencia, consumo y precisión.

AEYE informa ocupación y cupos anónimos. No implementa reconocimiento facial,
no determina productividad o intención, no atribuye una ausencia a una causa y
no relaciona faltantes de un puesto con entradas a baño o comedor.

## Arquitectura

~~~text
Cámaras RTSP
    |
    v
CameraReader (FFmpeg o GStreamer/NVDEC; conserva el frame más reciente)
    |
    v
BatchScheduler (secuencial o lote dinámico con timeout)
    |
    v
YOLO / TensorRT (cajas de clase persona)
    |
    +--> ByteTrack (IDs locales P001, P002...)
    |
    +--> ROI y StaffingStateMachine
              |
              +--> SQLite: ocupación, tracks, cruces e incidentes
              +--> logs/alerts.jsonl e imágenes de alerta
              +--> webhook opcional

Preview privado :8080             Dashboard y API LAN :8000
~~~

| Ruta | Responsabilidad |
| --- | --- |
| main.py | Coordina captura, inferencia, tracking, reglas y preview |
| vision/ | Captura, TensorRT, batching, tracking y ROI |
| metrics/ | Muestreo, incidentes y reportes por período |
| database/ | Repositorio SQLite y migraciones numeradas |
| api/app.py | API FastAPI y publicación del dashboard |
| api/static/ | Dashboard de actividad en JavaScript nativo |
| preview/ | Vista en vivo de cámaras |
| tools/ | Operación Jetson, auditoría y benchmarks |
| tests/ | Pruebas unittest con fixtures y bases temporales |

## Requisitos e instalación

- NVIDIA Jetson con JetPack compatible con la imagen base.
- Docker con NVIDIA Container Runtime.
- Acceso de red desde la Jetson a las cámaras RTSP.
- Espacio para SQLite, logs e imágenes de alerta.
- Un engine TensorRT generado en la misma Jetson y con versiones compatibles de
  TensorRT, CUDA, JetPack, modelo y resolución.

La plantilla usa la ruta Hikvision /Streaming/Channels/canal. Para otra marca
se debe adaptar CameraReader.build_url en main.py.

~~~bash
git clone <URL_DEL_REPOSITORIO>
cd aeye-yolo
cp cameras.example.json cameras.json
sudo docker build -t aeye-yolo:dev .
~~~

Editar cameras.json con las cámaras, zonas y reglas reales. El archivo está
ignorado por Git porque puede contener información de la red local. Colocar el
.engine configurado en la ruta correspondiente. Los engines no se versionan:
no son portables entre GPUs o entornos de JetPack/TensorRT.

### Credencial RTSP

La contraseña no debe guardarse en cameras.json, el Dockerfile ni Git. El
arranque normal usa /etc/aeye/camera_password, montado dentro del contenedor
como archivo de solo lectura:

~~~bash
sudo install -d -m 700 /etc/aeye
sudo install -m 600 -o root -g root /dev/null /etc/aeye/camera_password
read -rsp "Contraseña de las cámaras: " CAMERA_PASSWORD; echo
printf '%s' "$CAMERA_PASSWORD" | sudo tee /etc/aeye/camera_password >/dev/null
unset CAMERA_PASSWORD
~~~

Para otra ubicación, definir AEYE_CAMERA_PASSWORD_FILE antes de ejecutar
run.sh. CAMERA_PASSWORD existe solo como alternativa de desarrollo.

## Configuración

La referencia editable es cameras.example.json. Sus valores son ejemplos y no
prueban cuál es la configuración efectiva de una instalación.

| Sección | Responsabilidad |
| --- | --- |
| system | Engine, resolución, FPS, captura, batching y pipeline |
| preview | Visor local, puerto y calidad JPEG |
| alerts | Consola o webhook |
| database | Activación y ruta SQLite |
| reporting | Zona horaria, días, turnos, comidas y tolerancias |
| cameras | Conexión, rol, ROI y reglas por cámara |

Campos principales de una cámara:

| Campo | Descripción |
| --- | --- |
| id | Identificador estable usado en datos y configuración |
| name, zone | Nombre de presentación y zona operativa |
| enabled | Incluye la cámara en el proceso |
| ip, port, channel, username | Conexión RTSP sin contraseña |
| role | workstation, restroom, dining u other |
| reporting_enabled | Guarda muestras para reportes |
| expected_people | Cantidad simultánea esperada por turno |
| monitor_staffing | Genera incidentes de dotación durante los turnos |
| min_people, max_people | Rango esperado en la zona |
| roi | Polígono normalizado de la zona medida |
| access_line | Línea opcional para entradas y salidas anónimas |

Ejemplo de puesto:

~~~json
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
~~~

La ROI usa coordenadas entre 0 y 1. Un track cuenta cuando el centro inferior
de su caja cae dentro del polígono. Una ROI que cubre toda la imagen debe
calibrarse para excluir pasillos y puestos vecinos.

### Turnos y pausas

Los días usan lunes 0 a domingo 6; las horas locales usan HH:MM. Si el final es
anterior al inicio, el turno cruza medianoche.

~~~json
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
    }
  ]
}
~~~

Cada puesto se evalúa por turno. Fuera de días y horarios laborales,
monitor_staffing no abre incidentes de faltantes. Las áreas comunes no deben
tener dotación esperada ni reglas laborales de llegada.

### Línea de acceso

~~~json
"access_line": {
  "enabled": true,
  "start": [0.20, 0.52],
  "end": [0.82, 0.52],
  "inside_side": "left",
  "hysteresis": 0.015
}
~~~

Si entradas y salidas aparecen invertidas, cambiar inside_side entre left y
right. Las visitas se emparejan FIFO: la primera salida cierra la entrada
abierta más antigua. Es una estimación anónima que pierde fiabilidad con cruces
simultáneos, oclusiones, varias puertas o reinicios. Una visita abierta al
reiniciar se marca abortada y no recibe una duración inventada.

### Estabilidad del conteo

| Campo | Función |
| --- | --- |
| confidence | Umbral mínimo entregado al tracker |
| smoothing_window_seconds | Ventana de mediana para el conteo |
| incident_confirmation_seconds | Anormalidad continua antes de abrir incidente |
| recovery_confirmation_seconds | Normalidad continua antes de cerrarlo |
| alert_after_seconds | Espera desde la confirmación hasta alertar |
| tracker | Asociación, umbrales y tolerancia a oclusiones |
| metrics_sample_every_seconds | Frecuencia de persistencia de muestras |
| pipeline.copy_latest_frame | Copia o comparte el último frame inmutable |
| pipeline.result_transfer | Transfiere resultados split o packed |

Los umbrales deben calibrarse con escenas reales. Un valor bajo puede ayudar a
ByteTrack a recuperar trayectorias débiles, pero no debe aprobarse solo porque
mejore recall en un dataset general.

### Variables de entorno

| Variable | Valor predeterminado |
| --- | --- |
| AEYE_CONFIG | /workspace/aeye-yolo/cameras.json |
| AEYE_LOG_DIR | /workspace/aeye-yolo/logs |
| AEYE_PERFORMANCE_PATH | &lt;AEYE_LOG_DIR&gt;/performance_summary.json |
| AEYE_DB_PATH | Valor de database.path |
| AEYE_API_HOST | 0.0.0.0 |
| AEYE_API_PORT | 8000 |
| CAMERA_PASSWORD_FILE | /run/secrets/camera_password |
| CAMERA_PASSWORD | Alternativa de desarrollo |

## Ejecución y acceso

~~~bash
./run.sh
~~~

run.sh crea el contenedor persistente aeye-runtime con política unless-stopped.
Una invocación posterior inicia o reutiliza el contenedor; no garantiza que una
imagen nueva reemplace automáticamente uno existente.

~~~bash
docker ps --filter name=aeye-runtime
docker logs --tail 50 -f aeye-runtime
~~~

| Servicio | Dirección |
| --- | --- |
| Dashboard | http://IP_DE_LA_JETSON:8000/ |
| OpenAPI | http://IP_DE_LA_JETSON:8000/docs |
| Preview | http://127.0.0.1:8080 desde la Jetson |

El preview está desactivado inicialmente para evitar el costo de JPEG. Los
conteos y reportes continúan funcionando sin él. En su cuadrícula, una tarjeta
puede ampliarse y Escape restaura todas las cámaras.

Las unidades de tools/systemd/ pueden publicar el dashboard como
http://aeye.local/ mediante mDNS y un proxy local en el puerto 80:

~~~bash
sudo install -m 0644 tools/systemd/aeye-http.socket /etc/systemd/system/
sudo install -m 0644 tools/systemd/aeye-http.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aeye-http.socket
~~~

El dashboard y la API no tienen autenticación por decisión del despliegue LAN.
No se deben exponer los puertos 80 u 8000 a Internet. Si la red bloquea mDNS,
se necesita un registro DNS interno o usar directamente la IP reservada.

### RustDesk sin monitor

Antes de modificar el entorno gráfico, comprobar SSH desde otro equipo y
mantener esa sesión abierta. En Jetson no se debe reemplazar a ciegas el
xorg.conf de NVIDIA.

~~~bash
sudo bash tools/setup_rustdesk_headless.sh
sudo reboot
bash tools/check_rustdesk_headless.sh
~~~

Si Xorg existe pero RustDesk indica no display, se puede preparar un display
virtual de 1920x1080:

~~~bash
sudo bash tools/setup_jetson_dummy_display.sh
sudo reboot
~~~

Para volver a la salida física NVIDIA o desactivar solo el modo headless:

~~~bash
sudo bash tools/restore_jetson_nvidia_display.sh
sudo reboot

sudo bash tools/disable_rustdesk_headless.sh
~~~

Estos comandos cambian el host y requieren una ventana de mantenimiento. Los
scripts de preparación no reinician GDM automáticamente.

## Métricas, reportes y alertas

Cada muestra conserva raw_people_count, el conteo suavizado people_count y
data_status. Una desconexión o inferencia fallida produce no_data, conteos nulos
y estado unknown; nunca equivale a cero personas ni suma minutos de faltantes.

- **Ocupación media:** integral del conteo suavizado durante intervalos válidos.
- **Cobertura:** tiempo con muestras válidas dividido por el período aplicable.
- **Dotación completa:** tiempo válido con conteo igual o superior al esperado.
- **Horas-persona faltantes:** integral de la diferencia entre dotación y conteo.
- **Llegada tardía estimada:** primer momento en que aparece cada cupo anónimo,
  después de la tolerancia y con evidencia suficiente.
- **Salida anticipada estimada:** última presencia de cada cupo antes del final.
- **Después de hora:** cupos aún observados pasada la tolerancia de salida.
- **Pausa de comida:** ausencia de un cupo iniciada dentro de su ventana.

Un cupo no es un empleado. Si se esperan dos personas, el sistema razona sobre
dos plazas simultáneas sin saber quién las ocupa. Si en un cambio de turno el
conteo no varía, AEYE no puede demostrar que hubo relevo.

### Cómo leer AEYE Actividad

#### De la cámara al porcentaje

Cada inferencia produce `raw_people_count`, que es el conteo detectado dentro de
la ROI, y `people_count`, que es el conteo suavizado utilizado por los reportes.
El suavizado reduce fluctuaciones breves; no convierte un track en una identidad.

Las muestras se transforman en intervalos y una muestra solo se prolonga hasta
`max_sample_gap_seconds`. Un intervalo es válido cuando `data_status` es `valid`
y tiene conteo. Un conteo válido de cero significa “se observaron cero personas”;
`no_data` significa “no hubo evidencia utilizable” por desconexión, fallo de
inferencia o falta de continuidad. El tiempo `no_data` reduce cobertura y no se
contabiliza como ausencia de personal.

La cobertura responde cuánto tiempo está respaldado por datos, no si el conteo
fue correcto. Una cobertura alta puede convivir con falsos positivos, falsos
negativos, oclusiones o una ROI mal calibrada. La exactitud se evalúa aparte,
comparando muestras con conteos manuales mediante la auditoría visual.

| Indicador | Unidad y cálculo | Período aplicable | Qué no demuestra |
| --- | --- | --- | --- |
| Ocupación media | Personas: suma de `conteo × tiempo válido` dividida por el tiempo válido | Turnos en puestos; tiempo calendario en áreas comunes | Personas únicas |
| Ocupación respecto de la dotación | Porcentaje: `horas-persona observadas / horas-persona esperadas × 100` | Tiempo válido de puestos con dotación configurada | Identidad o asistencia individual |
| Cupos simultáneos esperados | Personas simultáneas configuradas por puesto; el general suma los puestos | Cada turno activo usa el cupo del puesto | Suma de empleados únicos de todos los turnos |
| Cobertura de turnos | Porcentaje: `tiempo válido / tiempo de turno aplicable × 100` | Puestos; el día en curso termina en la hora real | Exactitud del detector |
| Cobertura calendario | Porcentaje: `tiempo válido / tiempo calendario transcurrido × 100` | Baño y comedor | Comparabilidad directa con cobertura de turnos |
| Dotación completa | Porcentaje: tiempo válido con `conteo >= esperado` dividido por todo el tiempo válido | Puesto o conjunto de puestos | Que siempre estuvieron las mismas personas |
| Horas-persona | Horas: suma de `conteo × tiempo válido` | Tiempo válido | Horas contractuales o personas únicas |
| Horas-persona faltantes | Horas: suma de `máximo(0, esperado - conteo) × tiempo válido` | Tiempo válido con dotación configurada | Causa del faltante |
| Distribución horaria | Promedio ponderado por tiempo válido dentro de cada una de las 24 horas del día | Días incluidos en el informe | Una evolución día por día |

Los porcentajes generales se ponderan por tiempo y cupo; no son un promedio
simple de los porcentajes visibles de cada cámara. La pestaña de una cámara usa
solo datos de esa cámara. El resumen general suma eventos y horas, o pondera
ocupación, pero no copia un resultado general en cada puesto.

#### Ejemplo ficticio y comprobable

Supóngase un puesto con 2 cupos y un período aplicable de 5 horas:

| Intervalo | Estado | Conteo |
| --- | --- | --- |
| 2 horas | válido | 2 |
| 1 hora | válido | 1 |
| 1 hora | válido | 0 |
| 1 hora | `no_data` | desconocido |

El tiempo válido es 4 horas, por lo que la cobertura es `4 / 5 = 80 %`. Las
horas-persona son `(2 × 2) + (1 × 1) + (0 × 1) = 5`. Durante las 4 horas válidas
se esperaban `2 × 4 = 8` horas-persona, así que la ocupación respecto de la
dotación es `5 / 8 = 62,5 %`. La dotación estuvo completa 2 de las 4 horas
válidas: `50 %`. Las horas-persona faltantes son
`(2 - 1) × 1 + (2 - 0) × 1 = 3`.

#### Llegadas, salidas y pausas

Estas métricas recorren niveles de ocupación anónimos. Con dotación 2, “cupo 1”
significa que el conteo llegó al menos a 1 y “cupo 2” que llegó al menos a 2.
No siguen un `track_id`, no identifican empleados y no vinculan un faltante con
una visita a baño o comedor.

- **Llegada tarde:** primera presencia de cada cupo dentro del turno. Cuenta
  como tardía si ocurre después de `arrival_grace_minutes`. La demora se mide
  desde el inicio del turno, no desde el final de la tolerancia, y el promedio
  incluye solamente los cupos clasificados como tardíos. Un cupo que nunca
  aparece se informa como ausente, no como tardanza.
- **Salida anticipada:** última presencia de cada cupo dentro del turno. Cuenta
  cuando termina antes de `shift_end - early_departure_tolerance_minutes`.
  Un cupo que estuvo ausente todo el turno no se inventa como salida.
- **Después de hora:** para el último turno del día se observa desde
  `shift_end + overtime_tolerance_minutes` hasta
  `shift_end + overtime_observation_minutes`. Si un cupo aparece en esa ventana,
  su duración se calcula desde el fin del turno hasta su última presencia. Por
  eso un valor como 114 minutos significa “última presencia estimada 114 minutos
  después del fin”, no “114 minutos por encima de la tolerancia”.
- **Pausa de comida:** ausencia de un cupo que estaba presente antes y cuya
  ausencia comienza dentro de la ventana de comida. Ausencias separadas por
  hasta `absence_merge_gap_minutes` se unen. Es excedida cuando dura más que
  `meal_allowed_minutes`. La duración media del dashboard incluye todas las
  pausas estimadas, aunque se muestre junto al conteo de pausas excedidas.

Una pausa estimada puede deberse a que alguien salió de la ROI, pero también a
oclusión, subconteo o una ROI inadecuada. No prueba que una persona concreta
haya ido a comer. Un cambio de ID del tracker no crea por sí mismo una pausa,
porque estas reglas usan el conteo total; sí puede afectar indirectamente si el
cambio produce un conteo incorrecto.

Para emitir estas estimaciones se exige al menos 80 % de cobertura: los primeros
15 minutos del turno para llegadas, los últimos 15 para salidas anticipadas, los
primeros 15 minutos de la ventana posterior a la tolerancia para después de hora
y toda la ventana configurada para comida.

#### Estados de evidencia

| Estado visible | Significado |
| --- | --- |
| Estimado | La ventana terminó y tuvo evidencia suficiente |
| Parcial | Solo algunas jornadas o turnos del período pudieron estimarse |
| Pendiente | La ventana relevante todavía no terminó |
| Sin datos suficientes | La ventana terminó pero no alcanzó el 80 % de cobertura requerido |
| No aplica | No existía turno, horario de comida o regla configurada para ese caso |

En un período semanal o mensual, `X/Y jornadas completas` muestra cuántas
jornadas aportaron una estimación completa para ese evento. Un promedio basado
en pocas jornadas debe leerse con más cautela aunque el número sea válido.

#### Alertas, baño y comedor

Las alertas cuentan notificaciones efectivamente emitidas, no minutos de
faltante. El conteo se suaviza durante `smoothing_window_seconds`; una condición
fuera del rango se confirma tras `incident_confirmation_seconds` y, si continúa,
se alerta después de `alert_after_seconds`. La vuelta al rango se confirma
durante `recovery_confirmation_seconds`. El dashboard separa faltantes y
sobrantes; la duración del incidente es otro dato.

Baño y comedor se calculan de forma independiente y sobre tiempo calendario
transcurrido. Esa cobertura suele diferir de la cobertura de turnos aun cuando
las cámaras funcionen de la misma manera. Si aparece “Línea de acceso pendiente”,
la cámara todavía no tiene una línea habilitada y calibrada para registrar
cruces. Puede mostrar ocupación y sesiones visibles, pero entradas, salidas y
duraciones de visita quedan pendientes. Cuando se habilita, las visitas se
emparejan en orden FIFO y siguen siendo estimaciones anónimas, sensibles a
cruces simultáneos, oclusiones, varias puertas y reinicios.

Los reportes históricos se interpretan con la configuración materializada
actual. Horarios, cupos o roles anteriores no están versionados todavía; cambiar
la configuración puede cambiar la lectura de datos históricos.

En el día actual, la cobertura usa solo el tiempo laboral transcurrido. Cada
turno distingue not_started, in_progress y complete; un evento cuya ventana no
terminó queda pending. Falta de configuración, falta de evidencia y conteo cero
son estados diferentes.

Para una zona con mínimo 1 y máximo 2:

1. Un conteo suavizado de 0 sostenido abre un incidente missing.
2. Un conteo de 3 o más sostenido abre un incidente extra.
3. Volver al rango durante el tiempo de recuperación cierra el incidente.
4. Superar alert_after_seconds después de confirmarlo emite la alerta.

Al arrancar, AEYE cierra incidentes heredados en la última muestra válida con
closure_reason=process_restart; el tiempo apagado no se inventa. Las alertas se
escriben en logs/alerts.jsonl, sus imágenes en logs/alert_images/ y, cuando
alerts.mode es webhook, también se envían por HTTP POST.

### Dashboard y API

El dashboard muestra períodos diarios, semanales de lunes a domingo y meses
calendario. Incluye una vista general y detalle por cámara, ocupación horaria,
cobertura, eventos y evolución. La exportación semanal/mensual ofrece PNG; la
opción PDF usa la impresión A4 vertical del navegador: primero muestra el
resumen general y después el detalle de cada cámara en el orden de las pestañas.

Rutas de reportes:

- GET /api/health
- GET /api/reporting/configuration
- GET /api/reports/daily?day=AAAA-MM-DD
- GET /api/reports/weekly?week=AAAA-MM-DD
- GET /api/reports/monthly?month=AAAA-MM-DD
- GET /api/reports/daily.csv?day=AAAA-MM-DD

Consultas analíticas:

- GET /api/analytics/understaffed-hours?zone=Zona&start=...&end=...
- GET /api/analytics/minutes-below-minimum?zone=Zona&start=...&end=...
- GET /api/analytics/occupancy-by-hour?zone=Zona&start=...&end=...
- GET /api/analytics/long-incidents?start=...&end=...&minutes=20
- GET /api/analytics/false-positives?start=...&end=...&minimum_reviews=10
- GET /api/analytics/employee-zone-time?start=...&end=...&employee_id=...
- GET /api/analytics/transitions?start=...&end=...&limit=20

Los intervalos son semiabiertos: start se incluye y end no. Usar ISO 8601 con
zona horaria, por ejemplo 2026-08-10T00:00:00-03:00.

Los endpoints individuales solo tienen datos cuando una integración externa
aporta identidad explícita y verificable, como badge, QR o RFID. Un track visual
no se convierte en identidad. La tasa de falsos positivos también requiere
revisiones humanas; sin ellas devuelve una lista vacía.

## Datos y auditoría

SQLite se inicializa con migraciones numeradas de database/migrations/. La ruta
predeterminada es data/aeye.db y puede cambiarse con AEYE_DB_PATH.

Antes de convertir porcentajes en indicadores formales:

1. calibrar cada ROI y línea con imágenes reales;
2. comparar los conteos con observación humana en varios turnos;
3. exigir cobertura alta, idealmente superior al 95 %;
4. probar oclusiones, cambios de luz y momentos de mayor movimiento;
5. observar continuamente entre 24 y 72 horas.

La auditoría abre SQLite en modo de solo lectura:

~~~bash
python3 tools/audit_activity_data.py \
  --day AAAA-MM-DD \
  --configuration-valid-from AAAA-MM-DD \
  --visual-labels /ruta/local/conteos.csv
~~~

El CSV local usa
camera_id,shift_id,observed_at,reported_count,manual_count. La herramienta
informa cobertura, exactitud, error absoluto medio, sesgo, sobreconteos y
subconteos. Por defecto, cada combinación cámara-turno necesita al menos 95 %
de cobertura, 90 % de conteos visuales exactos y 10 observaciones para quedar
passed. Los argumentos --coverage-threshold, --exact-threshold y
--minimum-visual-samples permiten cambiar esos umbrales; sin evidencia
suficiente el resultado queda pending.

Los horarios aún no están versionados. Un dato histórico se interpreta con la
configuración disponible y no debe certificarse como si se conociera la regla
vigente en su fecha.

## TensorRT y modelos

TensorRT es el único backend de producción. AEYE no acepta inference_backend,
no carga .pt en runtime, no exporta desde el contenedor productivo y falla al
arrancar si falta el .engine configurado.

~~~json
"tensorrt_engine": "yolov8n.engine",
"imgsz": 640
~~~

Regenerar el engine al cambiar GPU, JetPack, CUDA, TensorRT, imagen Docker,
modelo o imgsz. La forma rectangular se configura como [alto, ancho].

Para batching existe un engine dinámico de hasta ocho entradas:

~~~bash
tools/export_batch_engine.sh yolov8n.pt yolov8n_batch8.engine 8 640
~~~

~~~json
"tensorrt_engine": "yolov8n_batch8.engine",
"batching": {
  "enabled": true,
  "max_batch_size": 8,
  "timeout_ms": 10
}
~~~

AEYE valida resolución, forma dinámica y batch máximo al arrancar. Con ocho
cámaras a 6 FPS, el lote redujo el costo TensorRT por imagen pero aumentó la
latencia p95 y la RAM; por eso la ruta secuencial sigue recomendada para esa
carga. Conviene repetir la comparación si cambian cantidad de cámaras,
frecuencia o prioridad entre throughput y latencia.

Una evaluación FP16 sobre COCO val comparó YOLO11/YOLO26 nano y small en
640x640 y 960x544. YOLO26s FP16 640 fue el candidato equilibrado preliminar
(mAP50-95 de persona 0,5936 y MAE de conteo 0,910) y sostuvo ocho cámaras en una
prueba de 120 segundos. Esto no demuestra que sea el engine desplegado ni que
sea el mejor para las escenas AEYE: debe validarse con imágenes anotadas de cada
cámara antes de cambiar producción. YOLO26n 640 queda como alternativa de menor
costo.

INT8 permanece bloqueado hasta contar con datos AEYE representativos, baseline
FP16 y umbrales acordados de pérdida en precisión, recall, conteo, incidentes y
estabilidad del tracker. COCO por sí solo no sirve para calibrar ni aprobarlo.

## Rendimiento

La instrumentación escribe performance_summary.json con FPS recibidos y
analizados, descartes, duplicados, reconexiones y latencias de preproceso,
TensorRT, postproceso, tracker, scheduler y antigüedad del frame. La latencia
capture_to_result_ms comienza cuando el lector entrega el frame decodificado;
no incluye exposición de cámara, red ni el tiempo interno de decodificación.

Herramientas disponibles (sus nombres stage se conservan por compatibilidad,
pero no representan fases obligatorias):

~~~bash
tools/run_stage0_baseline.sh
tools/run_stage1_fps.sh 120
tools/run_stage2_nvdec.sh 120
tools/run_stage3_batching.sh 120
tools/run_stage4_pipeline.sh 120
tools/prepare_coco_val.sh
tools/run_stage5_accuracy.sh
tools/run_stage5_operational.sh 120
~~~

Conclusiones observadas en la Jetson de prueba con ocho streams, preview
apagado y ventanas de 120 segundos:

- 6 FPS por cámara fue el máximo conservador del scheduler secuencial: entregó
  aproximadamente 5,78 frames distintos por segundo y mantuvo margen.
- 4 FPS es una alternativa de menor consumo; 8 FPS fue mejor esfuerzo y repitió
  más frames porque las fuentes entregaban alrededor de 8 FPS.
- TensorRT no fue el cuello de botella en el engine YOLOv8n 640 utilizado para
  esas pruebas: su p95 se mantuvo cerca de 6 ms.
- GStreamer/NVDEC funcionó en las ocho cámaras, pero la conversión a BGR aumentó
  CPU, RAM, consumo y latencia p95; FFmpeg permanece predeterminado.
- El batching promedio de 7,34 imágenes bajó 24,2 % la inferencia por imagen,
  pero agregó cerca de 98 ms a la latencia p95 y unos 140 MB de RAM.
- Compartir el último frame inmutable y transferir resultados packed eliminó
  copias redundantes. El efecto sobre el detector completo fue pequeño y no
  autoriza cambios de precisión o NMS.
- Las pruebas cortas no demostraron estabilidad de memoria, temperatura o
  cobertura durante 24 a 72 horas.

Las comparaciones operativas con cámaras usaron configuraciones temporales y
una base aislada, mantuvieron constantes resolución, preview, potencia y
duración, y cambiaron la ruta estudiada; el ensayo de batching también necesitó
su engine dinámico compatible. La matriz de precisión fue otra prueba: evaluó
los engines sobre COCO sin streams ni preview. Los runners fallan si detectan
errores o si no se activa la ruta que pretenden medir. Guardan
performance_summary.json, telemetría y resúmenes bajo benchmarks/, que
permanece fuera de Git.

En la comparación de copias, el brazo optimizado mostró además un aumento de
aproximadamente 84 ms en captura-a-resultado p95, acompañado por jitter severo
de una cámara y ejecuciones en orden fijo. Ese cambio no se atribuye a la
optimización local, que elimina menos de medio milisegundo. Una comparación
causal de latencia debe alternar el orden ABBA y repetirse con streams estables.

Los resultados históricos fueron obtenidos con Jetson Linux R39.2.0, modo 15 W
y una configuración concreta. Son una referencia reproducible, no una promesa
para otro hardware, stream o engine. Los artefactos crudos viven localmente en
benchmarks/ y están excluidos de Git.

~~~bash
python3 tools/benchmark_detector.py imagen.jpg --warmup 20 --runs 200
~~~

El FPS teórico solo mide inferencia. No incluye RTSP, tracking, preview ni
reparto entre cámaras, y sin anotaciones el benchmark no mide precisión.

## Desarrollo y pruebas

La suite no necesita cámaras conectadas:

~~~bash
python3 -m unittest discover -s tests -v
~~~

La estructura de instrucciones para asistentes de código se mantiene separada
porque es configuración operativa de las herramientas, no documentación de
producto. [AGENTS.md](AGENTS.md) enruta las tareas y
[skills/](skills/AGENTS.md) contiene las guías canónicas por área.

En un clon nuevo, crear primero los enlaces compartidos y luego validarlos:

~~~bash
python3 tools/sync_agent_skills.py
python3 tools/sync_agent_skills.py --check
python3 -m unittest discover -s tests -p 'test_agent_structure.py' -v
~~~

El primer comando escribe solamente los enlaces faltantes bajo .agents/skills;
--check no escribe y falla de forma deliberada si aún faltan. Si no están
disponibles PyYAML o tomli, usar un entorno aislado:

~~~bash
python3 -m venv /tmp/aeye-agent-tools
/tmp/aeye-agent-tools/bin/pip install -r requirements-agent-tools.txt
/tmp/aeye-agent-tools/bin/python tools/sync_agent_skills.py --check
~~~

En Codex, abrir el proyecto en una conversación nueva e invocar una skill, por
ejemplo: Usa $aeye-activity para revisar un reporte con datos temporales. Si no
aparecen las skills, reiniciar la sesión y ejecutar el check anterior. El soporte
de agentes personalizados depende de la versión del cliente; el agente principal
puede leer la misma skill cuando no estén disponibles.

En OpenCode, iniciar desde la raíz, seleccionar el agente aeye o invocar uno
específico, por ejemplo: @aeye-web revisa la exportación del reporte. La carga
real debe verificarse en el cliente instalado; la existencia de adaptadores no
demuestra que una sesión ya los haya descubierto.

Las skills no otorgan permisos ni autorizan por sí solas reinicios, migraciones
reales, despliegues, pushes, cambios SSH o transferencias de imágenes.

## Estado y trabajo pendiente

Implementado:

- estado no_data, suavizado, histéresis y recuperación tras reinicios;
- ByteTrack local por cámara y ROI normalizada;
- TensorRT único, batching opcional y optimizaciones de copias;
- reportes de actividad anónima, dashboard, CSV, PNG/PDF y cobertura auditable;
- áreas comunes con tracks locales y visitas FIFO opcionales;
- cierre correcto de SQLite y pruebas con bases temporales.

Pendiente antes de considerar una instalación validada:

- completar nombres, cupos, horarios, ROI y líneas de acceso reales;
- anotar escenas AEYE y contrastar conteos/eventos por cámara y turno;
- versionar reglas y horarios con vigencia histórica;
- agregar revisión humana de incidentes y conservar sus decisiones;
- medir p95, precisión, memoria, temperatura, consumo y cobertura durante 24-72
  horas con todas las cámaras;
- reproducir un posible caso donde agregados semanales o mensuales omitan
  eventos parciales observados en uno de varios turnos;
- integrar badge, QR o RFID antes de habilitar métricas individuales;
- evaluar DeepStream o energía/térmica solo si las mediciones lo justifican;
- definir retención de datos e imágenes y, si cambia el alcance de red, diseñar
  autenticación y permisos como una tarea explícita.

## Límites y uso responsable

- ByteTrack puede cambiar IDs con oclusiones o cruces complejos.
- El conteo no distingue empleados, clientes ni proveedores.
- Una detección no demuestra productividad, intención, incumplimiento o motivo
  de ausencia.
- El cambio de turno puede conservar la misma ocupación sin demostrar relevo.
- Las estimaciones no deben automatizar decisiones laborales o disciplinarias.
- Una instalación real necesita acceso controlado, retención definida, revisión
  humana y cumplimiento de la normativa aplicable.

## Archivos no publicados

.gitignore excluye deliberadamente:

- cameras.json y credenciales locales;
- bases SQLite y archivos WAL/SHM;
- logs e imágenes de evidencia;
- modelos y artefactos .pt, .onnx, .engine y .plan;
- datasets, benchmarks, caches y copias .orig;
- .env y nombres que contengan password.

Antes de publicar cambios, revisar git status y el contenido exacto que se va a
incluir.
