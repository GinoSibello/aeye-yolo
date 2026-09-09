# Alcance: API
Leer [aeye-api](../skills/aeye-api/SKILL.md) al cambiar handlers o contratos.
Para api/static, aplicar ademas sus instrucciones de web.
- api.app tiene efectos de importacion sobre SQLite: aislar AEYE_CONFIG y
  AEYE_DB_PATH antes de importar en tests.
- Calculos laborales pertenecen a metrics; no duplicarlos en handlers.
- Conservar contratos JSON/CSV y estados sin cobertura.
- No agregar autenticacion ni cambiar exposicion de red incidentalmente.
