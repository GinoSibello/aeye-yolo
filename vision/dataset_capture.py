"""Recolector opcional y no bloqueante de frames inferidos para auditoria."""

from __future__ import annotations

import cv2
import hashlib
import json
import os
import queue
import re
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


JPEG_QUALITY = 92


@dataclass(frozen=True)
class DatasetCaptureSettings:
    """Configuracion validada del recolector de dataset."""

    enabled: bool = False
    root: Path = Path("datasets/aeye_capture")
    sample_fps: float = 2.0
    pre_seconds: float = 2.0
    post_seconds: float = 2.0
    prolonged_interval_seconds: float = 10.0
    audit_interval_seconds: float = 300.0
    collection_window_minutes: float = 120.0
    quota_per_camera_per_window: int = 50
    queue_size: int = 64
    min_free_bytes: int = 5 * 1024**3


@dataclass
class FrameCandidate:
    camera_id: str
    frame_seq: int
    timestamp: datetime
    frame: object
    boxes: list


@dataclass
class CaptureTask:
    candidate: FrameCandidate
    event_id: str | None
    reason: str
    frame_key: tuple
    collection_window_id: str
    collection_window_start: str
    collection_window_end: str


@dataclass
class CameraCaptureState:
    prebuffer: deque = field(default_factory=deque)
    last_buffer_at: float | None = None
    event_id: str | None = None
    present: bool = False
    last_detection_at: float | None = None
    post_until: float | None = None
    last_presence_sample_at: float | None = None
    last_context_sample_at: float | None = None
    last_audit_at: float | None = None
    collection_window_id: str | None = None


class LowDiskError(RuntimeError):
    """Detiene solamente el recolector cuando no queda margen de disco."""


def parse_dataset_capture_settings(system_cfg):
    """Normaliza limites sin crear directorios cuando la funcion esta apagada."""
    values = dict(system_cfg.get("dataset_capture", {}) or {})

    def positive(name, default):
        value = float(values.get(name, default))
        if value <= 0:
            raise ValueError(f"dataset_capture.{name} debe ser mayor que cero")
        return value

    quota = int(values.get("quota_per_camera_per_window", 50))
    queue_size = int(values.get("queue_size", 64))
    if quota < 1:
        raise ValueError(
            "dataset_capture.quota_per_camera_per_window debe ser al menos 1"
        )
    if queue_size < 1:
        raise ValueError("dataset_capture.queue_size debe ser al menos 1")
    min_free_gb = float(values.get("min_free_gb", 5.0))
    if min_free_gb < 0:
        raise ValueError("dataset_capture.min_free_gb no puede ser negativo")

    return DatasetCaptureSettings(
        enabled=bool(values.get("enabled", False)),
        root=Path(values.get("root", "datasets/aeye_capture")),
        sample_fps=positive("sample_fps", 2.0),
        pre_seconds=positive("pre_seconds", 2.0),
        post_seconds=positive("post_seconds", 2.0),
        prolonged_interval_seconds=positive(
            "prolonged_interval_seconds", 10.0
        ),
        audit_interval_seconds=positive("audit_interval_seconds", 300.0),
        collection_window_minutes=positive("collection_window_minutes", 120.0),
        quota_per_camera_per_window=quota,
        queue_size=queue_size,
        min_free_bytes=int(min_free_gb * 1024**3),
    )


def _proposal_rows(detections):
    return [
        {
            "xyxy": [round(float(value), 4) for value in detection.box],
            "confidence": round(float(detection.confidence), 6),
            "class_id": int(detection.class_id),
        }
        for detection in detections
    ]


def _camera_directory(camera_id):
    """Impide que un identificador de configuracion se convierta en una ruta."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(camera_id)).strip("._")
    if safe == str(camera_id) and safe:
        return safe
    digest = hashlib.sha256(str(camera_id).encode("utf-8")).hexdigest()[:8]
    return f"{safe or 'camera'}_{digest}"


class DatasetCaptureCollector:
    """Selecciona ventanas en memoria y delega JPEG/IO a un hilo acotado."""

    def __init__(
        self,
        settings,
        engine,
        confidence,
        logger=None,
        session_id=None,
    ):
        self.settings = settings
        self.root = settings.root.resolve()
        self.engine = Path(engine).name
        self.confidence = float(confidence)
        self.logger = logger or (lambda message: None)
        self.session_id = session_id or uuid.uuid4().hex
        self.index_path = self.root / "capture_index.jsonl"
        self.status_path = self.root / "status.json"
        self._queue = queue.Queue(maxsize=settings.queue_size)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._states = {}
        self._hashes = set()
        self._seen_frame_keys = set()
        self._reserved_frame_keys = set()
        self._saved_by_camera = {}
        self._pending_by_camera = {}
        self._saved_by_window = {}
        self._pending_by_window = {}
        self._disabled_reason = None
        self._counters = {
            "saved": 0,
            "duplicate_frame": 0,
            "duplicate_hash": 0,
            "quota_reached": 0,
            "queue_full": 0,
            "write_errors": 0,
        }

        self.root.mkdir(parents=True, exist_ok=True)
        self._load_index()
        self._worker = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="dataset-capture-writer",
        )
        self._worker.start()
        self._write_status()

    @property
    def enabled(self):
        with self._lock:
            return self._disabled_reason is None

    @property
    def disabled_reason(self):
        with self._lock:
            return self._disabled_reason

    def snapshot(self):
        with self._lock:
            return {
                "enabled": self._disabled_reason is None,
                "disabled_reason": self._disabled_reason,
                "queue_size": self._queue.qsize(),
                "saved_by_camera": dict(self._saved_by_camera),
                "saved_by_window": {
                    f"{camera_id}|{window_id}": count
                    for (camera_id, window_id), count in self._saved_by_window.items()
                },
                **self._counters,
            }

    def _state(self, camera_id):
        return self._states.setdefault(str(camera_id), CameraCaptureState())

    def _load_index(self):
        if not self.index_path.exists():
            return
        with self.index_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    camera_id = str(row["camera_id"])
                    sha256 = str(row["sha256"])
                    session_id = str(row["session_id"])
                    frame_seq = int(row["frame_seq"])
                    timestamp = datetime.fromisoformat(row["timestamp"])
                    collection_window_id = str(
                        row.get("collection_window_id") or "legacy"
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise ValueError(
                        f"Indice de captura invalido en linea {line_number}"
                    ) from error
                self._hashes.add(sha256)
                self._seen_frame_keys.add((session_id, camera_id, frame_seq))
                self._saved_by_camera[camera_id] = (
                    self._saved_by_camera.get(camera_id, 0) + 1
                )
                window_key = (camera_id, collection_window_id)
                self._saved_by_window[window_key] = (
                    self._saved_by_window.get(window_key, 0) + 1
                )
                if "audit" in str(row.get("reason", "")).split("+"):
                    state = self._state(camera_id)
                    epoch = timestamp.timestamp()
                    if state.last_audit_at is None:
                        state.last_audit_at = epoch
                    else:
                        state.last_audit_at = max(state.last_audit_at, epoch)

    def _status_payload(self):
        with self._lock:
            return {
                "schema_version": 1,
                "session_id": self.session_id,
                "enabled": self._disabled_reason is None,
                "disabled_reason": self._disabled_reason,
                "updated_at": datetime.now().astimezone().isoformat(),
                "saved_by_camera": dict(self._saved_by_camera),
                "saved_by_window": {
                    f"{camera_id}|{window_id}": count
                    for (camera_id, window_id), count in self._saved_by_window.items()
                },
                "counters": dict(self._counters),
            }

    def _write_status(self):
        payload = self._status_payload()
        temporary = self.status_path.with_name(
            f".{self.status_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.status_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _disable(self, reason):
        with self._lock:
            if self._disabled_reason is not None:
                return
            self._disabled_reason = str(reason)
        try:
            self._write_status()
        except OSError:
            pass
        self.logger(f"Captura de dataset detenida: {reason}")

    def _candidate(self, camera_id, frame_seq, timestamp, frame, detections):
        return FrameCandidate(
            camera_id=str(camera_id),
            frame_seq=int(frame_seq),
            timestamp=timestamp,
            frame=frame.copy(),
            boxes=_proposal_rows(detections),
        )

    def observe(
        self,
        camera_id,
        frame_seq,
        timestamp,
        frame,
        detections,
        collection_window,
    ):
        """Recibe un frame ya inferido y no espera por JPEG, disco ni cola."""
        if not self.enabled:
            return
        try:
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("timestamp de captura debe incluir zona horaria")
            camera_id = str(camera_id)
            if collection_window is None:
                self._states.pop(camera_id, None)
                return

            epoch = timestamp.timestamp()
            window_id = str(collection_window["id"])
            window_start = collection_window["start"]
            window_end = collection_window["end"]
            if (
                window_start.tzinfo is None
                or window_end.tzinfo is None
                or not window_start <= timestamp.astimezone(window_start.tzinfo)
                < window_end
            ):
                raise ValueError("ventana de captura invalida para el timestamp")

            state = self._state(camera_id)
            if state.collection_window_id != window_id:
                state = CameraCaptureState(collection_window_id=window_id)
                self._states[camera_id] = state

            cutoff = epoch - self.settings.pre_seconds
            while state.prebuffer and state.prebuffer[0][0] < cutoff:
                state.prebuffer.popleft()

            has_person = bool(detections)
            current_reasons = []
            current_event_id = state.event_id
            clear_prebuffer = False

            if has_person:
                expired = (
                    not state.present
                    and state.post_until is not None
                    and epoch > state.post_until
                )
                if state.event_id is None or expired:
                    state.event_id = uuid.uuid4().hex
                    state.present = True
                    state.post_until = None
                    state.last_context_sample_at = None
                    state.last_presence_sample_at = epoch
                    current_event_id = state.event_id
                    for _, candidate in list(state.prebuffer):
                        self._submit(
                            candidate,
                            state.event_id,
                            "pre_context",
                            collection_window,
                        )
                    current_reasons.append("presence_start")
                    clear_prebuffer = True
                elif not state.present:
                    state.present = True
                    state.post_until = None
                    state.last_context_sample_at = None
                    state.last_presence_sample_at = epoch
                    current_event_id = state.event_id
                    current_reasons.append("presence_reappeared")
                    clear_prebuffer = True
                elif (
                    state.last_presence_sample_at is None
                    or epoch - state.last_presence_sample_at
                    >= self.settings.prolonged_interval_seconds
                ):
                    state.last_presence_sample_at = epoch
                    current_event_id = state.event_id
                    current_reasons.append("presence_prolonged")
                state.last_detection_at = epoch
            elif state.event_id is not None:
                if state.present:
                    state.present = False
                    state.post_until = (
                        state.last_detection_at + self.settings.post_seconds
                    )
                    state.last_context_sample_at = None
                if state.post_until is not None and epoch < state.post_until:
                    interval = 1.0 / self.settings.sample_fps
                    if (
                        state.last_context_sample_at is None
                        or epoch - state.last_context_sample_at >= interval
                    ):
                        state.last_context_sample_at = epoch
                        current_event_id = state.event_id
                        current_reasons.append("post_context")
                elif state.post_until is not None and epoch >= state.post_until:
                    state.event_id = None
                    state.post_until = None
                    state.last_presence_sample_at = None
                    state.last_context_sample_at = None
                    current_event_id = None

            if (
                state.last_audit_at is None
                or epoch - state.last_audit_at
                >= self.settings.audit_interval_seconds
            ):
                current_reasons.append("audit")

            window_key = (camera_id, window_id)
            with self._lock:
                accepted = (
                    self._saved_by_window.get(window_key, 0)
                    + self._pending_by_window.get(window_key, 0)
                )
            scheduled_interval = (
                float(collection_window["duration_seconds"])
                / self.settings.quota_per_camera_per_window
            )
            if (
                accepted < self.settings.quota_per_camera_per_window
                and epoch >= window_start.timestamp() + accepted * scheduled_interval
            ):
                current_reasons.append("scheduled")

            interval = 1.0 / self.settings.sample_fps
            needs_buffer = (
                state.last_buffer_at is None
                or epoch - state.last_buffer_at >= interval
            )
            candidate = None
            if needs_buffer or current_reasons:
                candidate = self._candidate(
                    camera_id, frame_seq, timestamp, frame, detections
                )

            if current_reasons:
                submitted = self._submit(
                    candidate,
                    current_event_id,
                    "+".join(sorted(set(current_reasons))),
                    collection_window,
                )
                if submitted and "audit" in current_reasons:
                    state.last_audit_at = epoch

            if clear_prebuffer:
                state.prebuffer.clear()
            elif needs_buffer:
                state.prebuffer.append((epoch, candidate))
            if needs_buffer:
                state.last_buffer_at = epoch
        except Exception as error:
            with self._lock:
                self._counters["write_errors"] += 1
            self._disable(f"collector_error:{type(error).__name__}:{error}")

    def _submit(self, candidate, event_id, reason, collection_window):
        frame_key = (
            self.session_id,
            candidate.camera_id,
            candidate.frame_seq,
        )
        window_id = str(collection_window["id"])
        window_key = (candidate.camera_id, window_id)
        with self._lock:
            if self._disabled_reason is not None:
                return False
            if (
                frame_key in self._seen_frame_keys
                or frame_key in self._reserved_frame_keys
            ):
                self._counters["duplicate_frame"] += 1
                return False
            saved = self._saved_by_window.get(window_key, 0)
            pending = self._pending_by_window.get(window_key, 0)
            if (
                saved + pending
                >= self.settings.quota_per_camera_per_window
            ):
                self._counters["quota_reached"] += 1
                return False
            task = CaptureTask(
                candidate=candidate,
                event_id=event_id,
                reason=reason,
                frame_key=frame_key,
                collection_window_id=window_id,
                collection_window_start=collection_window["start"].isoformat(),
                collection_window_end=collection_window["end"].isoformat(),
            )
            try:
                self._queue.put_nowait(task)
            except queue.Full:
                self._counters["queue_full"] += 1
                return False
            self._reserved_frame_keys.add(frame_key)
            self._pending_by_camera[candidate.camera_id] = (
                self._pending_by_camera.get(candidate.camera_id, 0) + 1
            )
            self._pending_by_window[window_key] = pending + 1
            return True

    def _writer_loop(self):
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                task = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            completed = False
            try:
                if self.enabled:
                    self._write_task(task)
                    completed = True
            except LowDiskError as error:
                self._disable(f"low_disk:{error}")
            except Exception as error:
                with self._lock:
                    self._counters["write_errors"] += 1
                self._disable(f"write_error:{type(error).__name__}:{error}")
            finally:
                with self._lock:
                    camera_id = task.candidate.camera_id
                    self._pending_by_camera[camera_id] = max(
                        0, self._pending_by_camera.get(camera_id, 1) - 1
                    )
                    window_key = (camera_id, task.collection_window_id)
                    self._pending_by_window[window_key] = max(
                        0,
                        self._pending_by_window.get(window_key, 1) - 1,
                    )
                    self._reserved_frame_keys.discard(task.frame_key)
                    if completed:
                        self._seen_frame_keys.add(task.frame_key)
                self._queue.task_done()

    def _write_task(self, task):
        free_bytes = shutil.disk_usage(self.root).free
        if free_bytes < self.settings.min_free_bytes:
            raise LowDiskError(
                f"libres={free_bytes} minimo={self.settings.min_free_bytes}"
            )

        ok, encoded = cv2.imencode(
            ".jpg",
            task.candidate.frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        if not ok:
            raise OSError("OpenCV no pudo codificar JPEG")
        image_bytes = encoded.tobytes()
        sha256 = hashlib.sha256(image_bytes).hexdigest()

        with self._lock:
            if sha256 in self._hashes:
                self._counters["duplicate_hash"] += 1
                return

        camera_dir = _camera_directory(task.candidate.camera_id)
        image_dir = self.root / "images" / camera_dir
        metadata_dir = self.root / "metadata" / camera_dir
        image_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        capture_id = (
            f"{self.session_id}_{camera_dir}_"
            f"{task.candidate.frame_seq}_{sha256[:12]}"
        )
        image_path = image_dir / f"{capture_id}.jpg"
        metadata_path = metadata_dir / f"{capture_id}.json"
        image_relative = image_path.relative_to(self.root).as_posix()
        metadata_relative = metadata_path.relative_to(self.root).as_posix()

        metadata = {
            "schema_version": 1,
            "capture_id": capture_id,
            "session_id": self.session_id,
            "camera_id": task.candidate.camera_id,
            "timestamp": task.candidate.timestamp.isoformat(),
            "frame_seq": task.candidate.frame_seq,
            "event_id": task.event_id,
            "reason": task.reason,
            "collection_window_id": task.collection_window_id,
            "collection_window_start": task.collection_window_start,
            "collection_window_end": task.collection_window_end,
            "engine": self.engine,
            "confidence": self.confidence,
            "boxes": task.candidate.boxes,
            "sha256": sha256,
            "image": image_relative,
        }
        index_row = {
            "schema_version": 1,
            "capture_id": capture_id,
            "session_id": self.session_id,
            "camera_id": task.candidate.camera_id,
            "timestamp": task.candidate.timestamp.isoformat(),
            "frame_seq": task.candidate.frame_seq,
            "event_id": task.event_id,
            "reason": task.reason,
            "collection_window_id": task.collection_window_id,
            "collection_window_start": task.collection_window_start,
            "collection_window_end": task.collection_window_end,
            "sha256": sha256,
            "image": image_relative,
            "metadata": metadata_relative,
        }

        image_temporary = image_path.with_name(
            f".{image_path.name}.{uuid.uuid4().hex}.tmp"
        )
        metadata_temporary = metadata_path.with_name(
            f".{metadata_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with image_temporary.open("xb") as stream:
                stream.write(image_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(image_temporary, image_path)

            with metadata_temporary.open("x", encoding="utf-8") as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(metadata_temporary, metadata_path)

            with self.index_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(index_row, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            image_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            raise
        finally:
            image_temporary.unlink(missing_ok=True)
            metadata_temporary.unlink(missing_ok=True)

        with self._lock:
            self._hashes.add(sha256)
            camera_id = task.candidate.camera_id
            self._saved_by_camera[camera_id] = (
                self._saved_by_camera.get(camera_id, 0) + 1
            )
            window_key = (camera_id, task.collection_window_id)
            self._saved_by_window[window_key] = (
                self._saved_by_window.get(window_key, 0) + 1
            )
            self._counters["saved"] += 1

    def wait_until_idle(self, timeout=5.0):
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout=5.0):
        """Drena trabajos aceptados; no se llama desde el ciclo de inferencia."""
        self._stop_event.set()
        self._worker.join(timeout=float(timeout))
        try:
            self._write_status()
        except OSError as error:
            self.logger(f"No se pudo actualizar estado de captura: {error}")
        return not self._worker.is_alive()
