---
name: aeye-agents
description: Mantener AGENTS.md, skills y adaptadores Codex/OpenCode de AEYE, o coordinar una tarea compleja entre sus especialistas. Usar para instrucciones y orquestacion; no cargar todas las skills en tareas pequenas.
---

# Arquitectura de agentes AEYE

## Contexto minimo
AEYE es Python en Jetson: main.py coordina vision/ y metrics/; database/ es SQLite;
api/app.py sirve FastAPI y api/static/ es web vanilla; preview/ es otra interfaz.
El producto reporta actividad anonima por puesto, no identidades ni asociaciones
puesto-bano/comedor. No tocar produccion al mantener estas instrucciones.

## Seleccion y delegacion
Elegir por responsabilidad: aeye-api (HTTP), aeye-web (interfaces/exportacion),
aeye-vision (frames/inferencia), aeye-database (persistencia), aeye-activity
(reglas/reportes), aeye-jetson (operacion), aeye-git (publicacion),
aeye-review (auditoria). Estas skills estan en skills/NOMBRE/SKILL.md.
No iniciar una cadena de agentes para una edicion sencilla.
Si hay trabajo independiente y la sesion permite subagentes, el principal
asigna objetivo, archivos exclusivos, contratos, pruebas y resultado esperado.
Especialistas no delegan recursivamente ni compiten editando un mismo archivo.
El principal integra y verifica el conjunto; agente revisor no escribe.
Respetar instrucciones superiores sobre si/cuando esta permitida la delegacion.

## Fuente unica y adaptadores
Editar skills/ como fuente canonica; .agents/skills/ solo descubre enlaces.
AGENTS.md raiz enruta; los de carpeta explican alcance, no repiten manuales.
OpenCode: .opencode/agents/aeye.md principal y agentes especialistas .md.
Codex: .codex/agents/*.toml especialistas; el principal es la sesion normal.
Los adaptadores apuntan a skills; no fijan modelo, credenciales ni permisos de
produccion. Skills son instrucciones, no una barrera de seguridad.
El revisor OpenCode bloquea bash/edicion/task; usa lectura/busqueda.
Codex declara sandbox read-only, sujeto a overrides reales de la sesion.

## Mantener
1. Verificar codigo y documentacion oficial de la herramienta afectada.
2. Agregar skill solo si reduce redescubrimiento real. Frontmatter YAML con
   name y description: nombre unico kebab-case, igual a carpeta, hasta 64
   caracteres; descripcion especifica hasta 1024 caracteres con trigger.
3. Body breve con alcance, flujo y comprobaciones. Referencias largas solo bajo
   demanda; no copiar manuales ni crear carpetas vacias.
4. Actualizar tabla raiz y AGENTS de alcance al cambiar responsabilidades.
5. Si corresponde nuevo agente, agregar ambos adaptadores y su asignacion en
   tools/sync_agent_skills.py. No duplicar skills por cliente.
6. Sincronizar y validar. El script no borra ni pisa destinos conflictivos:
```bash
python3 tools/sync_agent_skills.py
python3 tools/sync_agent_skills.py --check
python3 -m unittest discover -s tests -p 'test_agent_structure.py' -v
```
El chequeo estructural no prueba que un cliente haya cargado un agente ni que
una instruccion sea verdadera. Confirmar descubrimiento en nueva sesion.

## Evaluacion
Para cambios sustanciales, usar aeye-review con contexto limpio y tarea neutral.
Mientras revisa, el principal puede comprobar links/tests sin editar los mismos
archivos. Corregir hallazgos, repetir checks y documentar limites.
Guia funcional y uso de la estructura: [README.md](../../README.md).
