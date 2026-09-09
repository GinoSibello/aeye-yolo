# Alcance: preview de camaras
Leer [aeye-web](../skills/aeye-web/SKILL.md).
Para payload/snapshots y main.py, sumar aeye-vision.
- Conservar ID al enfocar una camara y regresar al mosaico.
- No divulgar URL RTSP, credenciales o campos internos en preview-state.json.
- No modificar frames compartidos al renderizar anotaciones.
- No confundir preview con api/static ni asumir que comparten servidor.
