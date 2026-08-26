# ETAPA 2: prototipo GStreamer NVDEC

Esta etapa implementa y compara un lector RTSP H.265 basado en GStreamer y
`nvv4l2decoder` contra el lector OpenCV/FFmpeg existente. No se cambio el
engine TensorRT, la resolucion de inferencia, el tracker, el scheduler, las
reglas, el preview ni el modo de potencia.

## Estado

El prototipo funciona con las ocho camaras, pero **no queda recomendado como
backend predeterminado**. En la prueba A/B de 120 segundos a 6 FPS NVDEC
conecto mas rapido, pero aumento CPU media, RAM, consumo y latencia p95. La
configuracion operativa no contiene una seccion `capture`, por lo que continua
usando FFmpeg, ahora a 6 FPS por camara.

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
los 6 FPS, las ocho camaras y todo el pipeline; cambia solamente
`system.capture.backend`. El brazo NVDEC desactiva el fallback durante el
benchmark y falla si alguna camara no confirma el backend esperado.

Los datos definitivos quedaron excluidos de Git:

- `benchmarks/stage2_ffmpeg_20260825_201852/`
- `benchmarks/stage2_gstreamer_nvdec_20260825_202105/`
- `benchmarks/stage2_20260825_201852/stage2_summary.json`

## Resultado funcional

| Metrica | OpenCV/FFmpeg | GStreamer/NVDEC | Diferencia |
| --- | ---: | ---: | ---: |
| FPS recibidos activos por camara | 8.161 | 8.005 | -0.156 |
| FPS analizados activos por camara | 5.910 | 5.913 | +0.003 |
| FPS unicos analizados por camara | 5.848 | 5.734 | -0.114 |
| FPS analizados, ventana completa | 40.311 | 45.290 | +4.979 |
| Ciclos `no_data` de arranque | 677 | 75 | -602 |
| Duplicados | 52 | 167 | +115 |
| Errores de captura/proceso | 0 | 0 | 0 |
| Reconexiones | 0 | 0 | 0 |

NVDEC completo las conexiones iniciales antes y por eso produjo mas resultados
en la ventana total. Una vez activas, ambas rutas se acercaron a los 6 FPS de
analisis solicitados, aunque la frecuencia de frames distintos quedo entre
5.734 y 5.848 FPS. NVDEC repitio mas frames que FFmpeg.

## Latencia

| Metrica | OpenCV/FFmpeg | GStreamer/NVDEC | Cambio NVDEC |
| --- | ---: | ---: | ---: |
| Scheduler p95 | 4.864 ms | 4.853 ms | -0.011 ms |
| Antiguedad de frame p50 | 63.926 ms | 64.898 ms | +0.972 ms |
| Antiguedad de frame p95 | 132.212 ms | 144.830 ms | +12.618 ms |
| Captura a resultado p50 | 80.769 ms | 81.755 ms | +0.986 ms |
| Captura a resultado p95 | 150.457 ms | 163.412 ms | +12.955 ms |
| TensorRT p95 | 6.241 ms | 6.359 ms | +0.118 ms |

NVDEC empeoro levemente la mediana y tambien la cola p95. La latencia medida
empieza cuando el lector entrega un frame decodificado; no incluye exposicion,
red ni tiempo interno del decoder.

## Recursos

| Metrica | OpenCV/FFmpeg | GStreamer/NVDEC | Cambio NVDEC |
| --- | ---: | ---: | ---: |
| CPU media | 23.355% | 24.371% | +1.016 puntos (+4.4%) |
| CPU p95 | 40.267% | 42.092% | +1.825 puntos |
| Nucleo mas ocupado p95 | 90.0% | 88.0% | -2.0 puntos |
| GPU media | 25.770% | 28.906% | +3.136 puntos |
| RAM media | 4913 MB | 4990 MB | +77 MB |
| RAM maxima | 4957 MB | 5014 MB | +57 MB |
| Temperatura maxima | 52.38 C | 53.31 C | +0.93 C |
| Potencia media | 6.693 W | 7.009 W | +0.315 W (+4.7%) |

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
