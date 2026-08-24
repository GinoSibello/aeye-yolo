# AEYE — métricas y API

El motor de visión guarda una muestra de ocupación cada 5 segundos (configurable
con `system.metrics_sample_every_seconds`) y abre/cierra incidentes cuando una
zona sale o vuelve al rango esperado. La base SQLite predeterminada es
`data/aeye.db`; puede cambiarse con `AEYE_DB_PATH`.

## Consultas disponibles

La API responde las preguntas operativas en estos endpoints:

- `GET /api/analytics/understaffed-hours?zone=Caja&start=...&end=...`
- `GET /api/analytics/minutes-below-minimum?zone=Zona%20A&start=...&end=...`
- `GET /api/analytics/employee-zone-time?start=...&end=...&employee_id=EMP0042`
- `GET /api/analytics/transitions?start=...&end=...&limit=20`
- `GET /api/analytics/long-incidents?start=...&end=...&minutes=20`
- `GET /api/analytics/false-positives?start=...&end=...&minimum_reviews=10`
- `GET /api/analytics/occupancy-by-hour?start=...&end=...&zone=Caja`

Los intervalos son semiabiertos: `start` se incluye y `end` no. Usar timestamps
ISO 8601 con zona horaria, por ejemplo `2026-08-10T00:00:00-03:00`.

Iniciar la API dentro del contenedor:

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

La documentación interactiva queda en `http://IP_JETSON:8000/docs`.

## Límites de interpretación

El tiempo por empleado y las transiciones solo se generan después de integrar
una evidencia explícita de identidad (badge, QR, ArUco, RFID, UWB o control de
acceso). Un track visual no se considera una identidad.

La tasa de falsos positivos usa `detection_reviews`. Sin detecciones revisadas
por una persona o una fuente de verdad externa, el endpoint devuelve una lista
vacía; no inventa una tasa a partir de la confianza de YOLO.

Los minutos bajo el mínimo se integran entre muestras consecutivas. Por ello,
la precisión temporal depende de `metrics_sample_every_seconds` y de la
continuidad de la cámara.
