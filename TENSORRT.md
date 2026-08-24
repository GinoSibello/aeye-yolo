# AEYE: PyTorch vs TensorRT

AEYE ahora tiene dos funciones de inferencia con la misma salida:

- `vision.detector.detect_yolo`: carga y ejecuta `yolov8n.pt` como hasta ahora.
- `vision.detector.detect_tensorrt`: carga y ejecuta `yolov8n.engine` con TensorRT.

El backend se elige en `cameras.json`:

```json
"inference_backend": "pytorch"
```

o:

```json
"inference_backend": "tensorrt"
```

## 1. Construir la imagen

```bash
cd ~/aeye-yolo
sudo docker build -t aeye-yolo:dev .
```

La imagen base NVIDIA ya contiene CUDA y TensorRT. El engine debe exportarse
en la Jetson y dentro de esta misma imagen: los `.engine` no son portables entre
distintas GPU, versiones de TensorRT ni, en general, entornos CUDA diferentes.

## 2. Exportar una vez a TensorRT FP16

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

El resultado esperado es `yolov8n.engine` en el proyecto. FP16 es la opción
recomendada inicialmente para Orin. Para exportar FP32:

```bash
python3 tools/export_tensorrt.py --fp32
```

Ultralytics 8.4 usa `quantize=16` para FP16 y requiere el módulo ONNX de
NVIDIA ModelOpt. Esas dependencias ya se instalan en el Dockerfile. Como la
imagen usa CUDA 13, también se instala `cupy-cuda13x`.

No se activa INT8 todavía: requiere un dataset de calibración representativo y
una comparación de precisión antes de usarlo en staffing.

## 3. Ejecutar cada backend

PyTorch:

```json
"inference_backend": "pytorch"
```

TensorRT:

```json
"inference_backend": "tensorrt"
```

Después se usa el mismo `./run.sh`. En la terminal aparecerá, según el caso:

```text
Backend activo: pytorch
```

o:

```text
Backend activo: tensorrt
```

El estado `/state.json` también incluye `inference_backend` e `inference_ms`.

## 4. Comparación controlada

Usar la misma imagen, confianza, resolución, calentamiento y cantidad de
repeticiones para ambos formatos:

```bash
python3 tools/benchmark_detector.py prueba.jpg --backend pytorch --warmup 20 --runs 200
python3 tools/benchmark_detector.py prueba.jpg --backend tensorrt --warmup 20 --runs 200
```

El script informa media, percentil 95, mínimo y FPS teórico. El FPS teórico es
solo de inferencia sobre una imagen; no incluye RTSP, tracking, preview ni ocho
cámaras. Para la comparación real observar también `inference_ms` durante una
prueba larga con las mismas cámaras.

## Reglas importantes

- Si cambia `imgsz`, hay que volver a exportar el engine.
- Si se actualizan TensorRT, CUDA, JetPack o la imagen Docker, regenerar el engine.
- No copiar un engine construido en una computadora x86 a la Jetson.
- Con un engine fijo se usa `rect=False` para alimentar siempre la forma 640x640.
- Mantener `yolov8n.pt`: es la fuente del export y el backend de referencia.

## Dataset de 20 imágenes desde Internet

Dentro del contenedor con `bash`, descargar fotografías desde Wikimedia Commons:

```bash
python3 tools/download_people_images.py --count 20
```

Los archivos quedan en `test_images/people/` y `manifest.csv` conserva fuente,
autor y licencia. Revisar visualmente el conjunto: la búsqueda textual no
garantiza que todas las personas sean claras ni constituye ground truth.

Comparar ambos backends sobre toda la carpeta:

```bash
python3 tools/benchmark_detector.py test_images/people --backend pytorch --warmup 20 --runs 20
python3 tools/benchmark_detector.py test_images/people --backend tensorrt --warmup 20 --runs 20
```
