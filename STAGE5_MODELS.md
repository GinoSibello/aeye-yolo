# ETAPA 5: comparacion de modelos y resoluciones

Esta etapa compara modelos nano y small con precision real y costo de ejecucion
en la Jetson. La seleccion se hizo primero en FP16. No se genero ningun engine
INT8 porque todavia falta medir la perdida de precision con anotaciones del
dominio de las camaras AEYE.

## Alcance

Se exportaron y validaron ocho engines TensorRT fijos, batch 1:

- YOLO11n y YOLO26n;
- YOLO11s y YOLO26s;
- 640x640 y 960x544 para cada modelo;
- FP16, sin perfil dinamico.

Los ocho engines se pudieron compilar y deserializar en la Jetson. Los YOLO26
usan la salida end-to-end incluida en el modelo; los YOLO11 conservan el
postprocesamiento NMS de Ultralytics. La forma rectangular se expresa como
`[alto, ancho]` en AEYE, por lo que 960x544 se configura como `[544, 960]`.

Ultralytics documenta las familias
[YOLO11](https://docs.ultralytics.com/models/yolo11/) y
[YOLO26](https://docs.ultralytics.com/models/yolo26/), asi como la exportacion
[TensorRT](https://docs.ultralytics.com/integrations/tensorrt/).

## Dataset y metodo

La evaluacion usa las 5.000 imagenes reales y anotadas de COCO 2017 val. Para
la clase persona contiene 10.777 instancias. Se mide:

- precision, recall, mAP50 y mAP50-95 con el matching oficial de Ultralytics;
- precision y recall operativos a confianza 0,1 e IoU 0,5;
- MAE, RMSE, sesgo y tasa de conteo exacto por imagen;
- preprocesamiento, inferencia y postprocesamiento por imagen;
- CPU, GPU, RAM, potencia y temperatura mediante `tegrastats`.

COCO permite comparar arquitecturas con verdad terreno, pero no representa los
angulos, distancias, oclusiones, iluminacion ni densidad de las camaras AEYE.
Por eso el ganador es preliminar. La seleccion operacional final requiere una
muestra anotada de cada camara en la Etapa 6.

Preparacion y ejecucion reproducibles:

```bash
tools/export_stage5_engines.sh
tools/prepare_coco_val.sh
tools/run_stage5_accuracy.sh
```

Los modelos, engines, dataset y resultados se excluyen de Git. En esta Jetson
ocupan aproximadamente 305 MiB, 1,3 GiB y 3,4 MiB, respectivamente.

## Resultados FP16

El presupuesto secuencial teorico para ocho camaras a 6 FPS es 20,83 ms por
imagen. El tiempo de pipeline suma preprocesamiento, inferencia y
postprocesamiento medidos por Ultralytics.

| Engine | mAP50-95 | P@0,1 | R@0,1 | MAE conteo | Pipeline | Cumple |
| --- | ---: | ---: | ---: | ---: | ---: | :---: |
| YOLO11n 640 | 0,5183 | 0,5321 | 0,7696 | 1,227 | 12,42 ms | Si |
| YOLO11n 960x544 | 0,5275 | 0,5197 | 0,7921 | 1,374 | 15,94 ms | Si |
| YOLO11s 640 | 0,5780 | 0,5631 | 0,8283 | 1,192 | 16,16 ms | Si |
| YOLO11s 960x544 | 0,5869 | 0,5507 | 0,8421 | 1,304 | 20,25 ms | Si, sin margen |
| YOLO26n 640 | 0,5125 | 0,6152 | 0,7383 | 0,831 | 10,66 ms | Si |
| YOLO26n 960x544 | 0,5251 | 0,5978 | 0,7574 | 0,890 | 14,11 ms | Si |
| YOLO26s 640 | 0,5936 | 0,6178 | 0,8205 | 0,910 | 16,37 ms | Si |
| YOLO26s 960x544 | 0,5967 | 0,6055 | 0,8299 | 0,997 | 21,42 ms | No |

La resolucion 960x544 mejora mAP50-95 entre 0,0031 y 0,0126 segun el modelo,
pero empeora el MAE de conteo entre 7,1% y 12,0% y aumenta el costo entre 25,3%
y 32,4%. En YOLO26s la ganancia de mAP es solo 0,0031 y la variante rectangular
excede el presupuesto.

YOLO26n 640 es el candidato de bajo costo: tiene el menor pipeline, 10,66 ms, y
el menor MAE, 0,831, pero pierde recall. YOLO26s 640 es el candidato equilibrado:
obtiene casi el mejor mAP de toda la matriz, la mayor precision operativa, buen
recall y mantiene 4,47 ms de margen teorico.

Resultados locales completos:

```text
benchmarks/stage5_exports_20260827_135302.json
benchmarks/stage5_20260827_145408/stage5_summary.json
```

## Validacion con ocho camaras

El candidato YOLO26s 640 se probo durante 120 segundos con ocho streams reales,
FFmpeg, 6 FPS solicitados por camara, batch 1, preview apagado y las
optimizaciones de Etapa 4. El runner usa una configuracion temporal y no
modifica `cameras.json`:

```bash
tools/run_stage5_operational.sh 120
```

| Metrica | YOLO26s 640 |
| --- | ---: |
| FPS unicos promedio por camara | 5,695 |
| FPS unicos minimo por camara | 5,535 |
| Inferencia promedio / p95 | 11,623 / 11,850 ms |
| Detector completo promedio / p95 | 18,754 / 20,218 ms |
| Captura a resultado p95 | 168,552 ms |
| Errores de proceso / conexion | 0 / 0 |
| GPU promedio / p95 | 46,5% / 70,0% |
| RAM promedio / maxima | 3.956 / 4.003 MiB |
| Potencia promedio / maxima | 7,91 / 8,88 W |
| Temperatura maxima | 55,2 C |

El benchmark anterior de YOLOv8n optimizado obtuvo 5,502 FPS unicos promedio
por camara y 246,910 ms de captura a resultado p95, pero esa corrida tuvo mas
duplicados y una camara con jitter severo. La diferencia entre corridas no es
una prueba causal de mejora en latencia. Si se necesita una comparacion estricta
se debe repetir en orden alternado ABBA bajo condiciones estables.

Resultado local:

```text
benchmarks/stage5_operational_yolo26s_640_20260827_151402/
```

## Decision

El ganador preliminar es `yolo26s_fp16_640x640.engine`. No se modifica
automaticamente `cameras.json`: primero se debe completar la validacion
anotada por camara de la Etapa 6. Para una prueba controlada se puede usar:

```json
"tensorrt_engine": "models/stage5/yolo26s_fp16_640x640.engine",
"imgsz": 640
```

YOLO26n 640 queda como alternativa cuando se priorice margen de rendimiento,
consumo o menor sobreconteo por encima del recall.

## Politica INT8

INT8 queda bloqueado por diseño. La documentacion de exportacion
[TensorRT de Ultralytics](https://docs.ultralytics.com/integrations/tensorrt/)
requiere datos de calibracion representativos. Antes de habilitarlo se debe:

1. anotar imagenes representativas de cada camara y condicion operativa;
2. establecer el resultado FP16 del ganador como baseline;
3. calibrar INT8 con un conjunto separado y representativo;
4. comparar mAP, precision, recall, MAE, falsos incidentes y estabilidad del
   tracker contra FP16;
5. aceptar INT8 solo si la perdida queda dentro de un umbral acordado.

COCO no es suficiente para calibrar ni aprobar INT8 en este sistema.

## Limites

- COCO evalua personas en fotografias generales, no ocupacion por zona AEYE.
- El umbral 0,1 favorece recall para ByteTrack y produce sobreconteo en imagenes
  aisladas; debe calibrarse junto con el tracker y las reglas temporales.
- El conteo por imagen no mide continuidad de IDs ni incidentes falsos.
- La prueba operativa de 120 segundos no sustituye una corrida de 24 a 72 horas.
- No hay evidencia suficiente para automatizar decisiones laborales; siempre se
  requiere revision humana y metricas auditables.
