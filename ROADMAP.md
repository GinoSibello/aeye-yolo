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
- [x] **Cierre de SQLite.** El repositorio libera su conexion y las pruebas pueden
  eliminar correctamente las bases temporales en Windows.

## Pendiente

- [ ] **1. Regiones de interes por camara.** Definir poligonos para contar solo
  personas dentro de la zona operativa correspondiente.
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

## Posibles mejoras posteriores

- Informes explicitos de cobertura y disponibilidad por camara.
- Alertas de camara desconectada con un umbral propio.
- Retencion automatica de muestras, logs e imagenes.
- Autenticacion y permisos para dashboard y API.
- Pruebas de integracion con streams RTSP simulados.
