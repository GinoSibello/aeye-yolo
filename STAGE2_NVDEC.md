# ETAPA 2: prototipo GStreamer NVDEC

Esta etapa implementa y compara un lector RTSP H.265 basado en GStreamer y
`nvv4l2decoder` contra el lector OpenCV/FFmpeg existente. No se cambio el
engine TensorRT, la resolucion de inferencia, el tracker, el scheduler, las
reglas, el preview ni el modo de potencia.

## Estado

El prototipo funciona con las ocho camaras, pero **no queda recomendado como
backend predeterminado**. En la prueba A/B de 120 segundos NVDEC conecto mas
rapido, pero aumento CPU media, RAM, consumo y latencia p95. La configuracion
operativa no contiene una seccion `capture`, por lo que continua usando
FFmpeg y 2 FPS por camara.

La imagen anterior se preservo localmente como `aeye-yolo:stage1`. La nueva
imagen `aeye-yolo:dev` agrega GStreamer 1.24.2 y ocupa aproximadamente 145 MiB
mas.

## Implementacion

El nuevo pipeline por camara es:

```text
rtspsrc (TCP, jitterbuffer 200 ms)
  -> rtph265depay
  -> h265parse
  -> nvv4l2decoder
  -> nvvidconv
  -> BGRx
  -> videoconvert
  -> BGR
  -> appsink (max-buffers=1, drop=true, sync=false)
```

`appsink` mantiene como maximo un frame y descarta el anterior cuando el
consumidor no llega a tiempo. AEYE conserva ademas su politica existente de
guardar solamente el frame mas reciente por camara.

La URL se asigna directamente a la propiedad `location` de `rtspsrc`; no se
concatena dentro de la descripcion del pipeline ni se guarda en los resumenes.
Los errores GStreamer se sanitizan antes de llegar a logs o al fallback.

Los backends aceptados son:

- `ffmpeg`: comportamiento anterior y valor predeterminado.
- `gstreamer_nvdec`: pipeline NVIDIA para H.264 o H.265.
- `fallback_to_ffmpeg`: permite volver a FFmpeg si NVDEC no puede iniciar o
  falla durante la lectura.

Ejemplo:

```json
"capture": {
  "backend": "gstreamer_nvdec",
  "fallback_to_ffmpeg": true,
  "codec": "h265",
  "rtsp_latency_ms": 200,
  "read_timeout_ms": 15000
}
```

## Validacion de hardware

Dentro del contenedor se confirmaron:

- GStreamer 1.24.2 y bindings Python GI.
- `rtspsrc`, `rtph265depay`, `h265parse`, `nvv4l2decoder`,
  `nvvidconv`, `videoconvert` y `appsink`.
- Dispositivo NVIDIA `/dev/v4l2-nvdec`.
- Ocho descriptores abiertos sobre `/dev/v4l2-nvdec` durante la corrida NVDEC,
  uno por cada pipeline de camara.
- Ocho backends efectivos `gstreamer_nvdec`, sin fallback.

Jetson Linux R39.2 no publico un campo NVDEC en `tegrastats`. Por eso el
porcentaje queda como no informado. Los descriptores del dispositivo y la
recepcion de frames a traves de `nvv4l2decoder` son la evidencia alternativa
de uso del decoder.

## Metodo reproducible

La comparacion completa se ejecuta con:

```bash
tools/run_stage2_nvdec.sh 120
```

El runner genera dos configuraciones temporales desde `cameras.json`. Conserva
los 2 FPS, las ocho camaras y todo el pipeline; cambia solamente
`system.capture.backend`. El brazo NVDEC desactiva el fallback durante el
benchmark y falla si alguna camara no confirma el backend esperado.

Los datos definitivos quedaron excluidos de Git:

- `benchmarks/stage2_ffmpeg_20260825_192247/`
- `benchmarks/stage2_gstreamer_nvdec_20260825_192500/`
- `benchmarks/stage2_20260825_192247/stage2_summary.json`

## Resultado funcional

| Metrica | OpenCV/FFmpeg | GStreamer/NVDEC | Diferencia |
| --- | ---: | ---: | ---: |
| FPS recibidos activos por camara | 8.163 | 8.005 | -0.158 |
| FPS unicos analizados por camara | 1.991 | 1.993 | +0.002 |
| FPS analizados, ventana completa | 13.550 | 15.256 | +1.706 |
| Ciclos `no_data` de arranque | 236 | 27 | -209 |
| Duplicados | 0 | 1 | +1 |
| Errores de captura/proceso | 0 | 0 | 0 |
| Reconexiones | 0 | 0 | 0 |

NVDEC completo las conexiones iniciales antes y por eso produjo mas resultados
en la ventana total. Una vez activas, ambas rutas entregaron la misma frecuencia
de analisis solicitada.

## Latencia

| Metrica | OpenCV/FFmpeg | GStreamer/NVDEC | Cambio NVDEC |
| --- | ---: | ---: | ---: |
| Scheduler p95 | 4.854 ms | 4.830 ms | -0.024 ms |
| Antiguedad de frame p50 | 65.348 ms | 63.139 ms | -2.209 ms |
| Antiguedad de frame p95 | 132.911 ms | 141.676 ms | +8.765 ms |
| Captura a resultado p50 | 84.251 ms | 81.387 ms | -2.864 ms |
| Captura a resultado p95 | 153.265 ms | 161.874 ms | +8.609 ms |
| TensorRT p95 | 6.317 ms | 6.607 ms | +0.290 ms |

NVDEC mejoro levemente la mediana, pero empeoro la cola p95. La latencia medida
empieza cuando el lector entrega un frame decodificado; no incluye exposicion,
red ni tiempo interno del decoder.

## Recursos

| Metrica | OpenCV/FFmpeg | GStreamer/NVDEC | Cambio NVDEC |
| --- | ---: | ---: | ---: |
| CPU media | 17.680% | 18.894% | +1.214 puntos (+6.9%) |
| CPU p95 | 37.167% | 38.833% | +1.666 puntos |
| Nucleo mas ocupado p95 | 90.0% | 89.2% | -0.8 puntos |
| GPU media | 8.430% | 10.032% | +1.602 puntos |
| RAM media | 4843 MB | 4978 MB | +135 MB |
| RAM maxima | 4898 MB | 5016 MB | +118 MB |
| Temperatura maxima | 51.75 C | 52.16 C | +0.41 C |
| Potencia media | 5.655 W | 5.870 W | +0.215 W (+3.8%) |

No hubo limite termico ni de potencia. Dos minutos no permiten demostrar
estabilidad de memoria durante 24 a 72 horas.

## Diagnostico

- NVDEC esta realmente activo, pero el prototipo no reduce el uso total de CPU.
- El costo probable se desplazo a conversion de color, copias desde superficies
  NVMM hacia memoria CPU y entrega por `appsink`.
- El camino FFmpeg no queda demostrado como software ni como hardware: esta
  etapa solamente confirma que no solicita explicitamente
  `nvv4l2decoder`.
- La mejora de arranque es real en esta corrida, pero no compensa por si sola
  los aumentos de CPU, RAM, consumo y p95.
- La direccion del cambio de CPU coincide con el smoke previo de 45 segundos,
  aunque una unica prueba A/B no permite estimar variabilidad estadistica fina.

## Decision

FFmpeg permanece como backend predeterminado. El prototipo NVDEC queda
disponible detras de configuracion y con fallback para continuar investigando,
pero no debe activarse en produccion con la expectativa de ahorrar CPU.

Reducir conversiones y copias NVMM/BGR corresponde a una prueba aislada
posterior. La siguiente etapa propuesta en la hoja de ruta es batching entre
camaras con un engine TensorRT que admita batch mayor que uno.
