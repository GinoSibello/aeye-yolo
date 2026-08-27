# ETAPA 4: copias y conversiones del pipeline

Esta etapa perfila el camino secuencial elegido en la Etapa 3 y reduce dos
operaciones redundantes sin cambiar el engine, la resolucion, la confianza, el
tracker ni las reglas. Se probaron ocho camaras, captura FFmpeg, 6 FPS por
camara, TensorRT FP16 batch 1, preview desactivado y modo de potencia de 15W.

## Estado

Quedan habilitadas en la configuracion local dos optimizaciones equivalentes
funcionalmente a la ruta anterior:

- el lector comparte una vista de solo lectura del ultimo frame, porque captura
  publica un `ndarray` nuevo y nunca vuelve a modificarlo;
- AEYE trae de GPU a CPU una sola matriz por resultado con columnas
  `x1, y1, x2, y2, confianza, clase`, en lugar de tres transferencias.

La copia del preview se conserva porque el overlay si modifica los pixeles. La
copia del backend GStreamer tambien se conserva porque el buffer deja de ser
valido al liberar el mapeo. Las imagenes de alertas son excepcionales y no
forman parte del camino sostenido.

Configuracion activa:

```json
"pipeline": {
  "copy_latest_frame": false,
  "result_transfer": "packed"
}
```

Para volver al comportamiento historico se usan `true` y `"split"`. Si la
seccion no existe, esos valores historicos siguen siendo los predeterminados.

## Perfil previo

El baseline secuencial de Etapa 3 mostro estos promedios por imagen:

| Etapa | Promedio | p95 |
| --- | ---: | ---: |
| Preprocesamiento Ultralytics | 3.830 ms | 4.655 ms |
| Inferencia TensorRT | 5.998 ms | 6.210 ms |
| Postprocesamiento/NMS | 3.933 ms | 5.550 ms |
| Detector completo | 15.774 ms | 18.114 ms |

Un perfil sintetico con la misma entrada 768 x 432 desgloso el preprocesamiento
en `0.839 ms` de resize/letterbox, `0.179 ms` de `np.stack`, `0.622 ms` de
BGR-HWC a RGB-CHW contiguo, `0.368 ms` de host a GPU y `0.973 ms` de conversion
FP16 y normalizacion. Fusionar solamente `stack` y el cambio de layout ahorro
aproximadamente `0.15 ms` en microbenchmark, pero exige mantener un predictor
acoplado a APIs internas de Ultralytics.

La copia aislada de un frame 768 x 432 BGR, de 0.949 MiB, costo `0.093 ms` en
microbenchmark. Dentro del proceso real, incluyendo la adquisicion del lock, el
baseline midio `0.197 ms` promedio.

## Metodo reproducible

La comparacion completa se ejecuta con:

```bash
tools/run_stage4_pipeline.sh 120
```

El runner genera cuatro configuraciones temporales en este orden:

1. `baseline`: copia de frame y tres transferencias de resultado.
2. `shared_frame`: referencia compartida y transferencias separadas.
3. `packed_results`: copia de frame y una transferencia empaquetada.
4. `optimized`: referencia compartida y transferencia empaquetada.

Todos los brazos fuerzan FFmpeg, engine batch 1 y batching deshabilitado. El
runner falla si cambia el backend, se habilita batching o aparece un error de
procesamiento. Los resultados locales, excluidos de Git, quedaron en:

- `benchmarks/stage4_baseline_20260827_123736/`
- `benchmarks/stage4_shared_frame_20260827_123950/`
- `benchmarks/stage4_packed_results_20260827_124203/`
- `benchmarks/stage4_optimized_20260827_124416/`
- `benchmarks/stage4_20260827_123736/stage4_summary.json`

## Resultados locales

| Metrica | Baseline | Solo frame | Solo resultado | Optimizado |
| --- | ---: | ---: | ---: | ---: |
| Snapshot promedio | 0.197 ms | 0.003 ms | 0.198 ms | 0.003 ms |
| Snapshot p95 | 0.233 ms | 0.004 ms | 0.233 ms | 0.004 ms |
| Conversion resultado promedio | 0.431 ms | 0.404 ms | 0.155 ms | 0.155 ms |
| Conversion resultado p95 | 0.751 ms | 0.727 ms | 0.257 ms | 0.251 ms |
| Detector completo promedio | 15.902 ms | 15.771 ms | 15.600 ms | 15.781 ms |
| Detector completo p95 | 18.291 ms | 18.111 ms | 17.638 ms | 17.955 ms |
| Errores de proceso/conexion | 0 | 0 | 0 | 0 |

La referencia compartida redujo el snapshot 98.5% y elimina aproximadamente
`38.37 MiB/s` de trafico de copia CPU con la carga observada. La transferencia
empaquetada redujo la conversion de resultados 64.0%. En conjunto, el p95 del
detector bajo 0.336 ms, 1.8%; es una mejora pequena pero consistente con el
costo local eliminado.

Los promedios de preprocesamiento quedaron entre 3.685 y 3.746 ms. Los de
postprocesamiento quedaron entre 4.023 y 4.261 ms. Las optimizaciones no movieron
esos trabajos internos: `result_conversion_ms` ocurre despues del NMS reportado
por Ultralytics.

## Variabilidad observada

| Metrica | Baseline | Optimizado | Cambio observado |
| --- | ---: | ---: | ---: |
| FPS unicos activos/camara | 5.799 | 5.502 | -5.1% |
| Captura a resultado p95 | 162.428 ms | 246.910 ms | +84.482 ms |
| CPU media | 22.414% | 21.713% | -0.701 puntos |
| GPU media | 26.580% | 25.936% | -0.644 puntos |
| Potencia media | 6.689 W | 6.584 W | -0.105 W |

Estas diferencias no se atribuyen a la optimizacion. Los brazos se ejecutaron
en orden y `cam08` mantuvo unos 8.16 FPS recibidos, pero paso de 17 a 166
analisis duplicados y su antiguedad p95 crecio de 144 ms a 1042 ms. Esto indica
entrega en rafagas o jitter externo durante la serie. Tambien hubo variacion en
otras camaras. El codigo optimizado no cambia captura ni scheduling y reduce
menos de medio milisegundo local, por lo que no explica decenas de milisegundos
de aumento. Una comparacion futura de latencia extremo a extremo debe alternar
el orden ABBA y repetirse con streams estables.

## Decision sobre pre y postprocesamiento

No se reemplaza el preprocesador de Ultralytics en esta etapa. El ahorro seguro
estimado al fusionar dos copias es de solo unos `0.15 ms`, a cambio de depender
de una clase interna que puede cambiar entre versiones. Llevar resize, cambio
de color y normalizacion completamente a GPU podria ser mas relevante, pero
requiere una ruta de entrada distinta y validar que las cajas resultantes sean
identicas.

Tampoco se cambia NMS, `confidence`, `max_det` ni se exporta un engine con NMS
integrado. El postprocesamiento si es material, alrededor de 4 ms, pero esas
opciones pueden cambiar que personas sobreviven al filtrado. Antes de aplicarlas
se necesita un conjunto representativo anotado y comparar precision, recall,
conteos por zona y estabilidad de ByteTrack. Sin esa evidencia, una mejora de
latencia no justifica alterar las metricas laborales.

## Limites

- La ventana de 120 segundos valida funcionamiento y costo local, no estabilidad
  durante 24 a 72 horas.
- Los tiempos de Ultralytics agrupan operaciones y sincronizaciones; no son un
  perfil CUDA completo por kernel.
- El benchmark no demuestra precision porque no usa anotaciones humanas.
- La referencia compartida depende del contrato actual: captura reemplaza el
  frame, la vista rechaza escrituras y cualquier consumidor que quiera dibujar
  debe copiar antes.
