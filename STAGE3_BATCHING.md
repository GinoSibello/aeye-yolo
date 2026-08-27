# ETAPA 3: batching entre camaras

Esta etapa implementa lotes TensorRT entre camaras y los compara contra la
ruta secuencial. Se conservaron las ocho camaras, captura FFmpeg, 6 FPS por
camara, resolucion 640 x 640, FP16, tracker, reglas, preview desactivado y modo
de potencia de 15W.

## Estado

El batching funciona y proceso lotes de hasta ocho camaras sin errores, pero
**no queda habilitado de forma predeterminada**. Redujo las llamadas TensorRT y
el costo de inferencia por imagen, pero aumento la latencia captura a resultado
p95 en 98 ms, uso 140 MB mas de RAM y entrego 1.8% menos frames unicos.

La configuracion operativa no contiene `system.batching`, por lo que conserva
la ruta secuencial, `yolov8n.engine` y FFmpeg a 6 FPS por camara.

## Engines validados

El engine anterior fue inspeccionado antes de implementar:

| Engine | Precision | Forma de entrada | Batch |
| --- | --- | --- | ---: |
| `yolov8n.engine` | FP16 | `(1, 3, 640, 640)` fija | 1 |
| `yolov8n_batch8.engine` | FP16 | dinamica | 1 a 8 |

El perfil TensorRT real del engine nuevo es:

```text
min: (1, 3, 32, 32)
opt: (8, 3, 640, 640)
max: (8, 3, 1280, 1280)
```

AEYE fija `imgsz=640`, valida la metadata al arrancar y rechaza batching si el
engine no es dinamico, admite menos imágenes que `max_batch_size` o usa otra
resolucion. El engine local ocupa 8.5 MB y su SHA-256 es:

```text
f4cad81693b9f2701fbf8fdb3ab46463940c29f53fd4f020ad8e1258c0a5263b
```

Los `.engine` y `.pt` siguen excluidos de Git porque dependen de la GPU,
JetPack, CUDA y TensorRT de esta Jetson. El engine se regenera localmente con:

```bash
tools/export_batch_engine.sh yolov8n.pt yolov8n_batch8.engine 8 640
```

La exportacion usa un contenedor temporal, instala ahi las dependencias ONNX de
ModelOpt, genera FP16 dinamico y valida el perfil deserializado. No agrega esas
dependencias al runtime de produccion.

## Planificacion

Cuando batching esta habilitado:

1. El primer vencimiento abre una ventana de hasta `timeout_ms`.
2. El scheduler agrupa solamente camaras cuyo turno ya vencio; nunca adelanta
   una inferencia para llenar el lote.
3. Consulta disponibilidad sin copiar y, al despachar, copia una sola vez el
   frame mas reciente de cada camara.
4. Envia como maximo un frame por camara y hasta `max_batch_size` frames.
5. Verifica que TensorRT devuelva exactamente un resultado por entrada.
6. Aplica los resultados sincronicamente en el mismo orden del lote.

Cada camara conserva su propia instancia `ByteTrackAdapter`. Una secuencia menor
que la ultima despachada se rechaza como error en vez de actualizar un tracker
fuera de orden. Secuencias iguales siguen siendo medibles como duplicados.

Configuracion disponible:

```json
"tensorrt_engine": "yolov8n_batch8.engine",
"batching": {
  "enabled": true,
  "max_batch_size": 8,
  "timeout_ms": 10
}
```

Si `batching` no existe o `enabled` es falso, AEYE normaliza el maximo a uno y
conserva el comportamiento secuencial.

## Metodo reproducible

La comparacion se ejecuta con:

```bash
tools/run_stage3_batching.sh 120
```

El runner crea configuraciones temporales y fuerza FFmpeg en ambos brazos. La
ruta secuencial usa el engine batch 1; batching usa el engine dinamico batch 8
y timeout de 10 ms. El runner falla si cambia el backend de captura, aparece un
error de procesamiento o el lote promedio no supera uno.

Los resultados quedaron excluidos de Git:

- `benchmarks/stage3_sequential_20260827_115134/`
- `benchmarks/stage3_batching_20260827_115347/`
- `benchmarks/stage3_20260827_115134/stage3_summary.json`

## Throughput

| Metrica | Secuencial | Batching | Cambio |
| --- | ---: | ---: | ---: |
| FPS recibidos activos/camara | 8.162 | 8.157 | -0.005 |
| FPS analizados activos/camara | 5.979 | 5.950 | -0.029 |
| FPS unicos activos/camara | 5.893 | 5.785 | -0.108 (-1.8%) |
| Cumplimiento unico de 6 FPS | 98.21% | 96.41% | -1.80 puntos |
| FPS analizados, ventana completa | 40.767 | 40.459 | -0.308 |
| Duplicados | 72 | 136 | +64 |
| Errores de proceso/conexion | 0 | 0 | 0 |
| Reconexiones | 0 | 0 | 0 |

El rango por camara fue 5.830-5.945 FPS unicos en secuencial y 5.684-5.871
con batching. Ambos se acercan al objetivo, pero la ruta secuencial conserva
mas observaciones distintas.

## Lotes y TensorRT

| Metrica | Secuencial | Batching | Cambio |
| --- | ---: | ---: | ---: |
| Llamadas TensorRT/s | 40.767 | 5.510 | -86.5% |
| Tamano de lote promedio | 1.000 | 7.343 | +6.343 |
| Tamano de lote p50 / p95 | 1 / 1 | 8 / 8 | -- |
| Llenado del lote | 100% | 91.79% | -8.21 puntos |
| Espera de lote p95 | 0 ms | 10.221 ms | +10.221 ms |
| Llamada completa p95 | 18.114 ms | 97.096 ms | +78.982 ms |
| Inferencia TensorRT por imagen p95 | 6.210 ms | 4.705 ms | -24.2% |

Batching aprovecha mejor cada llamada y reduce el costo TensorRT por imagen,
pero el lote completo retiene todos sus resultados hasta terminar.

## Latencia

| Metrica | Secuencial | Batching | Cambio |
| --- | ---: | ---: | ---: |
| Scheduler p95 | 3.270 ms | 10.314 ms | +7.044 ms |
| Antiguedad del frame p50 | 62.155 ms | 63.238 ms | +1.083 ms |
| Antiguedad del frame p95 | 134.465 ms | 145.452 ms | +10.987 ms |
| Captura a resultado p50 | 79.493 ms | 162.943 ms | +83.450 ms |
| Captura a resultado p95 | 152.231 ms | 250.579 ms | +98.348 ms (+64.6%) |

La medicion comienza cuando el backend entrega el frame decodificado. No
incluye exposicion, transito de red ni tiempo interno de decodificacion.

## Recursos

| Metrica | Secuencial | Batching | Cambio |
| --- | ---: | ---: | ---: |
| CPU media | 23.097% | 20.455% | -2.642 puntos (-11.4%) |
| Nucleo CPU p95 | 81% | 75% | -6 puntos |
| GPU media | 26.099% | 20.858% | -5.241 puntos |
| GPU p95 | 39% | 99% | +60 puntos |
| RAM media | 4850 MB | 4990 MB | +140 MB |
| RAM maxima | 4902 MB | 5081 MB | +179 MB |
| Temperatura maxima | 53.47 C | 53.94 C | +0.47 C |
| Potencia media | 6.688 W | 6.824 W | +0.136 W (+2.0%) |

La GPU trabaja en rafagas mas intensas con batching: baja el promedio, pero su
p95 llega a 99%. No hubo limite termico, falta de memoria ni errores durante
los 120 segundos. Esta ventana no demuestra estabilidad durante 24 a 72 horas.

## Decision

Batching queda implementado y disponible, pero deshabilitado por defecto para
la carga actual. A ocho camaras y 6 FPS, el secuencial ya tiene margen y ofrece
mejor latencia, mas frames unicos, menos RAM y menor potencia.

Conviene repetir esta decision si aumenta el numero de camaras, sube la
frecuencia solicitada o el throughput pasa a ser mas importante que la latencia.
Una futura prueba puede comparar batch 2 y 4 como compromiso. La Etapa 4 debe
perfilar copias, preprocesamiento y postprocesamiento antes de optimizarlos.
