---
name: aeye-activity
description: Definir o cambiar metricas anonimas de AEYE por puesto y periodo, turnos, cupos, almuerzo, tardanzas, salidas y alertas. Usar en metrics y configuracion; no identificar empleados ni vincular bano/comedor con puestos.
---

# Metricas de actividad anonima

## Flujo de datos
`metrics/reporting_config.py` normaliza opciones globales/por camara y sincroniza
workplace_settings; `staffing.py` maneja incidentes; `recorder.py` registra;
`access.py` trata cruces/visitas; `activity.py` produce reporte diario;
`weekly.py` agrega semana y mes. `analytics.py` mantiene otras consultas.
Leer los consumidores de una medida antes de cambiar su definicion.

## Configuracion y semantica
Configuracion operativa en cameras.json, ejemplo publico en cameras.example.json.
Leer solo los campos necesarios. No duplicar secretos ni fijar en codigo nombres,
cupos, horarios o el orden de montajes. ID estable, display_order y nombre tienen
propositos distintos. El rol distingue workstation, restroom, dining y other.
La solicitud vigente usa dos turnos y areas especiales; validar datos efectivos,
no asumir que el ejemplo representa todas las camaras.

- `shifts[]` convive con el formato anterior `shift`/`meal`; revisar la
  precedencia de overrides globales y por camara, no solo campos aplanados.
- Fin 00:00 corresponde al dia siguiente cuando el turno cruza medianoche.
  Respetar workdays, zona horaria y pertenencia al dia laboral.
- Almuerzo solo donde este configurado. No inventar pausa para otro turno.
- Cupo simultaneo no es cantidad de personas unicas ni suma de plazas de turnos.
- Tardanzas/salidas se estiman por plazas faltantes y ventanas observadas.
  Con dos presentes al relevo no puede probarse que llego el segundo equipo.
- El diario calcula el dia actual solo hasta la hora real y expone
  `not_started`, `in_progress` o `complete` por turno; un evento futuro usa
  `pending`, no ausencia de datos ni ausencia de personas.
- Acceso al bano y comedor se analiza de forma anonima e independiente.
  FIFO o track visible no prueba duracion individual ni puesto de procedencia.

## Antes de aceptar una metrica
Definir numerador, denominador, unidad, rango temporal, cobertura y tolerancia.
No promediar porcentajes sin revisar su ponderacion por tiempo/cupo.
Distinguir cero, null, dato parcial, intervalo sin muestras y periodo sin turno.
Revisar `build_intervals`, recorte de ventanas y max_sample_gap_seconds:
no rellenar una desconexion larga como ausencia de trabajadores.
Cruzar reglas de pausa con calculo de ocupacion y alertas; no asumir que toda
funcion excluye automaticamente almuerzo o huecos entre turnos.
Verificar que estados parciales del diario no desaparezcan al agregar semana/mes.
Estos son puntos de control, no afirmaciones de que ya esten resueltos.

## Flujo de cambio
1. Precisar la pregunta del encargado y lo que los datos realmente observan.
2. Trazar configuracion -> muestras/incidentes -> diario -> periodo -> API -> UI.
3. Escribir fixtures de tiempos exactos con timezone y datos completos/parciales.
4. Cambiar la capa responsable; coordinar aeye-database/API/web si cambia contrato.
5. Documentar limites. No borrar ni recalcular silenciosamente datos historicos.

## Verificacion
```bash
python3 -m unittest discover -s tests -p 'test_activity_reporting.py' -v
python3 -m unittest discover -s tests -p 'test_staffing.py' -v
python3 -m unittest discover -s tests -p 'test_activity_audit.py' -v
```
Cubrir medianoche, relevo, dos turnos, almuerzo, no laborable, cupo cero/sin
configurar, camara offline, inicio tardio de captura, overrides y periodos
parciales. Las estimaciones no habilitan atribucion personal ni sanciones
automaticas. Cambios de horarios historicos requieren versionado explicito.
