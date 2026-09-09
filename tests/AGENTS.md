# Alcance: pruebas
Elegir la skill del dominio probado; seguir unittest y fixtures existentes.
- Bases temporales, config sin secretos y tiempo explicito con timezone.
- No importar api.app sin aislar config/base ni iniciar captura real.
- Tests estructurales de UI no certifican navegacion/descarga.
- Tests simulados de vision no certifican engine, FPS ni precision.
- Para test_agent_structure.py cargar aeye-agents.
