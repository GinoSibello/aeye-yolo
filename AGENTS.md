# AEYE: instrucciones para agentes

## Proposito y limites

AEYE procesa camaras en una Jetson y ofrece reportes operativos por puesto.
La prioridad actual es recoger datos utiles y mostrar su calidad, no identificar
empleados ni adjudicar causas a ausencias. Responder al usuario en espanol.

Este archivo es el mapa del proyecto, no una especificacion completa. Leer la
skill pertinente y el codigo antes de editar. Los AGENTS.md de cada carpeta
complementan estas instrucciones dentro de su alcance; no sustituyen permisos
del entorno ni instrucciones de mayor prioridad.

## Arquitectura real

- `main.py`: coordina captura, inferencia, tracking, metricas y preview.
- `vision/`: captura, TensorRT, batching, trackers y regiones.
- `metrics/`: muestreo, incidentes, accesos y reportes diarios/semanales/mensuales.
- `database/`: SQLite, Repository y migraciones SQL numeradas.
- `api/app.py`: FastAPI; sirve consultas y el dashboard de `api/static/`.
- `preview/`: vista de camaras, distinta del dashboard de actividad.
- `tools/`: ejecucion en Jetson, benchmarks y herramientas de mantenimiento.
- `tests/`: unittest; pruebas con fixtures y bases temporales.

No asumir React, Django, PostgreSQL, un ORM, pytest o un frontend con npm.
No asumir que un modelo ganador en benchmarks sea el desplegado. Leer la
configuracion efectiva y el engine antes de afirmar versiones o prestaciones.

## Seleccion de skills

Las fuentes editables estan en `skills/`. `.agents/skills/` contiene enlaces
relativos para que Codex y OpenCode descubran las mismas instrucciones.
Los paths en las skills son relativos a la raiz del repositorio, salvo enlaces
Markdown, que son relativos al archivo. Cargar solo las skills necesarias.

| Disparador / alcance | Skill | Agente especialista |
| --- | --- | --- |
| Rutas, validacion HTTP, contratos JSON/CSV | [aeye-api](skills/aeye-api/SKILL.md) | aeye-api |
| Dashboard, preview, graficos, PNG/PDF | [aeye-web](skills/aeye-web/SKILL.md) | aeye-web |
| Frames, modelos, TensorRT, tracking, ROI | [aeye-vision](skills/aeye-vision/SKILL.md) | aeye-vision |
| SQLite, queries, migraciones, persistencia | [aeye-database](skills/aeye-database/SKILL.md) | aeye-database |
| Turnos, ocupacion, tardanzas, alertas, agregacion | [aeye-activity](skills/aeye-activity/SKILL.md) | aeye-activity |
| Docker, Jetson, rendimiento y despliegue | [aeye-jetson](skills/aeye-jetson/SKILL.md) | aeye-jetson |
| Commit, push, SSH, publicacion sin secretos | [aeye-git](skills/aeye-git/SKILL.md) | principal |
| Revision solicitada, regresiones y evidencia | [aeye-review](skills/aeye-review/SKILL.md) | aeye-review |
| Mantener esta estructura u orquestar tareas | [aeye-agents](skills/aeye-agents/SKILL.md) | principal / aeye |

Para un grafico nuevo con una metrica nueva, coordinar actividad, API y web;
no inventar el calculo en JavaScript. Para cambiar almacenamiento, sumar database.
Para cambios en `main.py`, elegir vision, activity o jetson segun el bloque.

## Invariantes del producto

- Identificador de camara estable; nombre y orden de presentacion son separados.
- Un track es local a una camara/sesion, no una identidad laboral.
- No asociar faltantes en puestos con entradas a bano o comedor.
- Conteos y cupos permiten estimaciones de plazas, no listas de personas tardias.
- Falta de muestras, cero personas y dato parcial son estados distintos.
- Explicar cobertura, tolerancias y limites al informar porcentajes o promedios.
- El cambio de turno puede conservar la misma ocupacion sin demostrar un relevo.
- La API es para red local sin login por decision del cliente. No agregar
  autenticacion ni exponerla a Internet como parte incidental de otra tarea.
- No convertir estimaciones en decisiones disciplinarias automaticas.

Los nombres, cupos y horarios operativos pertenecen a la configuracion. No
hardcodearlos en UI, queries o skills. `cameras.example.json` es un ejemplo,
no prueba del estado de las ocho camaras de produccion.

## Trabajo seguro

1. Leer `git status --short`, las instrucciones de las carpetas afectadas y el
   codigo que consume los datos. Respetar cambios existentes del usuario.
2. Delimitar archivos, contrato afectado y pruebas antes de editar.
3. Cambiar lo necesario y validar con fixtures, sin tocar el runtime activo.
4. Informar cambios, pruebas realmente ejecutadas y lo que queda sin comprobar.

`cameras.json`, secretos RTSP, claves SSH, `data/`, `logs/`, `benchmarks/`, imagenes
reales y engines son material local/sensible o generado. No pegarlos en chats,
no publicarlos ni cargarlos a servicios externos sin autorizacion especifica.
Para diagnosticar config, extraer solo campos necesarios y omitir URLs/secretos.
No usar `.orig` ni `.rej` como codigo activo.

Importar `api.app` abre la base y puede sincronizar configuracion. Crear un
`Repository` tambien ejecuta migraciones. No usarlos para inspeccion de solo
lectura de produccion. Ver la skill de base de datos.

No reiniciar contenedores, exportar engines, cambiar potencia, migrar/borrar
datos reales, hacer push o cambiar claves solo porque una skill lo mencione.
Necesitan una solicitud que incluya esa accion y los permisos del entorno.
Si falla una operacion sensible, detener reintentos y diagnosticar antes de
alterar configuracion o pedir privilegios mas amplios.

## Orquestacion

Para trabajo complejo con partes independientes, este proyecto recomienda
delegar subtareas acotadas si la herramienta y las instrucciones superiores lo
permiten. Para cambios pequenos, trabajar directamente. No delegar por rutina.

- El principal define resultado, archivos permitidos, contrato y comprobaciones.
- Cada archivo tiene un responsable de escritura a la vez, especialmente
  `main.py`, `metrics/activity.py` y `api/static/dashboard.js`.
- No asumir aislamiento de filesystem entre agentes ni crear commits paralelos.
- Los especialistas devuelven evidencia, archivos cambiados y riesgos; no amplian
  el alcance, no hacen deploy ni delegan recursivamente sin coordinacion.
- El principal integra, ejecuta pruebas cruzadas y resuelve contradicciones.
- Una revision independiente recibe una tarea neutral y contexto minimo, sin
  anticiparle el resultado esperado ni reutilizar el razonamiento del autor.

Codex usa `.codex/agents/*.toml`; OpenCode usa `.opencode/agents/*.md`.
Los adaptadores solo seleccionan skill, rol y permisos. No duplicar logica de
negocio en ellos. Si la version del cliente no admite agentes personalizados,
leer las mismas skills desde el principal; no afirmar que hubo delegacion.

## Verificacion

Desde la raiz:

```bash
python3 tools/sync_agent_skills.py --check
python3 -m unittest discover -s tests -v
```

Elegir ademas las pruebas focalizadas listadas por cada skill. Las pruebas de
texto HTML/JS no demuestran que el navegador renderice o descargue correctamente.
Una prueba unitaria tampoco demuestra FPS, precision o salud de una camara real.
Pruebas de hardware y navegacion requieren entorno y evidencia separados.

Los cambios de esquema requieren pruebas de migracion y compatibilidad; cambios
de reportes, pruebas de limites temporales y estados sin datos. Usar siempre
una base temporal para tests y configurar variables antes de importar la API.

## Mantenimiento y pendientes

Actualizar la skill afectada cuando cambie una ruta, contrato o comando.
No copiar documentacion extensa: el manual funcional, la guia breve para
agentes, las decisiones de rendimiento y los pendientes estan consolidados en
`README.md`.

La existencia de herramientas historicamente llamadas `run_stage*` no certifica
su resultado ni impone una secuencia de trabajo. Consultar la seccion de
rendimiento del README antes de retomar optimizaciones. Quedan sujetos a
solicitud futura la validacion con imagenes anotadas, DeepStream si las
mediciones lo justifican y robustez prolongada/energia/temperatura.
Calibracion ROI, versionado historico de horarios y validacion operativa son
trabajo de producto separado, no efectos de instalar agentes.
