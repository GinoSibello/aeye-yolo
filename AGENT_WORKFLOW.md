# Agentes y skills de AEYE

Esta estructura permite trabajar sin depender del historial de un chat.
No modifica el procesamiento de camaras, horarios ni datos de produccion.

## Estructura

```text
AGENTS.md                    Mapa, limites y seleccion por tarea
api/AGENTS.md                API FastAPI
api/static/AGENTS.md         Dashboard de actividad
preview/AGENTS.md            Vista de camaras
metrics/AGENTS.md            Reglas y reportes
database/AGENTS.md           Persistencia y migraciones
vision/AGENTS.md             Captura e inferencia
identity/AGENTS.md           Limites de identidad opcional
tools/AGENTS.md              Operacion y herramientas
tests/AGENTS.md              Pruebas aisladas
skills/AGENTS.md             Mantenimiento de instrucciones
skills/aeye-*/SKILL.md       Nueve fuentes canonicas
.agents/skills/aeye-*        Enlaces relativos a esas fuentes
.codex/agents/*.toml         Siete especialistas Codex
.opencode/agents/*.md        Principal aeye + siete especialistas
```

Especialidades: API, web, vision, base de datos, actividad, Jetson, Git,
revision y mantenimiento/orquestacion. Git y orquestacion son skills del
principal; no necesitan otro agente. Una skill es una guia reutilizable;
un agente es un ejecutor que puede cargarla y devolver resultados.

Adoptamos de Prowler la organizacion por alcance y carga selectiva, no su stack.
AEYE usa FastAPI, SQLite, unittest y web vanilla. El archivo raiz es breve:
250-500 lineas no es un requisito del formato ni justifica repetir informacion.

## Preparacion

Desde la raiz del repo, con Python 3.9 o posterior:

```bash
python3 tools/sync_agent_skills.py
python3 tools/sync_agent_skills.py --check
python3 -m unittest discover -s tests -p 'test_agent_structure.py' -v
```

Si faltan PyYAML o tomli, usar un entorno separado:

```bash
python3 -m venv /tmp/aeye-agent-tools
/tmp/aeye-agent-tools/bin/pip install -r requirements-agent-tools.txt
/tmp/aeye-agent-tools/bin/python tools/sync_agent_skills.py --check
```

No hace falta instalar nada en el contenedor de camaras. El sincronizador
valida YAML/TOML, rutas y permisos del revisor. Solo crea enlaces faltantes:
no borra enlaces viejos, reemplaza carpetas ni sigue padres simbolicos.
Ante conflictos informa el path para revision manual. `--check` no escribe.
Puede ejecutarse despues de un pull o antes de un commit; no instalamos hooks
ni modificamos configuracion global del usuario.

## Uso en Codex

Abrir el proyecto y comenzar una conversacion nueva. Codex descubre las skills
de `.agents/skills`; si no aparecen, reiniciar y verificar los enlaces.
Ejemplo:

```text
Usa $aeye-activity para revisar las tardanzas del turno tarde.
No modifiques produccion; agrega una prueba con datos temporales.
```

Para una tarea amplia:

```text
Agrega un filtro al reporte. Delega el contrato a aeye-api y la interfaz a
aeye-web, asignando archivos separados. Integra y pide revision a aeye-review.
```

Los especialistas estan en `.codex/agents/` usando TOML por agente. El principal
es la sesion normal de Codex, guiada por AGENTS.md. No se fijan modelos ni se
modifica `~/.codex/config.toml`. El soporte depende de la version del cliente y
las funciones habilitadas en la sesion. Si no admite roles personalizados, el
principal puede leer la misma skill o pasarsela a un subagente generico.
Crear archivos no demuestra que una sesion ya los haya cargado.

## Uso en OpenCode

Iniciar OpenCode desde la raiz y seleccionar `aeye` en el selector de agentes.
No se cambia el agente predeterminado global. Invocacion directa:

```text
@aeye-web revisa por que la descarga del reporte no produce una imagen.
```

OpenCode tambien descubre `.agents/skills`, por eso no hay otra copia en
`.opencode/skills`. Los agentes leen su SKILL.md; pueden cargarla con la
herramienta nativa `skill`. Si una version no sigue enlaces, comprobar
descubrimiento y actualizar el cliente; mientras tanto leer la fuente
explicitamente. No mantener dos versiones editables.

Los AGENTS.md de carpetas se leen al trabajar en ese alcance, incluso si el
cliente no los carga automaticamente. No cargamos todos mediante un glob.
Los especialistas no subdelegan. El revisor OpenCode permite lectura,
busqueda y skills, pero bloquea las demas herramientas. El principal ejecuta
las pruebas aisladas que requieren shell y le comunica los resultados.

## Permisos y limites

Las skills no otorgan permisos. OpenCode pide autorizacion para shell en los
agentes de trabajo; Codex conserva los permisos de la sesion. El revisor Codex
declara solo lectura, pero los overrides de la sesion pueden prevalecer.
No usar permisos globales irrestrictos suponiendo aislamiento.
Los proveedores, claves y conexiones MCP del usuario no se modifican.

No se autorizan implicitamente deploys, reinicios, migraciones reales, pushes,
cambios de SSH ni transferencias de imagenes. Las pruebas usan fixtures anonimos.
Una estimacion por puesto no demuestra identidad, motivo de ausencia ni relevo.

## Mantenimiento y evaluacion

Editar [skills](skills/AGENTS.md), no los enlaces. Actualizar el mapa
[AGENTS.md](AGENTS.md) cuando cambie el alcance. Para un agente nuevo, mantener
ambos adaptadores y ROLES en el [sincronizador](tools/sync_agent_skills.py).
Las pruebas estan en [test_agent_structure.py](tests/test_agent_structure.py).

Una revision independiente comienza sin historial de implementacion y recibe
solo la tarea y [aeye-review](skills/aeye-review/SKILL.md) como guia. Puede leer
las otras skills y contrastar codigo/archivos como evidencia. No se eliminan
las instrucciones superiores o permisos del entorno.
Los checks estructurales no sustituyen una prueba de carga en cada cliente
ni evaluan por si solos la utilidad de las instrucciones.

## Resultado de esta implementacion

La revision con contexto limpio y sus limites estan en `AGENT_REVIEW.md`.
Pasaron 69 pruebas y Codex detecto las nueve skills en una consulta local sin
credenciales. OpenCode no esta instalado aqui; su carga queda por verificar.

## Fuentes consultadas

Revisadas el 2026-09-09. La estructura y los flujos son propios de AEYE.

- [OpenCode: agentes](https://opencode.ai/docs/es/agents/): roles y permisos.
- [OpenCode: skills](https://opencode.ai/docs/skills/): descubrimiento compartido.
- [OpenCode: reglas](https://opencode.ai/docs/rules/): AGENTS.md y carga selectiva.
- [Agent Skills](https://agentskills.io/home) y [especificacion](https://agentskills.io/specification): SKILL.md.
- [Codex: skills](https://developers.openai.com/codex/skills/): .agents/skills y enlaces.
- [Codex: AGENTS.md](https://developers.openai.com/codex/guides/agents-md/): contexto por alcance.
- [Codex: subagentes](https://developers.openai.com/codex/subagents/): adaptadores TOML.
- [Prowler: AGENTS.md](https://github.com/prowler-cloud/prowler/blob/master/AGENTS.md) y [skills](https://github.com/prowler-cloud/prowler/tree/master/skills): referencia organizativa.
