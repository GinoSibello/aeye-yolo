---
name: aeye-review
description: Revisar cambios de AEYE con evidencia y pruebas de regresion, o evaluar la estructura de skills con contexto limpio cuando se solicita. Usar para auditoria/review; no implementar arreglos ni tocar produccion durante la revision.
---

# Revision independiente

## Metodo
Leer el alcance pedido y diff/archivos reales. Cargar solo las skills de dominios
afectados. Separar hechos demostrados, inferencias y puntos no verificados.
La revision no edita archivos, no inicia API contra datos reales, no crea
Repository de produccion, no ejecuta migraciones ni hace commits.
Solicitar al principal ejecucion aislada cuando falten herramientas/permisos;
no simular una prueba ni ampliar privilegios para completarla.

## Riesgos prioritarios de AEYE
- Muestras ausentes confundidas con cero, perdida de estados parciales.
- Turnos/medianoche/almuerzo inconsistentes entre incidente, diario y periodo.
- Track o FIFO presentado como persona identificada; vinculos entre camaras.
- Contrato API/CSV/UI roto o descargas que no corresponden al periodo visible.
- Migraciones con perdida de datos, imports con escrituras o secretos en diff.
- Batching que mezcla frames, cronologia o trackers de distintas camaras.
- Tests de strings reportados como prueba visual o FPS tomado como precision.
Consultar la skill de dominio para localizar codigo y comprobaciones.

## Revision de esta arquitectura con contexto limpio
1. El principal debe crear un agente sin historial heredado si el cliente lo
   permite; si no, declarar que la independencia de contexto es limitada.
2. Proveer tarea neutral, raiz del repo y esta skill. Leer las demas SKILL.md
   segun necesidad como unica guia de proyecto; no recibir la solucion esperada.
3. Inspeccionar codigo, adaptadores y AGENTS.md como artefactos a evaluar.
   No tratar comentarios del autor ni conversacion anterior como evidencia.
4. Verificar descubrimiento, enlaces, triggers, alcance, comandos y permisos.
   Detectar reglas falsas, redundantes, contradicciones y detalles obsoletos.
5. Resolver en seco un caso real siguiendo las skills, sin mutar el runtime.
   Citar archivos/funciones que permiten o contradicen la solucion.
El aislamiento del historial no elimina instrucciones superiores o permisos
heredados; nunca describirlo como un entorno sin reglas.

## Entrega
Hallazgos primero, ordenados por severidad, con archivo/linea, consecuencia y
forma de reproducir o verificar. Luego preguntas y riesgos residuales.
Distinguir defectos de las skills de bugs preexistentes del producto.
Si no hay hallazgos, decirlo y precisar pruebas/entornos no cubiertos.
No exigir cambios de estilo ajenos al objetivo ni reparar codigo por iniciativa
durante una revision de solo lectura.
