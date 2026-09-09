---
name: aeye-web
description: Modificar la web de AEYE Actividad o AEYE Preview, graficos, filtros, vistas por camara y exportacion PNG/PDF. Usar para api/static y preview; no asumir React ni recalcular reglas laborales en JavaScript.
---

# Web de AEYE

## Dos superficies
- Actividad: `api/static/dashboard.html`, `dashboard.js`, `dashboard.css`;
  servida por FastAPI. Tiene periodos diario/semanal/mensual y seleccion de camara.
- Preview: `preview/index.html`, `preview.js`, `preview.css` y `state.py`;
  se integra con `main.py` y consulta `/preview-state.json`.
No mezclar sus rutas ni asumir que un puerto sirve ambas interfaces.
Es HTML/CSS/JavaScript sin pipeline npm ni framework de componentes.

## Flujo
1. Seguir estado, fetch y render de la vista afectada antes de editar.
2. Obtener metricas del contrato API. Si falta una medida, coordinar con
   aeye-activity y aeye-api; no inventar valores ni derivar identidades en UI.
3. Mantener ID de camara estable al enfocar, volver a mosaico, filtrar y ordenar.
   Nombres visibles/orden vienen de configuracion, no del numero de camara.
4. Conservar estados de carga, error, vacio, parcial y sin cobertura.
   Null no es 0%; datos ausentes no son personas ausentes.
5. Para graficos indicar unidades, periodo y cobertura. El dashboard es una
   herramienta operativa: jerarquia compacta, controles accesibles y sin landing
   de marketing ni tarjetas decorativas que reduzcan el area de datos.

## Exportaciones
`downloadWeeklyImage` en dashboard.js genera imagen en el navegador mediante
SVG foreignObject y canvas; el nombre historico no implica soporte de todas
las vistas. Inspeccionar que DOM y periodo exporta realmente.
PDF usa `window.print()`: el usuario elige guardar PDF.
Los archivos se guardan en el equipo del navegador, no en una carpeta del servidor.
Comprobar fuentes, CSS embebido, imagenes same-origin, permisos de descarga y
URL de blobs; capturar errores visibles. No introducir CDNs innecesarios en LAN.

## Verificacion
```bash
python3 -m unittest discover -s tests -p 'test_weekly_dashboard.py' -v
python3 -m unittest discover -s tests -p 'test_preview_ui.py' -v
```
Son pruebas estructurales, no sustituyen navegador. Para cambios visuales:
probar desktop y movil, fechas, cambio de camara y retorno; comprobar consola,
red, overflow, enfoque y una descarga PNG no vacia e impresion legible.
Usar fixtures anonimos en servidor aislado; no exponer capturas reales.
Si no hay navegador automatizado, informar la limitacion, no afirmar validacion
visual. No arrancar el pipeline GPU solo para probar HTML.
