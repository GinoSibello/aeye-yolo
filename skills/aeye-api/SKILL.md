---
name: aeye-api
description: Modificar o diagnosticar FastAPI de AEYE, rutas de reportes, validacion HTTP y contratos JSON/CSV. Usar para api/app.py y consumidores; no para calcular nuevas metricas ni cambiar solo estilos.
---

# API de AEYE

## Alcance
`api/app.py` sirve FastAPI, `/assets` y el dashboard en `/`.
Las consultas de actividad estan en `/api/reporting/configuration` y
`/api/reports/daily`, `weekly`, `monthly`, ademas de `daily.csv`.
Las consultas historicas `/api/analytics/*` pertenecen a `metrics/analytics.py`.
`api/alert_evidence.py` sirve listados, manifiestos publicos y JPEG declarados
por manifiesto bajo `/api/alert-evidence`; no acepta rutas del cliente.
Verificar firmas en el archivo antes de usar parametros; no inventar endpoints.

## Flujo
1. Leer el handler y su consumidor en `api/static/dashboard.js`.
2. Seguir la llamada a `ActivityAnalytics` o `WeeklyActivityAnalytics`; mantener
   calculos en metrics y acceso SQL en repository o consultas existentes.
3. Mantener nombres de campos, unidades, fechas, valores null y estados de
   cobertura. Una metrica nueva requiere definir contrato antes del frontend.
4. Validar fechas, limites y errores HTTP; no filtrar trazas, RTSP o secretos.
5. Probar JSON y CSV con datos vacios, parciales y completos. Cambios de contrato
   requieren tambien las skills aeye-activity y aeye-web segun el alcance.

## Inicio con efectos secundarios
Importar `api.app` crea un Repository, ejecuta migraciones y, si hay camaras,
sincroniza configuracion. **No importar contra la base real para explorar.**
Para pruebas, definir `AEYE_CONFIG` con un JSON temporal sin secretos y
`AEYE_DB_PATH` con una base temporal ANTES del import, preferentemente en un
subproceso aislado. Evitar que el cache de imports reutilice otro repository.
`/api/health` comprueba una consulta SQLite; no certifica captura ni inferencia.

## Contrato operativo
La API es accesible en LAN sin usuario/contrasena por decision actual del cliente.
No agregar login, CORS abierto ni publicacion externa incidentalmente.
No adjudicar identidades: endpoints antiguos de empleados no significan que
existan identidades confiables en los reportes anonimos.
Respetar zona horaria configurada; no asumir UTC ni usar fecha del navegador
como sustituto de los limites laborales.

## Verificacion
```bash
python3 -m unittest discover -s tests -p 'test_activity_reporting.py' -v
python3 -m unittest discover -s tests -p 'test_analytics.py' -v
python3 -m unittest discover -s tests -p 'test_alert_evidence_api.py' -v
```
Estas pruebas cubren calculos, no son pruebas HTTP completas. Para cambios de
handlers agregar solicitudes reales a una instancia aislada con fixtures;
comprobar status, cuerpo, Content-Type y CSV. No iniciar otra API contra produccion.
