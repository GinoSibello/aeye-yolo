import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.alert_evidence import AlertEvidenceStore, build_alert_evidence_router


class AlertEvidenceApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = AlertEvidenceStore(self.root, enabled=True)
        app = FastAPI()
        app.include_router(build_alert_evidence_router(self.store))
        self.client = TestClient(app)

    def tearDown(self):
        self.temporary.cleanup()

    def write_event(
        self,
        evidence_id,
        camera_id="cam01",
        timestamp="10:00:00",
        status="complete",
    ):
        event_dir = self.root / "2026-09-16" / evidence_id
        frames_dir = event_dir / "frames"
        frames_dir.mkdir(parents=True)
        frame_id = f"1_1000000_{evidence_id[:12]}"
        filename = f"{frame_id}.jpg"
        (frames_dir / filename).write_bytes(b"\xff\xd8test\xff\xd9")
        manifest = {
            "schema_version": 1,
            "evidence_id": evidence_id,
            "camera_id": camera_id,
            "camera_name": f"Puesto {camera_id}",
            "alert_at": f"2026-09-16T{timestamp}+00:00",
            "kind": "missing",
            "reason": "faltantes",
            "status": status,
            "expected_frames": 60,
            "frame_count": 1,
            "coverage_percent": 1.7,
            "cover_frame_id": frame_id,
            "frames": [{
                "frame_id": frame_id,
                "timestamp": f"2026-09-16T{timestamp}+00:00",
                "frame_seq": 1,
                "relative_seconds": 0.0,
                "raw_people": 0,
                "people": 0,
                "sha256": "a" * 64,
                "file": f"frames/{filename}",
            }],
        }
        (event_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return frame_id, event_dir

    def test_list_filters_sorts_and_paginates(self):
        self.write_event("a" * 32, camera_id="cam01", timestamp="10:00:00")
        self.write_event("b" * 32, camera_id="cam02", timestamp="11:00:00")

        response = self.client.get(
            "/api/alert-evidence",
            params={"day": "2026-09-16", "offset": 0, "limit": 1},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["items"][0]["camera_id"], "cam02")
        self.assertNotIn("frames", payload["items"][0])

        filtered = self.client.get(
            "/api/alert-evidence",
            params={"day": "2026-09-16", "camera_id": "cam01"},
        ).json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["camera_id"], "cam01")

        self.assertEqual(len(filtered["cameras"]), 2)

    def test_partial_event_and_query_limits_are_explicit(self):
        self.write_event("f" * 32, status="collecting")
        response = self.client.get(
            "/api/alert-evidence", params={"day": "2026-09-16"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["status"], "collecting")
        self.assertEqual(
            self.client.get(
                "/api/alert-evidence",
                params={"day": "2026-09-16", "limit": 101},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                "/api/alert-evidence", params={"day": "no-es-fecha"}
            ).status_code,
            422,
        )

    def test_detail_and_jpeg_do_not_expose_filesystem_paths(self):
        evidence_id = "c" * 32
        frame_id, _ = self.write_event(evidence_id)
        detail = self.client.get(
            f"/api/alert-evidence/{evidence_id}"
        )
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertNotIn("file", payload["frames"][0])
        self.assertEqual(
            payload["frames"][0]["url"],
            f"/api/alert-evidence/{evidence_id}/frames/{frame_id}",
        )
        image = self.client.get(payload["frames"][0]["url"])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/jpeg")

    def test_invalid_ids_missing_files_and_traversal_are_rejected(self):
        with self.assertRaises(HTTPException):
            self.store.detail("../secreto")
        evidence_id = "d" * 32
        frame_id, event_dir = self.write_event(evidence_id)
        manifest_path = event_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["frames"][0]["file"] = "../../cameras.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        response = self.client.get(
            f"/api/alert-evidence/{evidence_id}/frames/{frame_id}"
        )
        self.assertEqual(response.status_code, 404)

    def test_event_removed_between_requests_returns_404(self):
        evidence_id = "e" * 32
        _, event_dir = self.write_event(evidence_id)
        self.assertEqual(
            self.client.get(f"/api/alert-evidence/{evidence_id}").status_code,
            200,
        )
        for path in sorted(event_dir.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        event_dir.rmdir()
        self.assertEqual(
            self.client.get(f"/api/alert-evidence/{evidence_id}").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
