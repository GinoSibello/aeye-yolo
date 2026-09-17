"""Lectura segura de manifiestos e imagenes de evidencia de alertas."""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response


EVIDENCE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
FRAME_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,220}$")


class AlertEvidenceStore:
    """Expone solo archivos declarados por manifiestos bajo una raiz fija."""

    def __init__(self, root, enabled=False):
        self.root = Path(root).resolve()
        self.enabled = bool(enabled)

    def _load(self, path):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(404, "Evidencia no disponible") from error
        if not isinstance(row, dict):
            raise HTTPException(404, "Evidencia no disponible")
        return row

    def _load_manifest(self, path, expected_id=None):
        manifest = self._load(path)
        directory_id = path.parent.name
        if (
            not EVIDENCE_ID_RE.fullmatch(directory_id)
            or manifest.get("evidence_id") != directory_id
            or (expected_id is not None and directory_id != expected_id)
        ):
            raise HTTPException(404, "Evidencia no disponible")
        return manifest

    def _manifest_path(self, evidence_id):
        if not EVIDENCE_ID_RE.fullmatch(str(evidence_id)):
            raise HTTPException(404, "Evidencia no encontrada")
        matches = list(self.root.glob(f"????-??-??/{evidence_id}/manifest.json"))
        if len(matches) != 1:
            raise HTTPException(404, "Evidencia no encontrada")
        return matches[0]

    def _frame_url(self, evidence_id, frame_id):
        return f"/api/alert-evidence/{evidence_id}/frames/{frame_id}"

    def _public_detail(self, manifest):
        evidence_id = str(manifest.get("evidence_id", ""))
        frames = []
        for frame in manifest.get("frames", []):
            if not isinstance(frame, dict):
                continue
            frame_id = str(frame.get("frame_id", ""))
            if not FRAME_ID_RE.fullmatch(frame_id):
                continue
            frames.append({
                key: frame.get(key)
                for key in (
                    "frame_id",
                    "timestamp",
                    "frame_seq",
                    "relative_seconds",
                    "raw_people",
                    "people",
                    "sha256",
                )
            } | {"url": self._frame_url(evidence_id, frame_id)})
        public = {
            key: manifest.get(key)
            for key in (
                "schema_version",
                "evidence_id",
                "camera_id",
                "camera_name",
                "alert_at",
                "kind",
                "reason",
                "raw_people",
                "people",
                "expected_min",
                "expected_max",
                "outside_range_seconds",
                "status",
                "sample_fps",
                "pre_seconds",
                "post_seconds",
                "expected_frames",
                "frame_count",
                "coverage_percent",
                "dropped_frames",
                "started_at",
                "completed_at",
                "failure_reason",
                "cover_frame_id",
                "actual_start_at",
                "actual_end_at",
            )
        }
        public["frames"] = frames
        cover_id = public.get("cover_frame_id")
        public["cover_url"] = (
            self._frame_url(evidence_id, cover_id)
            if cover_id and FRAME_ID_RE.fullmatch(str(cover_id)) else None
        )
        return public

    def list(self, day, camera_id=None, offset=0, limit=50):
        all_rows = []
        day_dir = self.root / day.isoformat()
        if day_dir.is_dir():
            for path in day_dir.glob("*/manifest.json"):
                try:
                    manifest = self._load_manifest(path)
                except HTTPException:
                    continue
                detail = self._public_detail(manifest)
                detail.pop("frames", None)
                detail["detail_url"] = (
                    f"/api/alert-evidence/{detail['evidence_id']}"
                )
                all_rows.append(detail)
        cameras = sorted(
            {
                (str(row.get("camera_id")), str(row.get("camera_name")))
                for row in all_rows if row.get("camera_id")
            }
        )
        rows = [
            row for row in all_rows
            if not camera_id or row.get("camera_id") == camera_id
        ]
        rows.sort(key=lambda row: str(row.get("alert_at") or ""), reverse=True)
        total = len(rows)
        return {
            "enabled": self.enabled,
            "day": day.isoformat(),
            "generated_at": datetime.now().astimezone().isoformat(),
            "camera_id": camera_id,
            "cameras": [
                {"camera_id": camera, "camera_name": name}
                for camera, name in cameras
            ],
            "offset": offset,
            "limit": limit,
            "total": total,
            "items": rows[offset:offset + limit],
        }

    def detail(self, evidence_id):
        path = self._manifest_path(evidence_id)
        return self._public_detail(self._load_manifest(path, evidence_id))

    def frame_bytes(self, evidence_id, frame_id):
        if not FRAME_ID_RE.fullmatch(str(frame_id)):
            raise HTTPException(404, "Frame no encontrado")
        manifest_path = self._manifest_path(evidence_id)
        manifest = self._load_manifest(manifest_path, evidence_id)
        matching = [
            row for row in manifest.get("frames", [])
            if isinstance(row, dict) and row.get("frame_id") == frame_id
        ]
        if len(matching) != 1:
            raise HTTPException(404, "Frame no encontrado")
        relative = Path(str(matching[0].get("file", "")))
        if relative.is_absolute() or relative.parts[:1] != ("frames",):
            raise HTTPException(404, "Frame no encontrado")
        frames_root = (manifest_path.parent / "frames").resolve()
        path = (manifest_path.parent / relative).resolve()
        if frames_root not in path.parents or not path.is_file():
            raise HTTPException(404, "Frame no encontrado")
        try:
            return path.read_bytes()
        except OSError as error:
            raise HTTPException(404, "Frame no encontrado") from error


def build_alert_evidence_router(store):
    router = APIRouter()

    @router.get("/api/alert-evidence")
    def list_evidence(
        day: Optional[date] = None,
        camera_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        return store.list(day or date.today(), camera_id, offset, limit)

    @router.get("/api/alert-evidence/{evidence_id}")
    def evidence_detail(evidence_id: str):
        return store.detail(evidence_id)

    @router.get("/api/alert-evidence/{evidence_id}/frames/{frame_id}")
    def evidence_frame(evidence_id: str, frame_id: str):
        content = store.frame_bytes(evidence_id, frame_id)
        return Response(
            content=content,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=60"},
        )

    return router
