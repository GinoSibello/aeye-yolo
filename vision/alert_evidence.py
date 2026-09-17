"""Evidencia JPEG asincrona alrededor de alertas anonimas de dotacion."""

from __future__ import annotations

import cv2
import hashlib
import json
import math
import os
import queue
import re
import shutil
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


EVIDENCE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class AlertEvidenceSettings:
    enabled: bool = False
    root: Path = Path("logs/alert_evidence")
    sample_fps: float = 1.0
    pre_seconds: float = 30.0
    post_seconds: float = 30.0
    jpeg_quality: int = 92
    input_queue_size: int = 128
    write_queue_size: int = 512
    retention_days: int = 30
    min_free_bytes: int = 5 * 1024**3
    cleanup_target_free_bytes: int = 6 * 1024**3

    @property
    def expected_frames(self):
        return max(
            1,
            int(round((self.pre_seconds + self.post_seconds) * self.sample_fps)),
        )


@dataclass(frozen=True)
class EncodedFrame:
    camera_id: str
    frame_seq: int
    timestamp: datetime
    jpeg: bytes
    sha256: str
    raw_people: int
    people: int


@dataclass(frozen=True)
class InputTask:
    camera_id: str
    frame_seq: int
    timestamp: datetime
    frame: object
    raw_people: int
    people: int
    trigger: dict | None = None


@dataclass(frozen=True)
class WriterCommand:
    kind: str
    evidence_id: str
    payload: object


@dataclass
class ActiveEvidence:
    evidence_id: str
    camera_id: str
    alert_at: datetime
    post_until_epoch: float
    trigger: dict
    dropped_frames: int = 0
    input_drops_start: int = 0


def parse_alert_evidence_settings(alert_cfg, project_dir=None):
    """Valida configuracion sin crear directorios cuando esta deshabilitada."""
    values = dict((alert_cfg or {}).get("evidence", {}) or {})
    base = Path(project_dir) if project_dir is not None else Path.cwd()
    root = Path(values.get("root", "logs/alert_evidence"))
    if not root.is_absolute():
        root = base / root

    def positive_float(name, default):
        value = float(values.get(name, default))
        if value <= 0:
            raise ValueError(f"alerts.evidence.{name} debe ser mayor que cero")
        return value

    def positive_int(name, default):
        value = int(values.get(name, default))
        if value < 1:
            raise ValueError(f"alerts.evidence.{name} debe ser al menos 1")
        return value

    quality = int(values.get("jpeg_quality", 92))
    if not 1 <= quality <= 100:
        raise ValueError("alerts.evidence.jpeg_quality debe estar entre 1 y 100")
    min_free_gb = float(values.get("min_free_gb", 5.0))
    target_free_gb = float(values.get("cleanup_target_free_gb", 6.0))
    if min_free_gb < 0:
        raise ValueError("alerts.evidence.min_free_gb no puede ser negativo")
    if target_free_gb < min_free_gb:
        raise ValueError(
            "alerts.evidence.cleanup_target_free_gb no puede ser menor que min_free_gb"
        )

    return AlertEvidenceSettings(
        enabled=bool(values.get("enabled", False)),
        root=root,
        sample_fps=positive_float("sample_fps", 1.0),
        pre_seconds=positive_float("pre_seconds", 30.0),
        post_seconds=positive_float("post_seconds", 30.0),
        jpeg_quality=quality,
        input_queue_size=positive_int("input_queue_size", 128),
        write_queue_size=positive_int("write_queue_size", 512),
        retention_days=positive_int("retention_days", 30),
        min_free_bytes=int(min_free_gb * 1024**3),
        cleanup_target_free_bytes=int(target_free_gb * 1024**3),
    )


def _atomic_json(path, payload):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class AlertEvidenceCollector:
    """Comprime en segundo plano y persiste eventos sin bloquear inferencia."""

    def __init__(self, settings, logger=None):
        self.settings = settings
        self.root = settings.root.resolve()
        self.logger = logger or (lambda message: None)
        self._input_queue = queue.Queue(maxsize=settings.input_queue_size)
        self._write_queue = queue.Queue(maxsize=settings.write_queue_size)
        self._encoder_stop = threading.Event()
        self._writer_stop = threading.Event()
        self._lock = threading.Lock()
        self._last_sample_at = {}
        self._input_drops_by_camera = defaultdict(int)
        self._buffers = defaultdict(
            lambda: deque(
                maxlen=max(1, int(math.ceil(
                    self.settings.pre_seconds * self.settings.sample_fps
                )))
            )
        )
        self._active = {}
        self._active_by_camera = defaultdict(set)
        self._writer_events = {}
        self._last_cleanup_epoch = 0.0
        self._counters = {
            "sampled": 0,
            "input_queue_full": 0,
            "write_queue_full": 0,
            "encode_errors": 0,
            "write_errors": 0,
            "events_started": 0,
            "events_completed": 0,
            "events_failed": 0,
            "events_interrupted": 0,
            "events_deleted": 0,
        }

        self.root.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted()
        self._cleanup_storage(datetime.now().astimezone())
        self._encoder = threading.Thread(
            target=self._encoder_loop,
            daemon=True,
            name="alert-evidence-encoder",
        )
        self._writer = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="alert-evidence-writer",
        )
        self._writer.start()
        self._encoder.start()

    def snapshot(self):
        with self._lock:
            return {
                "enabled": True,
                "input_queue_size": self._input_queue.qsize(),
                "write_queue_size": self._write_queue.qsize(),
                "active_events": len(self._active),
                **self._counters,
            }

    def observe(
        self,
        camera_id,
        frame_seq,
        timestamp,
        frame,
        raw_people,
        people,
        alert=None,
        monitoring=True,
    ):
        """Encola como maximo una muestra por intervalo y devuelve descriptor."""
        if not monitoring:
            return None
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp de evidencia debe incluir zona horaria")
        camera_id = str(camera_id)
        trigger = None
        if alert and alert.get("kind") == "missing":
            evidence_id = uuid.uuid4().hex
            trigger = {
                "evidence_id": evidence_id,
                "camera_id": camera_id,
                "camera_name": str(alert.get("camera_name", camera_id)),
                "alert_at": timestamp.isoformat(),
                "kind": "missing",
                "reason": "faltantes",
                "raw_people": int(alert.get("raw_people", raw_people)),
                "people": int(alert.get("people", people)),
                "expected_min": int(alert.get("expected_min", 0)),
                "expected_max": int(alert.get("expected_max", 0)),
                "outside_range_seconds": float(
                    alert.get("outside_range_seconds", 0.0)
                ),
            }

        epoch = timestamp.timestamp()
        interval = 1.0 / self.settings.sample_fps
        with self._lock:
            last_sample = self._last_sample_at.get(camera_id)
            due = last_sample is None or epoch - last_sample >= interval
            if not due and trigger is None:
                return None
            self._last_sample_at[camera_id] = epoch

        task = InputTask(
            camera_id=camera_id,
            frame_seq=int(frame_seq),
            timestamp=timestamp,
            frame=frame.copy(),
            raw_people=int(raw_people),
            people=int(people),
            trigger=trigger,
        )
        try:
            self._input_queue.put_nowait(task)
        except queue.Full:
            with self._lock:
                self._counters["input_queue_full"] += 1
                self._input_drops_by_camera[camera_id] += 1
            if trigger:
                return self._descriptor(trigger["evidence_id"], "failed")
            return None
        with self._lock:
            self._counters["sampled"] += 1
        return (
            self._descriptor(trigger["evidence_id"], "collecting")
            if trigger else None
        )

    def _descriptor(self, evidence_id, status):
        return {
            "id": evidence_id,
            "status": status,
            "planned_frames": self.settings.expected_frames,
            "api_path": f"/api/alert-evidence/{evidence_id}",
        }

    def _encoder_loop(self):
        while not self._encoder_stop.is_set() or not self._input_queue.empty():
            try:
                task = self._input_queue.get(timeout=0.2)
            except queue.Empty:
                self._finalize_due(time.time())
                continue
            try:
                self._encode_task(task)
            except Exception as error:
                with self._lock:
                    self._counters["encode_errors"] += 1
                self.logger(
                    "ERROR comprimiendo evidencia de alerta: "
                    f"{type(error).__name__}: {error}"
                )
            finally:
                self._input_queue.task_done()
            self._finalize_due(time.time())

        for evidence_id in list(self._active):
            self._finish_active(evidence_id, "interrupted")

    def _encode_task(self, task):
        ok, encoded = cv2.imencode(
            ".jpg",
            task.frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.settings.jpeg_quality],
        )
        if not ok:
            raise OSError("OpenCV no pudo codificar evidencia JPEG")
        jpeg = encoded.tobytes()
        frame = EncodedFrame(
            camera_id=task.camera_id,
            frame_seq=task.frame_seq,
            timestamp=task.timestamp,
            jpeg=jpeg,
            sha256=hashlib.sha256(jpeg).hexdigest(),
            raw_people=task.raw_people,
            people=task.people,
        )
        buffer = self._buffers[task.camera_id]

        if task.trigger:
            self._start_active(task.trigger, list(buffer))

        for evidence_id in list(self._active_by_camera[task.camera_id]):
            active = self._active.get(evidence_id)
            if active is None:
                continue
            epoch = task.timestamp.timestamp()
            if epoch >= active.post_until_epoch:
                self._finish_active(evidence_id, "complete")
            elif epoch >= active.alert_at.timestamp():
                if not self._enqueue_writer(
                    WriterCommand("frame", evidence_id, frame)
                ):
                    active.dropped_frames += 1
        buffer.append(frame)

    def _start_active(self, trigger, pre_frames):
        evidence_id = trigger["evidence_id"]
        alert_at = datetime.fromisoformat(trigger["alert_at"])
        earliest = alert_at.timestamp() - self.settings.pre_seconds
        pre_frames = [
            frame for frame in pre_frames
            if earliest <= frame.timestamp.timestamp() < alert_at.timestamp()
        ]
        with self._lock:
            input_drops_start = self._input_drops_by_camera[trigger["camera_id"]]
        active = ActiveEvidence(
            evidence_id=evidence_id,
            camera_id=trigger["camera_id"],
            alert_at=alert_at,
            post_until_epoch=alert_at.timestamp() + self.settings.post_seconds,
            trigger=trigger,
            input_drops_start=input_drops_start,
        )
        command = WriterCommand(
            "start",
            evidence_id,
            {"trigger": trigger, "pre_frames": pre_frames},
        )
        if not self._enqueue_writer(command, control=True):
            with self._lock:
                self._counters["events_failed"] += 1
            return
        self._active[evidence_id] = active
        self._active_by_camera[active.camera_id].add(evidence_id)

    def _enqueue_writer(self, command, control=False):
        try:
            if control:
                self._write_queue.put(command, timeout=0.5)
            else:
                self._write_queue.put_nowait(command)
            return True
        except queue.Full:
            with self._lock:
                self._counters["write_queue_full"] += 1
            return False

    def _finalize_due(self, now_epoch):
        for evidence_id, active in list(self._active.items()):
            if now_epoch >= active.post_until_epoch:
                self._finish_active(evidence_id, "complete")

    def _finish_active(self, evidence_id, status):
        active = self._active.get(evidence_id)
        if active is None:
            return
        with self._lock:
            input_drops = max(
                0,
                self._input_drops_by_camera[active.camera_id]
                - active.input_drops_start,
            )
        command = WriterCommand(
            "finish",
            evidence_id,
            {
                "status": status,
                "dropped_frames": active.dropped_frames + input_drops,
            },
        )
        if not self._enqueue_writer(command, control=True):
            return
        self._active.pop(evidence_id, None)
        self._active_by_camera[active.camera_id].discard(evidence_id)

    def _writer_loop(self):
        while not self._writer_stop.is_set() or not self._write_queue.empty():
            try:
                command = self._write_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if command.kind == "start":
                    self._writer_start(command)
                elif command.kind == "frame":
                    self._writer_frame(command)
                elif command.kind == "finish":
                    self._writer_finish(command)
            except Exception as error:
                with self._lock:
                    self._counters["write_errors"] += 1
                self._mark_writer_failed(command.evidence_id, error)
                self.logger(
                    "ERROR escribiendo evidencia de alerta: "
                    f"{type(error).__name__}: {error}"
                )
            finally:
                self._write_queue.task_done()

    def _writer_start(self, command):
        payload = command.payload
        trigger = payload["trigger"]
        alert_at = datetime.fromisoformat(trigger["alert_at"])
        self._cleanup_storage(alert_at)
        day_dir = self.root / alert_at.date().isoformat()
        event_dir = day_dir / command.evidence_id
        frames_dir = event_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema_version": 1,
            **trigger,
            "status": "collecting",
            "sample_fps": self.settings.sample_fps,
            "pre_seconds": self.settings.pre_seconds,
            "post_seconds": self.settings.post_seconds,
            "expected_frames": self.settings.expected_frames,
            "frame_count": 0,
            "coverage_percent": 0.0,
            "dropped_frames": 0,
            "started_at": datetime.now().astimezone().isoformat(),
            "completed_at": None,
            "failure_reason": None,
            "cover_frame_id": None,
            "frames": [],
        }
        self._writer_events[command.evidence_id] = {
            "dir": event_dir,
            "manifest": manifest,
        }
        if not self._ensure_space({command.evidence_id}):
            manifest["status"] = "failed"
            manifest["failure_reason"] = "low_disk_no_deletable_evidence"
            self._write_manifest(command.evidence_id)
            with self._lock:
                self._counters["events_failed"] += 1
            return
        self._write_manifest(command.evidence_id)
        for frame in payload["pre_frames"]:
            self._persist_frame(command.evidence_id, frame)
        with self._lock:
            self._counters["events_started"] += 1

    def _writer_frame(self, command):
        context = self._writer_events.get(command.evidence_id)
        if not context or context["manifest"]["status"] != "collecting":
            return
        if not self._ensure_space(set(self._writer_events)):
            context["manifest"]["status"] = "failed"
            context["manifest"]["failure_reason"] = (
                "low_disk_no_deletable_evidence"
            )
            self._write_manifest(command.evidence_id)
            with self._lock:
                self._counters["events_failed"] += 1
            return
        self._persist_frame(command.evidence_id, command.payload)

    def _persist_frame(self, evidence_id, frame):
        context = self._writer_events[evidence_id]
        manifest = context["manifest"]
        if manifest["status"] != "collecting":
            return
        relative_seconds = (
            frame.timestamp - datetime.fromisoformat(manifest["alert_at"])
        ).total_seconds()
        frame_id = (
            f"{frame.frame_seq}_{int(frame.timestamp.timestamp() * 1000000)}_"
            f"{frame.sha256[:12]}"
        )
        filename = f"{frame_id}.jpg"
        image_path = context["dir"] / "frames" / filename
        temporary = image_path.with_name(
            f".{image_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as stream:
                stream.write(frame.jpeg)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, image_path)
        finally:
            temporary.unlink(missing_ok=True)
        row = {
            "frame_id": frame_id,
            "timestamp": frame.timestamp.isoformat(),
            "frame_seq": frame.frame_seq,
            "relative_seconds": round(relative_seconds, 3),
            "raw_people": frame.raw_people,
            "people": frame.people,
            "sha256": frame.sha256,
            "file": f"frames/{filename}",
        }
        manifest["frames"].append(row)
        manifest["frame_count"] = len(manifest["frames"])
        manifest["coverage_percent"] = round(
            min(100.0, manifest["frame_count"] / manifest["expected_frames"] * 100),
            1,
        )
        cover = manifest.get("cover_frame_id")
        if cover is None:
            manifest["cover_frame_id"] = frame_id
        else:
            current = next(
                item for item in manifest["frames"] if item["frame_id"] == cover
            )
            if abs(relative_seconds) < abs(current["relative_seconds"]):
                manifest["cover_frame_id"] = frame_id
        self._write_manifest(evidence_id)

    def _writer_finish(self, command):
        context = self._writer_events.get(command.evidence_id)
        if not context:
            return
        manifest = context["manifest"]
        if manifest["status"] == "collecting":
            manifest["status"] = command.payload["status"]
        manifest["dropped_frames"] += int(command.payload["dropped_frames"])
        manifest["completed_at"] = datetime.now().astimezone().isoformat()
        frames = manifest["frames"]
        manifest["actual_start_at"] = frames[0]["timestamp"] if frames else None
        manifest["actual_end_at"] = frames[-1]["timestamp"] if frames else None
        self._write_manifest(command.evidence_id)
        with self._lock:
            key = (
                "events_completed"
                if manifest["status"] == "complete"
                else "events_interrupted"
                if manifest["status"] == "interrupted"
                else None
            )
            if key:
                self._counters[key] += 1
        self._writer_events.pop(command.evidence_id, None)

    def _write_manifest(self, evidence_id):
        context = self._writer_events[evidence_id]
        _atomic_json(context["dir"] / "manifest.json", context["manifest"])

    def _mark_writer_failed(self, evidence_id, error):
        context = self._writer_events.get(evidence_id)
        if not context:
            return
        manifest = context["manifest"]
        manifest["status"] = "failed"
        manifest["failure_reason"] = f"{type(error).__name__}:{error}"
        try:
            self._write_manifest(evidence_id)
        except OSError:
            pass
        with self._lock:
            self._counters["events_failed"] += 1

    def _manifest_paths(self):
        if not self.root.exists():
            return []
        return sorted(self.root.glob("????-??-??/*/manifest.json"))

    def _recover_interrupted(self):
        for path in self._manifest_paths():
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") != "collecting":
                continue
            manifest["status"] = "interrupted"
            manifest["completed_at"] = datetime.now().astimezone().isoformat()
            manifest["failure_reason"] = "process_restart"
            _atomic_json(path, manifest)

    def _cleanup_storage(self, now):
        cutoff = now - timedelta(days=self.settings.retention_days)
        records = self._deletable_records()
        for record in records:
            if record["alert_at"] < cutoff:
                self._delete_event(record["path"].parent)
        self._last_cleanup_epoch = time.time()
        self._ensure_space(set(self._writer_events))

    def _deletable_records(self):
        rows = []
        for path in self._manifest_paths():
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                alert_at = datetime.fromisoformat(manifest["alert_at"])
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
            if manifest.get("status") != "complete":
                continue
            rows.append({"path": path, "alert_at": alert_at})
        return sorted(rows, key=lambda row: row["alert_at"])

    def _ensure_space(self, protected_ids):
        if shutil.disk_usage(self.root).free >= self.settings.min_free_bytes:
            return True
        for record in self._deletable_records():
            evidence_id = record["path"].parent.name
            if evidence_id in protected_ids:
                continue
            self._delete_event(record["path"].parent)
            if (
                shutil.disk_usage(self.root).free
                >= self.settings.cleanup_target_free_bytes
            ):
                return True
        return shutil.disk_usage(self.root).free >= self.settings.min_free_bytes

    def _delete_event(self, event_dir):
        event_dir = event_dir.resolve()
        if self.root not in event_dir.parents:
            raise ValueError("Directorio de evidencia fuera de la raiz")
        deleting = event_dir.with_name(
            f".deleting-{event_dir.name}-{uuid.uuid4().hex}"
        )
        try:
            os.replace(event_dir, deleting)
        except FileNotFoundError:
            return
        shutil.rmtree(deleting)
        try:
            event_dir.parent.rmdir()
        except OSError:
            pass
        with self._lock:
            self._counters["events_deleted"] += 1

    def wait_until_idle(self, timeout=5.0):
        """Espera solamente trabajos ya encolados; se usa fuera de inferencia."""
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            if (
                self._input_queue.unfinished_tasks == 0
                and self._write_queue.unfinished_tasks == 0
            ):
                return True
            time.sleep(0.01)
        return (
            self._input_queue.unfinished_tasks == 0
            and self._write_queue.unfinished_tasks == 0
        )

    def close(self, timeout=10.0):
        """Drena ambas colas fuera del ciclo de inferencia."""
        deadline = time.monotonic() + float(timeout)
        self._encoder_stop.set()
        self._encoder.join(timeout=max(0.0, deadline - time.monotonic()))
        self._writer_stop.set()
        self._writer.join(timeout=max(0.0, deadline - time.monotonic()))
        return not self._encoder.is_alive() and not self._writer.is_alive()
