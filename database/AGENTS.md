# Alcance: persistencia
Leer [aeye-database](../skills/aeye-database/SKILL.md).
- Constructor Repository migra; inspeccion real requiere conexion mode=ro.
- No modificar migraciones ya aplicadas ni editar base real para tests.
- Probar upgrade con datos, nueva instalacion e idempotencia.
- Configuracion actual no equivale a configuracion historica versionada.
