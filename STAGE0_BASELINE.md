# ETAPA 0: diagnostico y baseline

Este documento fija el punto de partida para optimizar AEYE sin cambiar todavia
su arquitectura, el engine, el modo de potencia ni la cantidad de camaras.

## Estado

La inspeccion, la instrumentacion y el baseline de 120 segundos estan completos.
La corrida valida se realizo el 25 de agosto de 2026 y quedo aislada en
`benchmarks/stage0_20260825_181317/`. No se cambio `nvpmodel`, no se activaron
clocks y no se modifico el engine TensorRT.

## Configuracion observada

| Parametro | Valor |
| --- | --- |
| Jetson Linux | R39.2.0, aarch64 |
| Modo de potencia | 15W, ID 0 |
| Camaras habilitadas | 8 |
| Canal configurado | 102 en las 8 camaras |
| Preview inicial | Desactivado |
| Frecuencia solicitada | 2 FPS por camara |
| Resolucion de inferencia | 640 x 640 |
| Engine | YOLOv8n TensorRT, FP16 |
| Batch del engine | Fijo en 1 |
| Forma dinamica | No |
| NMS dentro del engine | No |

El engine fijo en batch 1 no puede recibir un lote mayor sin regenerarse. Esto
es un limite observado, no una recomendacion de cambio en esta etapa.

## Pipeline actual

| Paso | Ejecucion actual | Recurso principal |
| --- | --- | --- |
| Captura RTSP | Un `CameraReader` por camara, retiene solo el frame mas reciente | CPU, red y FFmpeg de OpenCV |
| Planificacion | Un bucle central recorre las camaras secuencialmente | CPU |
| Preproceso | Ultralytics prepara una entrada fija de 640 x 640 | CPU/GPU, a confirmar con tiempos |
| Inferencia | Engine TensorRT FP16, una imagen por llamada | GPU |
| Resultados | NMS de Ultralytics y conversion de tensores a listas Python | GPU/CPU y sincronizacion |
| Tracking | Una instancia ByteTrack por camara | CPU |
| Reglas | Suavizado, histeresis, alertas y persistencia | CPU y almacenamiento |
| Preview | JPEG solo cuando se activa desde el dashboard | CPU |

La inferencia no usa PyTorch como backend. Sin embargo, el adaptador actual de
ByteTrack crea un tensor CPU de PyTorch y un objeto `Boxes` para entregar las
detecciones al tracker. Esta dependencia se medira como parte de
`tracker_ms`; retirarla seria una optimizacion posterior y separada.

## Instrumentacion agregada

Cada ejecucion escribe `performance_summary.json` con valores globales y por
camara:

- FPS recibido y FPS analizado.
- Frames recibidos que no fueron seleccionados para analisis.
- Analisis duplicados del mismo frame.
- Ciclos sin datos y errores de procesamiento.
- Intentos de conexion, conexiones exitosas, errores y reconexiones.
- Resolucion, FPS y codec reportados por OpenCV.
- Promedio, p50, p95 y maximo de preproceso, inferencia, postproceso, detector
  completo, tracker, retraso del scheduler, antiguedad del frame y latencia al
  resultado.

`capture_to_result_ms` empieza cuando `VideoCapture.read()` entrega un frame
ya decodificado. No incluye exposicion de la camara, transito de red ni tiempo
interno de decodificacion. Esta limitacion queda guardada en el propio JSON.

## Baseline reproducible

Con Docker disponible sin interaccion:

```bash
tools/run_stage0_baseline.sh
```

La duracion predeterminada es 120 segundos y `tegrastats` toma muestras cada
100 ms. El script exige `preview.enabled=false`, usa el mismo engine y las
mismas 8 camaras, y no ejecuta `nvpmodel` en modo escritura.

Cada corrida queda aislada en
`benchmarks/stage0_<fecha>/` con:

| Archivo | Contenido |
| --- | --- |
| `performance_summary.json` | FPS, descartes, reconexiones y latencias |
| `tegrastats.log` | Telemetria cruda cada 100 ms |
| `tegrastats_summary.json` | GPU, CPU, RAM, temperatura y potencia |
| `container_opencv.txt` | Version y soporte FFmpeg/GStreamer del contenedor |
| `container_gstreamer.txt` | Version y plugins de captura disponibles |
| `capture_device_evidence.txt` | Descriptores abiertos sobre el decoder NVDEC |
| `host_runtime.txt` | Jetson Linux, arquitectura y modo de potencia |
| `aeye.log` | Log de la ejecucion aislada |
| `aeye.db` | SQLite separada de los datos operativos |

En Jetson Linux R39.2, `tegrastats` no muestra campos EMC o NVDEC en las
muestras observadas. El resumen los deja como `null`; eso significa
"no informado", no utilizacion cero.

## Resultado del baseline

La ventana activa medida fue de 120.207 segundos. Las ocho camaras se conectaron
sin desconexiones, reconexiones ni errores de inferencia. Todas reportaron HEVC,
768 x 432 y aproximadamente 8 FPS recibidos mientras estuvieron activas.

| Metrica global | Resultado |
| --- | --- |
| FPS recibidos durante toda la ventana | 55.945 |
| FPS analizados durante toda la ventana | 13.535 |
| FPS analizados sostenidos por camara, estimados desde el primer resultado | 1.984 a 1.996 |
| Frames recibidos | 6725 |
| Frames analizados | 1627 |
| Frames no seleccionados para analisis | 5098 (75.8%) |
| Analisis duplicados | 0 |
| Errores de procesamiento | 0 |
| Desconexiones o reconexiones | 0 |

El total de 13.535 FPS no representa una saturacion sostenida. Las conexiones
iniciales quedaron escalonadas entre 4 y 32 segundos; despues del primer
resultado, cada camara se mantuvo practicamente en los 2 FPS configurados.

| Etapa | Promedio ms | p50 ms | p95 ms | Maximo ms |
| --- | ---: | ---: | ---: | ---: |
| Antiguedad del frame | 71.558 | 67.031 | 148.565 | 375.671 |
| Preproceso | 4.279 | 4.347 | 4.911 | 29.450 |
| TensorRT | 6.063 | 6.028 | 6.303 | 12.336 |
| Postproceso | 4.380 | 4.056 | 6.141 | 46.524 |
| Detector completo | 18.261 | 16.108 | 19.016 | 3632.147 |
| ByteTrack | 2.027 | 1.584 | 4.185 | 9.169 |
| Frame decodificado a resultado | 91.933 | 85.538 | 167.063 | 3770.212 |

Los maximos de detector, scheduler y latencia corresponden a la primera carga
perezosa de TensorRT. Para carga sostenida, p50 y p95 son mas representativos.

| Recurso Jetson | Promedio | p95 | Maximo |
| --- | ---: | ---: | ---: |
| GPU | 8.651% | 38.0% | 59.0% |
| CPU media entre nucleos activos | 17.399% | 36.667% | 98.667% |
| Nucleo CPU mas ocupado | 42.111% | 90.0% | 100.0% |
| RAM | 4719.539 MB | 4789 MB | 4792 MB |
| Potencia VDD_IN | 5651.527 mW | 5988 mW | 7102 mW |
| Temperatura | - | - | 51.75 C |

La RAM se estabilizo cerca de 4783 MB en las ultimas muestras. El menor tamano
de bloque libre fue 0.125 MB, con 104 bloques en esa observacion; la menor suma
observada fue 1 bloque de 0.25 MB en otro instante. Son senales de fragmentacion
que merecen vigilancia en pruebas largas, pero 120 segundos no alcanzan para
diagnosticar una fuga de memoria.

## Diagnostico

- El sistema cumple de forma sostenida los 2 FPS por camara configurados.
- TensorRT no es el limite actual: su p95 es 6.303 ms y la GPU media es 8.651%.
- Hay picos de un nucleo CPU al 100%, aunque la CPU global conserva margen.
- Se decodifican cerca de 8 FPS por camara y se analizan 2; descartar alrededor
  del 75% es esperado por el buffer de ultimo frame, pero el costo de
  decodificacion ya fue pagado.
- OpenCV 5.0.0 dentro del contenedor tiene FFmpeg habilitado y GStreamer
  deshabilitado. El codigo usa explicitamente `CAP_FFMPEG`.
- R39 no informa EMC ni NVDEC en `tegrastats`; por eso no se puede afirmar con
  esta medicion si la decodificacion HEVC uso hardware.
- No hubo evidencia de inestabilidad RTSP o errores de detector/tracker.

## Continuacion

La prueba propuesta de frecuencia se completo para 2, 4, 6 y 8 FPS por camara.
Los resultados y el limite recomendado estan en
[STAGE1_FPS.md](STAGE1_FPS.md).
