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
from metrics.performance import PerformanceMonitor
from metrics.recorder import MetricsRecorder
from metrics.staffing import StaffingStateMachine
from vision.batching import BatchScheduler, parse_batching_settings
from vision.capture import open_capture, parse_capture_settings
from vision.detector import (
    detect_batch,
    load_detector,
    validate_engine_for_batching,
)
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


def round_metric(value):
    """Redondea una metrica opcional sin convertir ausencia de datos en cero."""
    return round(float(value), 1) if isinstance(value, (int, float)) else None


def append_jsonl(filename, payload):
    """Agrega un objeto JSON como una nueva linea dentro del directorio de logs."""
    path = LOG_DIR / filename
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


class CameraReader(threading.Thread):
    """Lee RTSP continuamente y conserva solo el frame mas reciente."""

    def __init__(self, cfg, capture_cfg=None):
        """Inicializa el lector con la configuracion de una sola camara."""
        super().__init__(daemon=True, name=f"reader-{cfg['id']}")
        self.cfg = cfg
        self.capture_cfg = dict(capture_cfg or {})
        self.capture_settings = parse_capture_settings(self.capture_cfg)
        self.force_ffmpeg = False
        self.lock = threading.Lock()
        self.frame = None
        self.frame_seq = 0
        self.frame_captured_at = None
        self.connected = False
        self.last_error = ""
        self.cap = None
        self.received_frames = 0
        self.first_frame_at = None
        self.last_frame_at = None
        self.connection_attempts = 0
        self.successful_connections = 0
        self.connection_errors = 0
        self.stream = {
            "width": None,
            "height": None,
            "reported_fps": None,
            "codec": None,
            "capture_backend": None,
            "hardware_decode": False,
            "fallback_reason": None,
        }

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
        """Libera de forma segura el backend de captura si esta abierto."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def run(self):
        """Mantiene la conexion RTSP activa y reintenta luego de cada error."""
        while not STOP_EVENT.is_set():
            try:
                with self.lock:
                    self.connection_attempts += 1
                url = self.build_url()
                self.cap = open_capture(
                    url, self.capture_cfg, force_ffmpeg=self.force_ffmpeg
                )
                if not self.cap.is_opened():
                    raise RuntimeError("No se pudo abrir RTSP")
                stream = self.cap.stream_info()
                with self.lock:
                    self.connected = True
                    self.last_error = ""
                    self.successful_connections += 1
                    self.stream = stream
                log(
                    f"{self.cfg['id']} conectado a {self.cfg['ip']} "
                    f"con captura={stream['capture_backend']}"
                )

                while not STOP_EVENT.is_set():
                    ok, frame = self.cap.read()
                    if not ok:
                        raise RuntimeError("Lectura RTSP fallida")
                    captured_at = time.monotonic()
                    stream = self.cap.stream_info()
                    with self.lock:
                        self.frame = frame
                        self.frame_seq += 1
                        self.frame_captured_at = captured_at
                        self.received_frames += 1
                        if self.first_frame_at is None:
                            self.first_frame_at = captured_at
                        self.last_frame_at = captured_at
                        self.stream = stream

            except Exception as e:
                failed_backend = getattr(self.cap, "backend_name", None)
                if (
                    failed_backend == "gstreamer_nvdec"
                    and self.capture_settings.fallback_to_ffmpeg
                ):
                    self.force_ffmpeg = True
                with self.lock:
                    self.connected = False
                    self.last_error = str(e)
                    self.frame = None
                    self.frame_captured_at = None
                    self.connection_errors += 1
                log(f"{self.cfg['id']} desconectado: {e}. Reintento en 3s")
                if self.force_ffmpeg and failed_backend == "gstreamer_nvdec":
                    log(f"{self.cfg['id']} activara fallback de captura FFmpeg")
                self._close()
                STOP_EVENT.wait(3)

        self._close()

    def has_frame(self):
        """Permite al batcher esperar disponibilidad sin copiar la imagen."""
        with self.lock:
            return self.frame is not None

    def latest(self):
        """Devuelve el ultimo frame, su secuencia y hora de decodificacion."""
        with self.lock:
            if self.frame is None:
                return None, self.frame_seq, None
            return self.frame.copy(), self.frame_seq, self.frame_captured_at

    def performance_snapshot(self):
        """Expone contadores RTSP y propiedades del stream sin credenciales."""
        with self.lock:
            active_seconds = 0.0
            if (
                self.received_frames > 1
                and self.first_frame_at is not None
                and self.last_frame_at is not None
            ):
                active_seconds = max(
                    self.last_frame_at - self.first_frame_at,
                    1e-9,
                )
            return {
                "received_frames": self.received_frames,
                "received_fps_active": round(
                    (self.received_frames - 1) / active_seconds, 3
                ) if active_seconds else 0.0,
                "connection_attempts": self.connection_attempts,
                "successful_connections": self.successful_connections,
                "connection_errors": self.connection_errors,
                "stream": dict(self.stream),
            }


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
    capture_cfg = system_cfg.get("capture", {})
    batching_settings = parse_batching_settings(system_cfg)
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
    performance_path = Path(
        os.environ.get(
            "AEYE_PERFORMANCE_PATH",
            str(LOG_DIR / "performance_summary.json"),
        )
    )
    performance_configuration = {
        "camera_count": len(cameras),
        "camera_ids": [cam["id"] for cam in cameras],
        "preview_enabled": PREVIEW_ENABLED,
        "engine": Path(system_cfg["tensorrt_engine"]).name,
        "imgsz": int(system_cfg["imgsz"]),
        "requested_inference_fps_per_camera": float(
            system_cfg["inference_fps_per_camera"]
        ),
        "requested_capture_backend": parse_capture_settings(capture_cfg).backend,
        "batching_enabled": batching_settings.enabled,
        "batching_max_batch_size": batching_settings.max_batch_size,
        "batching_timeout_ms": batching_settings.timeout_ms,
    }

    engine_capabilities = validate_engine_for_batching(
        system_cfg, batching_settings
    )
    performance_configuration.update({
        "engine_batch_size": engine_capabilities.batch_size,
        "engine_dynamic": engine_capabilities.dynamic,
        "engine_precision": engine_capabilities.precision,
    })
    log("Cargando engine TensorRT...")
    model = load_detector(system_cfg)
    log(
        "Backend activo: tensorrt "
        f"batching={batching_settings.enabled} "
        f"batch_max={batching_settings.max_batch_size}"
    )

    readers = {}
    trackers = {}
    rules = {}
    last_log = {}

    for cam in cameras:
        reader = CameraReader(cam, capture_cfg)
        readers[cam["id"]] = reader
        trackers[cam["id"]] = ByteTrackAdapter(system_cfg.get("tracker", {}))
        rules[cam["id"]] = StaffingStateMachine(cam, system_cfg)
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
    scheduler = BatchScheduler(
        [cam["id"] for cam in cameras],
        float(system_cfg["inference_fps_per_camera"]),
        batching_settings,
    )
    performance_monitor = PerformanceMonitor([cam["id"] for cam in cameras])

    log(f"AEYE iniciado con {len(cameras)} camara(s). Ctrl+C para detener.")

    camera_by_id = {cam["id"]: cam for cam in cameras}
    last_dispatched_sequence = {cam["id"]: None for cam in cameras}

    def mark_no_data(cam_id, error=None):
        """Propaga ausencia o fallo sin convertirlo en un conteo cero."""
        cam = camera_by_id[cam_id]
        reader = readers[cam_id]
        if error is None:
            performance_monitor.record_no_data(cam_id)
            last_error = reader.last_error
        else:
            performance_monitor.record_error(cam_id)
            last_error = f"Inferencia/tracking: {error}"
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
                "last_error": last_error,
            })
        if error is not None:
            log(f"{cam_id} error de inferencia/tracking: {error}")

    try:
        while not STOP_EVENT.is_set():
            window_started = time.monotonic()
            due_ids = scheduler.due(window_started)
            if not due_ids:
                STOP_EVENT.wait(scheduler.idle_sleep_seconds(window_started))
                continue

            deadline = scheduler.window_deadline(window_started)
            while batching_settings.enabled and not STOP_EVENT.is_set():
                now = time.monotonic()
                due_ids = scheduler.due(now)
                ready_count = sum(readers[cam_id].has_frame() for cam_id in due_ids)
                if ready_count >= batching_settings.max_batch_size or now >= deadline:
                    break
                wait_seconds = scheduler.wait_seconds(now, deadline)
                if wait_seconds <= 0.0:
                    break
                STOP_EVENT.wait(wait_seconds)

            dispatch_at = time.monotonic()
            due_ids = scheduler.due(dispatch_at)
            ready_ids = [
                cam_id for cam_id in due_ids if readers[cam_id].has_frame()
            ]
            selected_ids = ready_ids[:batching_settings.max_batch_size]
            no_data_ids = [
                cam_id for cam_id in due_ids if not readers[cam_id].has_frame()
            ]
            scheduled_ids = selected_ids + no_data_ids
            if not scheduled_ids:
                STOP_EVENT.wait(scheduler.idle_sleep_seconds(dispatch_at))
                continue

            schedule_lags = scheduler.schedule(scheduled_ids, dispatch_at)
            batch_wait_ms = (
                (dispatch_at - window_started) * 1000.0
                if batching_settings.enabled
                else 0.0
            )
            for cam_id in no_data_ids:
                mark_no_data(cam_id)

            batch_items = []
            for cam_id in selected_ids:
                reader = readers[cam_id]
                frame, seq, captured_at = reader.latest()
                if frame is None:
                    mark_no_data(cam_id)
                    continue
                previous_seq = last_dispatched_sequence[cam_id]
                if previous_seq is not None and seq < previous_seq:
                    mark_no_data(
                        cam_id,
                        RuntimeError(
                            f"secuencia fuera de orden: {seq} < {previous_seq}"
                        ),
                    )
                    continue
                last_dispatched_sequence[cam_id] = seq
                batch_items.append({
                    "cam": camera_by_id[cam_id],
                    "cam_id": cam_id,
                    "reader": reader,
                    "frame": frame,
                    "seq": seq,
                    "captured_at": captured_at,
                    "process_started": time.monotonic(),
                    "schedule_lag_ms": schedule_lags[cam_id],
                })

            if not batch_items:
                continue

            detector_started = time.perf_counter()
            try:
                detections_by_frame, timings_by_frame = detect_batch(
                    model,
                    [item["frame"] for item in batch_items],
                    system_cfg,
                    with_timing=True,
                )
                detector_total_ms = (
                    time.perf_counter() - detector_started
                ) * 1000.0
                performance_monitor.record_batch(
                    len(batch_items), batch_wait_ms, detector_total_ms
                )
            except Exception as error:
                for item in batch_items:
                    mark_no_data(item["cam_id"], error)
                continue

            batch_size = len(batch_items)
            for item, detections, detector_timings in zip(
                batch_items, detections_by_frame, timings_by_frame
            ):
                cam = item["cam"]
                cam_id = item["cam_id"]
                reader = item["reader"]
                frame = item["frame"]
                seq = item["seq"]
                captured_at = item["captured_at"]
                try:
                    tracker_started = time.perf_counter()
                    tracks = trackers[cam_id].update(detections, frame.shape)
                    tracker_ms = (
                        time.perf_counter() - tracker_started
                    ) * 1000.0
                except Exception as error:
                    mark_no_data(cam_id, error)
                    continue

                boxes = [track.box for track in tracks]
                ids = [track.track_id for track in tracks]
                raw_count = len(tracks)
                observation = rules[cam_id].evaluate(raw_count)
                count = observation.smoothed_count
                rule_state = observation.rule_state
                result_ready = time.monotonic()
                timings = dict(detector_timings)
                timings.update({
                    "schedule_lag_ms": item["schedule_lag_ms"],
                    "batch_wait_ms": batch_wait_ms,
                    "frame_age_ms": (
                        (item["process_started"] - captured_at) * 1000.0
                        if captured_at is not None
                        else None
                    ),
                    "detector_total_ms": detector_total_ms,
                    "tracker_ms": tracker_ms,
                    "capture_to_result_ms": (
                        (result_ready - captured_at) * 1000.0
                        if captured_at is not None
                        else None
                    ),
                })
                perf_snapshot = performance_monitor.record_analysis(
                    cam_id, seq, timings
                )
                infer_ms = detector_timings.get("inference_ms")
                if metrics_recorder and cam.get("monitor_staffing", False):
                    metrics_recorder.observe(cam, observation)

                if observation.alert:
                    detail = dict(observation.alert)
                    detail["timestamp"] = now_iso()
                    if metrics_recorder:
                        metrics_recorder.mark_alerted(cam_id)
                    try:
                        alert_image_path = save_alert_frame(frame.copy(), cam_id)
                        detail["image_path"] = alert_image_path
                        log(f"{cam_id} frame de alerta guardado en {alert_image_path}")
                    except Exception as error:
                        detail["image_path"] = None
                        detail["image_error"] = str(error)
                        log(f"{cam_id} ERROR guardando frame de alerta: {error}")

                    send_alert(alert_cfg, detail)
                    remaining = 0
                else:
                    remaining = observation.seconds_to_alert

                reader_snapshot = reader.performance_snapshot()
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
                    "seconds_to_alert": (
                        round(remaining, 1)
                        if isinstance(remaining, (int, float))
                        else None
                    ),
                    "preprocess_ms": round_metric(timings["preprocess_ms"]),
                    "inference_ms": round_metric(infer_ms),
                    "postprocess_ms": round_metric(timings["postprocess_ms"]),
                    "detector_total_ms": round_metric(detector_total_ms),
                    "tracker_ms": round_metric(tracker_ms),
                    "batch_size": batch_size,
                    "batch_wait_ms": round_metric(batch_wait_ms),
                    "frame_age_ms": round_metric(timings["frame_age_ms"]),
                    "capture_to_result_ms": round_metric(
                        timings["capture_to_result_ms"]
                    ),
                    "received_fps": reader_snapshot["received_fps_active"],
                    "analyzed_fps": perf_snapshot["analyzed_fps"],
                    "skipped_frames": perf_snapshot["scheduler_skipped_frames"],
                    "reconnections": max(
                        0, reader_snapshot["successful_connections"] - 1
                    ),
                    "capture_backend": reader_snapshot["stream"][
                        "capture_backend"
                    ],
                    "inference_backend": "tensorrt",
                    "frame_seq": seq,
                    "last_update": now_iso(),
                    "last_error": reader.last_error,
                }
                with STATE_LOCK:
                    STATE[cam_id] = state_row

                if PREVIEW_ENABLED:
                    annotated = draw_overlay(
                        frame.copy(),
                        cam,
                        boxes,
                        ids,
                        count,
                        rule_state,
                        remaining,
                    )
                    ok, buf = cv2.imencode(
                        ".jpg",
                        annotated,
                        [
                            int(cv2.IMWRITE_JPEG_QUALITY),
                            int(preview_cfg.get("jpeg_quality", 70)),
                        ],
                    )
                    if ok:
                        with STATE_LOCK:
                            LATEST_JPEG[cam_id] = buf.tobytes()

                if result_ready - last_log[cam_id] >= float(
                    system_cfg.get("log_every_seconds", 10)
                ):
                    log(
                        f"{cam_id} personas={count} crudo={raw_count} "
                        f"IDs={[f'P{x:03d}' for x in ids]} "
                        f"estado={rule_state} infer={round_metric(infer_ms)}ms "
                        f"batch={batch_size}"
                    )
                    last_log[cam_id] = result_ready

    except KeyboardInterrupt:
        log("Deteniendo por Ctrl+C...")
    finally:
        STOP_EVENT.set()
        performance_monitor.stop()
        dashboard.shutdown()
        for reader in readers.values():
            reader.join(timeout=2)
        try:
            written_path = performance_monitor.write(
                performance_path, readers, performance_configuration
            )
            log(f"Resumen de rendimiento: {written_path}")
        except Exception as error:
            log(f"ERROR escribiendo resumen de rendimiento: {error}")
        if repository:
            repository.close()
        log("AEYE detenido.")


if __name__ == "__main__":
    main()
