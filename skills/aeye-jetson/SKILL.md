---
name: aeye-jetson
description: Operar o diagnosticar AEYE en Jetson y Docker, medir rendimiento, recuperar servicio y preparar despliegues. Usar para run.sh, Dockerfile y benchmarks; no reiniciar ni cambiar hardware sin autorizacion de esa accion.
---

# Operacion y rendimiento en Jetson

## Entradas verificables
`run.sh` crea/inicia el contenedor; `tools/start_runtime.sh` arranca
`main.py` y uvicorn. Leer ambos antes de dar comandos: un contenedor existente
no se recrea ni actualiza automaticamente al invocar run.sh.
AEYE_CONTAINER_NAME selecciona el nombre (default aeye-runtime).
AEYE_CAMERA_PASSWORD_FILE apunta al secreto montado en solo lectura.
AEYE_API_HOST/AEYE_API_PORT controlan API (defaults 0.0.0.0:8000).
No asumir IP de la Jetson, estado del preview ni version de driver.
`tools/systemd/aeye-http.socket` y `.service` pueden publicar el dashboard en
puerto 80 mediante `systemd-socket-proxyd`; Preview sigue en loopback. Validar
las unidades antes de instalarlas y no habilitarlas sin permiso del host.

## Diagnostico gradual
1. Estado de git/config sin secretos y procesos/contenedores relevantes.
2. Consultar estado, restart policy y mounts con campos seleccionados de inspect;
   no volcar todo el entorno. Logs pueden contener URLs: redactar antes de compartir.
3. Separar salud HTTP, base de datos, frames recientes, inferencia y calidad.
4. Revisar JetPack/L4T, CUDA, TensorRT y engine antes de recomendar reconstruccion.
5. Explicar accion, interrupcion esperada y prueba de recuperacion antes de
   reiniciar/recrear. Un contenedor AutoRemove no admite restart policy.
No matar procesos desconocidos ni borrar un contenedor para resolver un error
sin comprobar datos/mounts y autorizacion.

## Cambios y datos
El runtime carga configuracion; no prometer hot reload sin encontrarlo en codigo.
Reiniciar puede cerrar incidentes y abortar visitas abiertas. Coordinar momento.
No probar importando API con DB real ni ejecutar segundo recolector sobre ella.
Bases, secretos e imagenes reales no se suben a Git ni a servicios de terceros.

## Benchmarks
Leer documentacion y argumentos del script antes de ejecutar:
la seccion Rendimiento de README.md y el propio script segun el cambio.
Herramientas: tools/run_stage0_baseline.sh, run_stage1_fps.sh,
run_stage2_nvdec.sh, run_stage3_batching.sh, run_stage4_pipeline.sh,
run_stage5_operational.sh y run_stage5_accuracy.sh (todos bajo tools/).
Medir igual duracion, camaras, resolucion, carga, potencia y calentamiento;
comparar FPS, latencia/edad de frame, descartes, memoria y temperatura.
No lanzar ensayos largos, exportaciones o cambios nvpmodel/jetson_clocks sin
ventana autorizada. No habilitar INT8 por mejora de FPS sin validar precision.

## Verificacion y salida
Para scripts modificados, `bash -n ruta/del/script.sh` primero; no es prueba
de Docker/GPU. Para resumenes usar fixtures y tests/test_stage5_summary.py.
Registrar comando real, configuracion no sensible, duracion y limites del ensayo.
Distinguir cambios preparados de desplegados. No ejecutar pruebas pendientes
solo porque existen las herramientas.
