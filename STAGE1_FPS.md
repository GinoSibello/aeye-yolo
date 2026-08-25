# ETAPA 1: frecuencia de inferencia por camara

Este documento compara 2, 4, 6 y 8 FPS solicitados por camara. En cada corrida
se cambio unicamente `system.inference_fps_per_camera`; se conservaron las ocho
camaras, streams, engine TensorRT, resolucion 640 x 640, tracker, preview
desactivado, contenedor y modo de potencia de 15W.

## Estado

Las cuatro corridas de 120 segundos finalizaron correctamente el 25 de agosto
de 2026. No se cambio `cameras.json`: el runner genero copias temporales,
modifico el campo de FPS mediante un parser JSON y las monto en Docker como
solo lectura. La configuracion operativa continua en 2 FPS por camara.

Los datos crudos quedaron aislados y excluidos de Git:

- `benchmarks/stage1_fps2_20260825_184007/`
- `benchmarks/stage1_fps4_20260825_184216/`
- `benchmarks/stage1_fps6_20260825_184426/`
- `benchmarks/stage1_fps8_20260825_184636/`
- `benchmarks/stage1_20260825_184007/stage1_summary.json`

## Metodo reproducible

La serie completa se ejecuta con:

```bash
tools/run_stage1_fps.sh 120
```

Cada punto espera que AEYE complete el arranque, mide durante 120 segundos,
captura `tegrastats` cada 100 ms y detiene el contenedor limpiamente. Se
utiliza el mismo procedimiento para las cuatro frecuencias.

Se distinguen dos conceptos:

- **Llamadas activas:** ejecuciones del detector por segundo desde el primer
  hasta el ultimo analisis de cada camara.
- **Frames unicos activos:** frames distintos realmente analizados por segundo.
  Repetir el ultimo frame cuenta como llamada, pero no como nueva informacion.

Los FPS agregados de ventana completa incluyen el arranque escalonado de las
camaras. Para evaluar capacidad sostenida se usan principalmente los FPS
activos.

## Resultados de procesamiento

| FPS solicitados | Llamadas activas/camara | Frames unicos/camara | Cumplimiento unico | FPS agregados, ventana completa | Frames no seleccionados | Duplicados |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 1.991 | 1.990 | 99.5% | 13.548 | 75.8% | 1 |
| 4 | 3.959 | 3.870 | 96.8% | 27.016 | 52.8% | 71 |
| 6 | 5.904 | 5.777 | 96.3% | 40.247 | 29.7% | 106 |
| 8 | 7.707 | 7.205 | 90.1% | 52.227 | 12.2% | 410 |

Los ocho streams entregaron en conjunto aproximadamente 56 FPS durante la
ventana completa. Por eso 8 FPS unicos por camara tampoco pueden garantizarse
si la fuente entrega alrededor de 8 FPS y existe variacion de llegada.

| FPS solicitados | Scheduler p95 ms | Frame age p95 ms | TensorRT p95 ms | Captura a resultado p95 ms |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 4.848 | 137.957 | 6.271 | 156.223 |
| 4 | 4.858 | 154.006 | 6.258 | 173.704 |
| 6 | 4.837 | 139.852 | 6.197 | 156.656 |
| 8 | 17.613 | 135.157 | 6.096 | 151.007 |

Los maximos de cada corrida incluyen la primera carga perezosa de TensorRT y no
representan el comportamiento sostenido. Los p95 muestran que la latencia total
no empeoro de forma sistematica, pero el retraso del scheduler salto de unos
4.8 ms a 17.6 ms al solicitar 8 FPS.

## Recursos

| FPS solicitados | GPU promedio | CPU promedio | Nucleo CPU p95 | RAM promedio | Temp. maxima | Potencia promedio |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 8.85% | 17.54% | 90% | 4698 MB | 51.16 C | 5.64 W |
| 4 | 17.95% | 21.01% | 90% | 4701 MB | 52.50 C | 6.16 W |
| 6 | 26.27% | 23.23% | 90% | 4721 MB | 53.38 C | 6.69 W |
| 8 | 33.85% | 23.31% | 81% | 4728 MB | 54.38 C | 7.32 W |

La GPU maxima fue 62% y la temperatura maxima 54.38 C. No hubo senales de
limite termico, energetico o de memoria en estas ventanas. Dos minutos no son
suficientes para demostrar estabilidad de RAM durante 24 a 72 horas.

Jetson Linux R39.2 no incluyo campos EMC ni NVDEC en estas muestras de
`tegrastats`. NVDEC queda como no informado, no como utilizacion cero.

## Estabilidad observada

En las cuatro corridas hubo:

- Cero errores de inferencia o tracking.
- Cero errores de conexion y cero reconexiones.
- Cero terminaciones inesperadas.
- Ciclos `no_data` durante el arranque escalonado, que aumentan con la
  frecuencia solicitada porque el scheduler consulta mas veces antes del primer
  frame.

## Diagnostico

- TensorRT no es el cuello de botella: su p95 se mantuvo cerca de 6 ms y la GPU
  promedio llego solamente a 33.85% en el punto mas exigente.
- De 2 a 6 FPS, el scheduler mantuvo el mismo p95 y se obtuvo aproximadamente
  96% o mas del objetivo en frames distintos.
- A 8 FPS, el bucle secuencial empieza a quedarse sin margen: baja el
  cumplimiento, el scheduler se retrasa y 6.5% de las llamadas repite un frame.
- Configurar 8 FPS no produce 8 observaciones nuevas por segundo. El resultado
  medido fue aproximadamente 7.2 frames unicos por camara.
- Los porcentajes de descarte bajan al subir FPS, pero el costo de decodificar
  todos los frames ya se paga en CPU con el lector actual.

## Limite recomendado

**6 FPS por camara es el maximo conservador y reproducible del pipeline actual.**
Entrega aproximadamente 5.78 frames distintos por segundo y conserva margen en
el scheduler. Para una configuracion operativa con menor consumo, 4 FPS entrega
aproximadamente 3.87 frames distintos por segundo.

8 FPS puede utilizarse como modo de mejor esfuerzo, pero no debe prometerse
como frecuencia fiable con el scheduler secuencial y los streams actuales. La
configuracion real queda en 2 FPS hasta que se decida explicitamente cambiarla.

## Siguiente etapa

La siguiente prueba aislada es un prototipo de decodificacion NVDEC con
GStreamer y fallback configurable al lector FFmpeg actual. El resto del
pipeline debe permanecer igual para comparar CPU, latencia y estabilidad antes
de considerar batching.
