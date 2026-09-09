---
name: aeye-database
description: Modificar o inspeccionar SQLite de AEYE, Repository, consultas, indices y migraciones. Usar para persistencia y calidad historica; distinguir inspeccion de solo lectura de operaciones que migran datos.
---

# Persistencia SQLite

## Mapa y efectos
`database/repository.py` gestiona conexiones y migraciones de
`database/migrations/`. `database/models.py` define modelos locales.
Leer DDL en orden: migraciones posteriores pueden reemplazar tablas anteriores.
Datos principales: occupancy_samples, incidents, workplace_settings,
anonymous_track_observations, access_events y anonymous_visits.
Tambien existen tablas de identidades; eso no demuestra que haya identificacion
habilitada ni permite inventar asociaciones empleado/camara.

**Repository(path) crea directorios y migra. Importar api.app tambien puede
actualizar workplace_settings. No son APIs de inspeccion de solo lectura.**

## Consultar sin mutar
Obtener el path efectivo de `AEYE_DB_PATH`/config, sin volcar secretos. Para una
consulta autorizada de solo lectura usar sqlite3 URI `mode=ro`, por ejemplo:
```python
from pathlib import Path
import sqlite3

path = Path(database_path).resolve()
connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
try:
    connection.execute("PRAGMA query_only = ON")
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ?", ("table",)
    ).fetchall()
finally:
    connection.close()
```
No usar `immutable=1` en una base activa con WAL ni abrir ruta inexistente en
modo normal. No copiar solo el .db activo ignorando WAL: para backup consistente
usar SQLite backup hacia un destino autorizado y verificar restauracion.
No imprimir observaciones personales o imagenes para probar una consulta.

## Cambios
1. Revisar llamadores, parametros SQL, indices y volumen esperado.
2. Agregar migracion numerada nueva; no reescribir una ya aplicada. Consultar
   `schema_migrations` y archivos, no asumir version por nombre de carpeta.
3. Probar base vacia y upgrade con datos representativos, FK, nulls, indices
   y segunda inicializacion idempotente en directorio temporal.
4. Preservar calidad, timestamps con zona y unidades. Comparar timestamps
   almacenados como texto requiere limites con convencion compatible.
5. Ajustar repository y consumers juntos; SQL parametrizado, no concatenar input.
6. No migrar produccion ni borrar historicos como parte de una prueba.

## Historicos
La sincronizacion actual de configuracion puede reinterpretar reportes antiguos;
no prometer configuracion versionada por fecha sin implementacion verificable.
Visitas anonimas se emparejan FIFO; no son duraciones por persona identificada.
Cambios de reglas temporales requieren aeye-activity, no solo una migracion.

## Verificacion
```bash
python3 -m unittest discover -s tests -p 'test_analytics.py' -v
python3 -m unittest discover -s tests -p 'test_activity_reporting.py' -v
```
Agregar pruebas de upgrade y regresion del contrato afectado. Registrar que
todas las bases usadas fueron temporales y que no se modifico la base real.
