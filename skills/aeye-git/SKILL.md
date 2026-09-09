---
name: aeye-git
description: Preparar commits o comandos de push/pull de AEYE y diagnosticar SSH de GitHub sin filtrar secretos. Usar al publicar etapas o resolver claves de solo lectura; no autoriza push ni cambios de credenciales por si sola.
---

# Publicacion de AEYE

## Preparacion
1. Revisar git status, diff y archivos staged; preservar cambios ajenos.
2. Elegir archivos explicitos del cambio. Evitar git add . sin inspeccion.
3. Excluir cameras.json con datos locales, secretos RTSP, .env, claves,
   bases/WAL, logs, capturas, benchmarks pesados y engines. Un .gitignore
   no protege un archivo ya trackeado: revisar el diff staged.
4. Ejecutar pruebas pertinentes, proponer mensaje que describa el cambio.
5. Commit y push solo si fueron solicitados como acciones. Si el usuario
   pide comandos, entregarlos sin ejecutar la publicacion.

## SSH y remoto
No cambiar remoto, identity global o credential helper para arreglar algo sin
diagnosticar el repositorio y la clave seleccionada. Nunca imprimir claves
privadas ni pedir contrasenas/tokens en el chat.
Un error de clave read-only es de autorizacion de escritura, no del commit.
Inspeccionar SSH/remoto sin exponer secretos; comprobar si es deploy key de
lectura o clave de cuenta. Explicar opciones de clave de escritura con alcance
al repo, y clave de lectura para la Jetson. No ampliar permisos por defecto.
No borrar la SSH existente: el usuario puede conservarla entre etapas.
Validar host key; no recomendar StrictHostKeyChecking=no.

## Publicacion de instrucciones
Incluir skills/, AGENTS.md de raiz/carpeta, adaptadores .codex/agents/ y
.opencode/agents/, enlaces .agents/skills/, herramientas/tests y guia humana.
Comprobar `python3 tools/sync_agent_skills.py --check` antes del commit.
Verificar que Git conserva enlaces relativos, no copias divergentes.
No incorporar configuracion personal de ~/.codex ni ~/.config/opencode.

## Limites
No force-push, reset --hard ni reescritura de historia para resolver rechazos
normales. Revisar divergencia y pedir decision si hay trabajo incompatible.
Un commit local no despliega ni garantiza que otra maquina hizo pull.
Reportar rama/remoto y resultado real, o comandos pendientes si no se ejecutaron.
