"""Orquesta captura RTSP, deteccion, tracking, reglas, alertas y dashboard."""

import cv2
import json
import os
import time
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from database.repository import Repository
from metrics.recorder import MetricsRecorder
from metrics.staffing import StaffingStateMachine
from vision.detector import detect, load_detector
from vision.tracker import ByteTrackAdapter

CONFIG_PATH = Path(os.environ.get("AEYE_CONFIG", "/workspace/aeye-yolo/cameras.json"))
LOG_DIR = Path(os.environ.get("AEYE_LOG_DIR", "/workspace/aeye-yolo/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
ALERT_IMG_DIR = LOG_DIR / "alert_images"
ALERT_IMG_DIR.mkdir(parents=True, exist_ok=True)

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

STATE_LOCK = threading.Lock()
STATE = {}
LATEST_JPEG = {}
PREVIEW_ENABLED = False
STOP_EVENT = threading.Event()


def now_iso():
    """Devuelve la hora local actual en ISO 8601, incluyendo zona horaria."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg):
    """Escribe un mensaje con timestamp y fuerza su salida inmediata."""
    print(f"[{now_iso()}] {msg}", flush=True)


def append_jsonl(filename, payload):
    """Agrega un objeto JSON como una nueva linea dentro del directorio de logs."""
    path = LOG_DIR / filename
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


class CameraReader(threading.Thread):
    """Lee RTSP continuamente y conserva solo el frame mas reciente."""

    def __init__(self, cfg):
        """Inicializa el lector con la configuracion de una sola camara."""
        super().__init__(daemon=True, name=f"reader-{cfg['id']}")
        self.cfg = cfg
        self.lock = threading.Lock()
        self.frame = None
        self.frame_seq = 0
        self.connected = False
        self.last_error = ""
        self.cap = None

    def build_url(self):
        """Construye la URL RTSP usando un archivo secreto o una variable."""
        password_file = Path(
            self.cfg.get(
                "password_file",
                os.environ.get("CAMERA_PASSWORD_FILE", "/run/secrets/camera_password"),
            )
        )
        password = None
        if password_file.is_file():
            password = password_file.read_text(encoding="utf-8").rstrip("\r\n")

        env_name = self.cfg.get("password_env", "CAMERA_PASSWORD")
        if not password:
            password = os.environ.get(env_name)
        if not password:
            raise RuntimeError(
                f"Falta secreto {password_file} o variable de entorno {env_name}"
            )
        user = urllib.parse.quote(str(self.cfg["username"]), safe="")
        password = urllib.parse.quote(password, safe="")
        return (
            f"rtsp://{user}:{password}@{self.cfg['ip']}:{self.cfg.get('port', 554)}"
            f"/Streaming/Channels/{self.cfg.get('channel', 102)}"
        )

    def _close(self):
        """Libera de forma segura la captura de OpenCV si esta abierta."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def run(self):
        """Mantiene la conexion RTSP activa y reintenta luego de cada error."""
        while not STOP_EVENT.is_set():
            try:
                url = self.build_url()
                self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                if not self.cap.isOpened():
                    raise RuntimeError("No se pudo abrir RTSP")
                self.connected = True
                self.last_error = ""
                log(f"{self.cfg['id']} conectado a {self.cfg['ip']}")

                while not STOP_EVENT.is_set():
                    ok, frame = self.cap.read()
                    if not ok:
                        raise RuntimeError("Lectura RTSP fallida")
                    with self.lock:
                        self.frame = frame
                        self.frame_seq += 1

            except Exception as e:
                self.connected = False
                self.last_error = str(e)
                with self.lock:
                    self.frame = None
                log(f"{self.cfg['id']} desconectado: {e}. Reintento en 3s")
                self._close()
                STOP_EVENT.wait(3)

        self._close()

    def latest(self):
        """Devuelve una copia del ultimo frame y su numero de secuencia."""
        with self.lock:
            if self.frame is None:
                return None, self.frame_seq
            return self.frame.copy(), self.frame_seq


def save_alert_frame(frame, camera_id):
    """Guarda el frame exacto usado cuando se dispara una alerta."""
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{camera_id}_{timestamp}.jpg"
    path = ALERT_IMG_DIR / filename

    ok = cv2.imwrite(
        str(path),
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), 92],
    )

    if not ok:
        raise RuntimeError(f"No se pudo guardar frame de alerta: {path}")

    return str(path)


def send_alert(alert_cfg, payload):
    """Persiste la alerta, la registra y envia el webhook opcional."""
    append_jsonl("alerts.jsonl", payload)
    log("ALERTA: " + json.dumps(payload, ensure_ascii=False))

    if alert_cfg.get("mode") == "webhook" and alert_cfg.get("webhook_url"):
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                alert_cfg["webhook_url"],
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                log(f"Webhook enviado HTTP {r.status}")
        except Exception as e:
            log(f"ERROR enviando webhook: {e}")


def draw_overlay(frame, cam, boxes, ids, count, rule_state, remaining):
    """Dibuja cajas, IDs temporales y estado operativo sobre un frame."""
    for box, tid in zip(boxes, ids):
        x1, y1, x2, y2 = [int(v) for v in box]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
        cv2.putText(
            frame,
            f"P{tid:03d}",
            (x1, max(20, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )

    lines = [
        f"{cam['id']} | {cam['name']} | {cam.get('zone','')}",
        f"Personas: {count}",
        f"Estado: {rule_state}",
    ]
    if isinstance(remaining, (int, float)):
        lines.append(f"Alerta en: {int(remaining)} s")

    y = 25
    for line in lines:
        cv2.putText(
            frame, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX,
            0.6, (255, 255, 255), 2
        )
        y += 25
    return frame


class DashboardHandler(BaseHTTPRequestHandler):
    """Sirve dashboard, estado JSON y previews JPEG en memoria."""
    def log_message(self, format, *args):
        """Desactiva el log HTTP estandar para evitar ruido en consola."""
        return

    def _send(self, status, content_type, body):
        """Envia una respuesta HTTP sin cache con el cuerpo indicado."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Resuelve controles, imagenes, estado JSON y pagina principal."""
        global PREVIEW_ENABLED

        if self.path.startswith("/preview/on"):
            PREVIEW_ENABLED = True
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if self.path.startswith("/preview/off"):
            PREVIEW_ENABLED = False
            with STATE_LOCK:
                LATEST_JPEG.clear()
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if self.path.startswith("/camera/") and self.path.split("?")[0].endswith(".jpg"):
            cam_id = self.path.split("?")[0].split("/")[-1].replace(".jpg", "")
            with STATE_LOCK:
                data = LATEST_JPEG.get(cam_id)
            if data:
                self._send(200, "image/jpeg", data)
            else:
                self._send(404, "text/plain; charset=utf-8", b"Preview no disponible")
            return

        if self.path == "/state.json":
            with STATE_LOCK:
                data = json.dumps(STATE, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", data)
            return

        if self.path == "/" or self.path.startswith("/?"):
            with STATE_LOCK:
                snapshot = dict(STATE)
            cards = []
            for cam_id, s in snapshot.items():
                people = s.get("people")
                people_label = people if people is not None else "sin datos"
                cards.append(f"""
                <section class="card">
                  <h2>{cam_id} — {s.get('name','')}</h2>
                  <p>{s.get('zone','')} | personas: <b>{people_label}</b> | {s.get('rule_state','')}</p>
                  <img class="cam" data-cam="{cam_id}" alt="{cam_id}" />
                </section>
                """)
            refresh_ms = 1000
            body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>AEYE Preview</title>
<style>
body{{font-family:sans-serif;background:#111;color:#eee;margin:20px}}
.controls{{margin-bottom:16px}} a{{color:#8cf;margin-right:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}
.card{{background:#222;padding:12px;border-radius:10px}}
img{{width:100%;min-height:160px;object-fit:contain;background:#000}}
</style></head>
<body>
<h1>AEYE — Preview {"ON" if PREVIEW_ENABLED else "OFF"}</h1>
<div class="controls"><a href="/preview/on">Activar preview</a><a href="/preview/off">Desactivar preview</a></div>
<div class="grid">{''.join(cards)}</div>
<script>
setInterval(() => {{
  document.querySelectorAll('img.cam').forEach(img => {{
    img.src = '/camera/' + img.dataset.cam + '.jpg?t=' + Date.now();
  }});
}}, {refresh_ms});
</script>
</body></html>"""
            self._send(200, "text/html; charset=utf-8", body.encode("utf-8"))
            return

        self._send(404, "text/plain", b"Not found")


def start_dashboard(host, port):
    """Inicia el servidor HTTP en un hilo daemon y devuelve su instancia."""
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"Dashboard: http://{host}:{port}")
    return server


def main():
    """Ejecuta el ciclo multi-camara hasta recibir una senal de parada."""
    global PREVIEW_ENABLED

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    system_cfg = cfg["system"]
    preview_cfg = cfg["preview"]
    alert_cfg = cfg["alerts"]
    database_cfg = cfg.get("database", {})
    repository = None
    metrics_recorder = None
    if database_cfg.get("enabled", True):
        db_path = os.environ.get("AEYE_DB_PATH", database_cfg.get("path", str(LOG_DIR / "aeye.db")))
        repository = Repository(db_path)
        metrics_recorder = MetricsRecorder(
            repository, float(system_cfg.get("metrics_sample_every_seconds", 5))
        )
        interrupted = metrics_recorder.recover_after_restart()
        if interrupted:
            log(f"Incidentes interrumpidos por reinicio: {interrupted}")
        log(f"Base de datos: {db_path}")
    cameras = [c for c in cfg["cameras"] if c.get("enabled", False)]

    if not cameras:
        raise RuntimeError("No hay camaras habilitadas en cameras.json")

    PREVIEW_ENABLED = bool(preview_cfg.get("enabled", False))

    log("Cargando engine TensorRT...")
    model = load_detector(system_cfg)
    log("Backend activo: tensorrt")

    readers = {}
    trackers = {}
    rules = {}
    next_inference = {}
    last_log = {}

    for cam in cameras:
        reader = CameraReader(cam)
        readers[cam["id"]] = reader
        trackers[cam["id"]] = ByteTrackAdapter(system_cfg.get("tracker", {}))
        rules[cam["id"]] = StaffingStateMachine(cam, system_cfg)
        next_inference[cam["id"]] = 0.0
        last_log[cam["id"]] = 0.0
        with STATE_LOCK:
            STATE[cam["id"]] = {
                "name": cam["name"],
                "zone": cam.get("zone", ""),
                "ip": cam["ip"],
                "connected": False,
                "data_status": "no_data",
                "people": None,
                "raw_people": None,
                "track_ids": [],
                "rule_state": "starting",
                "last_update": None,
            }
        if repository:
            repository.upsert_camera(cam, datetime.now().astimezone())
        reader.start()

    dashboard = start_dashboard(preview_cfg["host"], int(preview_cfg["port"]))
    interval = 1.0 / float(system_cfg["inference_fps_per_camera"])

    log(f"AEYE iniciado con {len(cameras)} camara(s). Ctrl+C para detener.")

    try:
        while not STOP_EVENT.is_set():
            loop_now = time.monotonic()

            for cam in cameras:
                cam_id = cam["id"]
                reader = readers[cam_id]

                if loop_now < next_inference[cam_id]:
                    continue
                next_inference[cam_id] = loop_now + interval

                frame, seq = reader.latest()
                if frame is None:
                    observation = rules[cam_id].no_data()
                    if metrics_recorder and cam.get("monitor_staffing", False):
                        metrics_recorder.observe(cam, observation)
                    with STATE_LOCK:
                        STATE[cam_id]["connected"] = reader.connected
                        STATE[cam_id]["data_status"] = "no_data"
                        STATE[cam_id]["people"] = None
                        STATE[cam_id]["raw_people"] = None
                        STATE[cam_id]["track_ids"] = []
                        STATE[cam_id]["rule_state"] = "no_data"
                        STATE[cam_id]["last_update"] = now_iso()
                        STATE[cam_id]["last_error"] = reader.last_error
                    continue

                try:
                    t0 = time.perf_counter()
                    detections = detect(model, frame, system_cfg)
                    infer_ms = (time.perf_counter() - t0) * 1000.0
                    tracks = trackers[cam_id].update(detections, frame.shape)
                except Exception as error:
                    observation = rules[cam_id].no_data()
                    if metrics_recorder and cam.get("monitor_staffing", False):
                        metrics_recorder.observe(cam, observation)
                    with STATE_LOCK:
                        STATE[cam_id].update({
                            "connected": reader.connected,
                            "data_status": "no_data",
                            "people": None,
                            "raw_people": None,
                            "track_ids": [],
                            "rule_state": "no_data",
                            "last_update": now_iso(),
                            "last_error": f"Inferencia/tracking: {error}",
                        })
                    log(f"{cam_id} error de inferencia/tracking: {error}")
                    continue

                boxes = [track.box for track in tracks]
                ids = [track.track_id for track in tracks]
                raw_count = len(tracks)
                observation = rules[cam_id].evaluate(raw_count)
                count = observation.smoothed_count
                rule_state = observation.rule_state
                if metrics_recorder and cam.get("monitor_staffing", False):
                    metrics_recorder.observe(cam, observation)

                if observation.alert:
                    detail = dict(observation.alert)
                    detail["timestamp"] = now_iso()
                    if metrics_recorder:
                        metrics_recorder.mark_alerted(cam_id)
                    try:
                        alert_frame = frame.copy()
                        alert_image_path = save_alert_frame(alert_frame, cam_id)
                        detail["image_path"] = alert_image_path
                        log(f"{cam_id} frame de alerta guardado en {alert_image_path}")
                    except Exception as e:
                        detail["image_path"] = None
                        detail["image_error"] = str(e)
                        log(f"{cam_id} ERROR guardando frame de alerta: {e}")

                    send_alert(alert_cfg, detail)
                    remaining = 0
                else:
                    remaining = observation.seconds_to_alert

                state_row = {
                    "name": cam["name"],
                    "zone": cam.get("zone", ""),
                    "ip": cam["ip"],
                    "connected": reader.connected,
                    "data_status": observation.data_status,
                    "people": count,
                    "raw_people": raw_count,
                    "detections": len(detections),
                    "track_ids": [f"P{x:03d}" for x in ids],
                    "rule_state": rule_state,
                    "seconds_to_alert": round(remaining, 1) if isinstance(remaining, (int, float)) else None,
                    "inference_ms": round(infer_ms, 1),
                    "inference_backend": "tensorrt",
                    "frame_seq": seq,
                    "last_update": now_iso(),
                    "last_error": reader.last_error,
                }
                with STATE_LOCK:
                    STATE[cam_id] = state_row

                if PREVIEW_ENABLED:
                    annotated = draw_overlay(frame.copy(), cam, boxes, ids, count, rule_state, remaining)
                    ok, buf = cv2.imencode(
                        ".jpg", annotated,
                        [int(cv2.IMWRITE_JPEG_QUALITY), int(preview_cfg.get("jpeg_quality", 70))]
                    )
                    if ok:
                        with STATE_LOCK:
                            LATEST_JPEG[cam_id] = buf.tobytes()

                if loop_now - last_log[cam_id] >= float(system_cfg.get("log_every_seconds", 10)):
                    log(
                        f"{cam_id} personas={count} crudo={raw_count} "
                        f"IDs={[f'P{x:03d}' for x in ids]} "
                        f"estado={rule_state} infer={infer_ms:.1f}ms"
                    )
                    last_log[cam_id] = loop_now

            time.sleep(0.005)

    except KeyboardInterrupt:
        log("Deteniendo por Ctrl+C...")
    finally:
        STOP_EVENT.set()
        dashboard.shutdown()
        for reader in readers.values():
            reader.join(timeout=2)
        if repository:
            repository.close()
        log("AEYE detenido.")


if __name__ == "__main__":
    main()
