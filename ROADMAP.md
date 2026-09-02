# AEYE: estado de mejoras

Esta lista resume las mejoras identificadas. "Completado" significa implementado
y cubierto por pruebas unitarias; la validacion con camaras reales debe hacerse
en la Jetson.

## Completado

- [x] **2. Estado `no_data`.** Desconexiones y fallos de inferencia generan
  muestras con conteos nulos y estado desconocido. Las consultas no los cuentan
  como cero ni como faltantes.
- [x] **3. Suavizado e histeresis.** Se usa una mediana temporal y tiempos
  configurables para confirmar incidentes y recuperaciones.
- [x] **4. Recuperacion tras reinicios.** Los incidentes heredados se cierran en
  la ultima muestra valida con `closure_reason=process_restart`; el apagado no
  agrega duracion inventada.
- [x] **7. ByteTrack.** Reemplaza el tracker por centroides. Cada camara mantiene
  su propio estado e IDs locales; TensorRT entrega caja y confianza al tracker.
- [x] **Backend unico TensorRT.** No existe seleccion ni fallback a PyTorch.
- [x] **Batching TensorRT entre camaras.** Engine FP16 dinamico batch 8,
  timeout corto, frames recientes, orden por camara y trackers independientes.
  Queda disponible pero deshabilitado segun la medicion de Etapa 3.
- [x] **Copias y conversiones del pipeline.** Snapshot compartido entre captura e
  inferencia y una sola transferencia GPU-CPU por resultado, con rutas A/B,
  metricas propias y decision documentada en la Etapa 4.
- [x] **Comparacion de modelos FP16.** YOLO11/YOLO26 nano y small en 640 y
  960x544, precision sobre 5.000 imagenes anotadas y prueba de ocho camaras.
  YOLO26s 640 queda como ganador preliminar; INT8 espera datos AEYE anotados.
- [x] **ROI por camara.** El conteo usa el centro inferior de cada track dentro
  de un poligono normalizado. Falta calibrar los poligonos con escenas reales.
- [x] **MVP de actividad anonima.** Reportes diarios de ocupacion, dotacion,
  tardanzas, salidas, tiempo extra y pausas por cupos anonimos.
- [x] **Bano y comedor sin identidad.** Se guardan tracks locales y existe
  medicion FIFO de visitas por linea de acceso. Falta ubicar las lineas reales.
- [x] **Dashboard y CSV.** FastAPI publica reportes historicos en la red local,
  configuracion efectiva y exportacion por puesto.
- [x] **Calidad auditable.** La cobertura se muestra por separado y los
  intervalos sin datos o sin configuracion no se convierten en ceros.
- [x] **Cierre de SQLite.** El repositorio libera su conexion y las pruebas pueden
  eliminar correctamente las bases temporales en Windows.

## Pendiente

- [ ] **Calibracion del MVP.** Completar nombres, dotaciones, horarios, ROI y
  lineas de acceso; contrastar conteos y eventos contra observacion humana.
- [ ] **5. Reglas versionadas y auditoria completa.** Guardar cada version de
  minimo/maximo, su vigencia, motivo del cambio y relacion con cada muestra.
- [ ] **6. Revision humana.** Crear API y pantalla para marcar incidentes como
  confirmados, falsos positivos, justificados o sin evidencia, conservando el
  historial de revisiones.
- [ ] **8. Validacion operativa TensorRT.** Medir p95, precision de conteo,
  temperatura, memoria, cobertura y estabilidad durante 24-72 horas con todas
  las camaras reales.
- [ ] **9. Identidad externa opcional.** Integrar badge, QR o RFID antes de
  habilitar tiempos individuales y transiciones de empleados.

## Etapas de optimizacion aplazadas

- [ ] **Etapa 6. Datos reales AEYE.** Anotar imagenes representativas, repetir
  precision por camara y decidir si conviene ajustar o entrenar un modelo.
- [ ] **Etapa 7. DeepStream.** Evaluarlo solamente si la validacion operativa
  demuestra que el pipeline actual limita la escala o la estabilidad.
- [ ] **Etapa 8. Energia y termica.** Probar modos de potencia y frecuencias
  despues de respaldar la Jetson y contar con acceso fisico para recuperacion.
- [ ] **INT8.** Calibrar solo con datos AEYE y aceptar el engine unicamente si
  la perdida de precision queda dentro del umbral acordado.

## Posibles mejoras posteriores

- Informes explicitos de cobertura y disponibilidad por camara.
- Alertas de camara desconectada con un umbral propio.
- Retencion automatica de muestras, logs e imagenes.
- Autenticacion y permisos para dashboard y API.
- Pruebas de integracion con streams RTSP simulados.
