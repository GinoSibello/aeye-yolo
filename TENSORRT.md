# AEYE: inferencia TensorRT

AEYE usa exclusivamente un engine TensorRT para la deteccion de personas. El
archivo predeterminado es `yolov8n.engine` y puede cambiarse en `cameras.json`:

```json
"tensorrt_engine": "yolov8n.engine"
```

## Decision de arquitectura

El proyecto tuvo inicialmente dos caminos de inferencia: PyTorch y TensorRT.
PyTorch sirvio como implementacion de referencia durante el desarrollo y para
comparar resultados. Despues de las pruebas sobre la Jetson se decidio retirar
ese backend y adoptar TensorRT como unico runtime por su mejor rendimiento.

Esto significa que AEYE:

- no acepta `inference_backend` en la configuracion;
- no carga pesos `.pt` durante la ejecucion;
- no exporta engines desde el contenedor de produccion;
- falla al arrancar si el `.engine` configurado no existe;
- informa siempre `tensorrt` en el estado y los benchmarks.

La imagen base conserva el entorno NVIDIA que ya fue validado con Ultralytics.
Su nombre puede incluir componentes del ecosistema de entrenamiento, pero AEYE
no ofrece ni ejecuta un camino de inferencia PyTorch. Migrar a carga nativa con
la API de TensorRT seria un cambio independiente que exige validar preprocesado,
bindings, NMS y compatibilidad del engine en la Jetson.

## Preparar el engine

El engine debe generarse fuera del runtime de AEYE, en la Jetson de destino y
con el mismo `imgsz` configurado. Luego se copia a la raiz del proyecto con el
nombre indicado por `tensorrt_engine`.

Un engine no se debe copiar entre equipos o entornos diferentes. Hay que
regenerarlo cuando cambia alguno de estos elementos:

- GPU o modelo de Jetson;
- JetPack, CUDA o TensorRT;
- imagen Docker;
- resolucion `imgsz`;
- arquitectura o version del modelo YOLO.

## Engine para batching

El engine `yolov8n.engine` original es FP16 fijo con batch 1. Etapa 3 genero y
valido `yolov8n_batch8.engine`, FP16 dinamico con maximo batch 8 y forma optima
`(8, 3, 640, 640)`. Se puede regenerar en la Jetson con:

```bash
tools/export_batch_engine.sh yolov8n.pt yolov8n_batch8.engine 8 640
```

El script usa la imagen Docker en un contenedor temporal, instala ahi las
dependencias de exportacion, compila el engine y deserializa su perfil para
validarlo. Los pesos y engines permanecen excluidos de Git.

Para probarlo:

```json
"tensorrt_engine": "yolov8n_batch8.engine",
"batching": {
  "enabled": true,
  "max_batch_size": 8,
  "timeout_ms": 10
}
```

AEYE rechaza al arrancar engines con otra resolucion, batch insuficiente o forma
fija cuando batching esta habilitado. La prueba de ocho camaras a 6 FPS redujo
la inferencia por imagen, pero aumento la latencia p95; por eso batch 1 sigue
siendo el valor operativo recomendado. Ver [STAGE3_BATCHING.md](STAGE3_BATCHING.md).

## Modelos de Etapa 5

La matriz FP16 comparo YOLO11n, YOLO11s, YOLO26n y YOLO26s con engines fijos
batch 1 en 640x640 y 960x544. AEYE admite una forma cuadrada como entero y una
forma rectangular como lista `[alto, ancho]`:

```json
"tensorrt_engine": "models/stage5/yolo26s_fp16_640x640.engine",
"imgsz": 640
```

Para un engine 960x544 se usa `"imgsz": [544, 960]`. El ganador preliminar es
YOLO26s FP16 640: obtuvo mAP50-95 de persona 0,5936 sobre COCO val, MAE de
conteo 0,910 y sostuvo las ocho camaras sin errores. La configuracion activa no
se cambia hasta validarlo con imagenes anotadas de las camaras AEYE. Ver
[STAGE5_MODELS.md](STAGE5_MODELS.md).

INT8 no debe exportarse todavia. Primero hay que establecer el baseline FP16,
calibrar con imagenes representativas separadas y verificar la perdida de
precision, recall, conteo e incidentes.

## Ejecutar

El arranque normal no requiere seleccionar backend:

```bash
./run.sh
```

La terminal debe mostrar:

```text
Cargando engine TensorRT...
Backend activo: tensorrt batching=False batch_max=1
```

`/state.json` incluye `inference_backend: "tensorrt"` e `inference_ms`.

## Benchmark

Para una imagen:

```bash
python3 tools/benchmark_detector.py prueba.jpg --warmup 20 --runs 200
```

Para todas las imagenes de una carpeta:

```bash
python3 tools/benchmark_detector.py test_images/people --warmup 20 --runs 20
```

El script informa media, percentil 95, minimo y FPS teorico. El FPS teorico solo
mide inferencia; no incluye RTSP, tracking, preview ni el reparto entre camaras.
Para una validacion real tambien hay que observar `inference_ms`, temperatura,
consumo, desconexiones y conteos durante una prueba prolongada con todas las
camaras.

Las imagenes del dataset auxiliar pueden descargarse con:

```bash
python3 tools/download_people_images.py --count 20
```

El benchmark no mide precision si las imagenes no poseen anotaciones manuales.
