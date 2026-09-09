---
name: aeye-vision
description: Cambiar o perfilar captura, inferencia Python/YOLO/TensorRT, batching, trackers y ROI en vision y main.py. Usar para FPS, latencia o precision; no confundir deteccion de personas con identidad.
---

# Pipeline de vision

## Mapa
`main.py` coordina; `vision/capture.py` obtiene frames;
`detector.py` carga/valida engine y convierte resultados; `batching.py`
agrupa; `tracker.py` mantiene tracks; `regions.py` aplica geometria;
`pipeline.py` configura transferencias/snapshots.
Leer llamadores y tests: no sustituir APIs locales por ejemplos genericos YOLO.

## Invariantes
- Engine TensorRT requerido en el flujo de inferencia actual. Verificar
  `read_engine_capabilities` y `validate_engine_for_batching`; no introducir
  fallback silencioso a CPU/PyTorch.
- Usar frames recientes y timeout corto, evitar colas ilimitadas.
- Preservar correspondencia camara/frame/resultado al agrupar y desagrupar.
- Tracker independiente por camara, secuencia cronologica y manejo de reconexion.
  ByteTrack y sus IDs no identifican empleados ni unen distintas camaras.
- Snapshots compartidos no deben mutarse desde dibujo/preview o preprocesado.
- Conservar timestamps y estados invalidos hasta las metricas. Una falla de
  inferencia no equivale a cero personas.
- ROI y lineas tienen coordenadas normalizadas; comprobar convencion geometrica
  y direccion de cruce con fixtures antes de calibrar sobre imagenes reales.
- Verificar orden ancho/alto en `normalize_image_size`, engine y preprocesado;
  la etiqueta 960x544 no define por si sola el orden del tensor.

## Medir antes de optimizar
Leer el STAGE pertinente, config efectiva y metadatos de engine sin revelar RTSP.
Medir por camara y agregado: FPS utiles, antiguedad del frame, latencia,
descartes, pre/postprocesado, CPU/GPU/memoria y temperatura cuando disponible.
No inferir una mejora de precision a partir de FPS ni de un benchmark sintetico.
FP16 primero; INT8 requiere comparacion de precision con imagenes anotadas.
Exportar engines o ejecutar benchmarks con camaras reales puede competir con el
servicio. Coordinar ventana operativa mediante aeye-jetson; no hacerlo por rutina.

## Verificacion
```bash
python3 -m unittest discover -s tests -p 'test_detector.py' -v
python3 -m unittest discover -s tests -p 'test_batching.py' -v
python3 -m unittest discover -s tests -p 'test_tracker.py' -v
python3 -m unittest discover -s tests -p 'test_capture.py' -v
python3 -m unittest discover -s tests -p 'test_pipeline.py' -v
python3 -m unittest discover -s tests -p 'test_regions.py' -v
```
Las pruebas simuladas no validan el engine en esta Jetson. Reportar por separado
pruebas de logica y mediciones de hardware con configuracion reproducible.
