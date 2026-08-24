# AEYE: metricas y API

El motor de vision guarda una muestra cada 5 segundos, configurable mediante
`system.metrics_sample_every_seconds`. Los incidentes se abren o cierran solo
despues de que la histeresis confirma que una zona salio o regreso al rango.
La base SQLite predeterminada es `data/aeye.db`; puede cambiarse con
`AEYE_DB_PATH`.

Cada muestra distingue `data_status=valid` de `data_status=no_data` y conserva
`raw_people_count` junto con el conteo suavizado `people_count`. Las consultas de
dotacion excluyen periodos sin datos. Una desconexion nunca equivale a cero
personas.

## Consultas disponibles

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

La documentacion interactiva queda en `http://IP_JETSON:8000/docs`.

## Limites de interpretacion

El tiempo por empleado y las transiciones solo se generan despues de integrar
una evidencia explicita de identidad como badge, QR, RFID o control de acceso.
Un track visual no se considera una identidad.

La tasa de falsos positivos usa `detection_reviews`. Sin detecciones revisadas
por una persona o una fuente externa, el endpoint devuelve una lista vacia.

Los minutos bajo el minimo se integran solamente entre muestras validas
consecutivas. La precision depende de `metrics_sample_every_seconds` y de la
continuidad de la camara. Un incidente abierto al reiniciar se cierra en su
ultima muestra valida con `closure_reason=process_restart`.
