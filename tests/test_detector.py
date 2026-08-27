import importlib
import json
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path


class FakeTensor:
    def cpu(self):
        return self

    def tolist(self):
        return [[1.0, 2.0, 30.0, 40.0]]


class FakeVectorTensor(FakeTensor):
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class FakeBoxes:
    xyxy = FakeTensor()
    conf = FakeVectorTensor([1.0])
    cls = FakeVectorTensor([0.0])

    def __len__(self):
        return 1


class FakeModel:
    def __init__(self, path=""):
        self.path = path
        self.kwargs = None

    def predict(self, frame, **kwargs):
        self.kwargs = kwargs
        count = len(frame) if isinstance(frame, list) else 1
        return [
            types.SimpleNamespace(
                boxes=FakeBoxes(),
                speed={"preprocess": 1.25, "inference": 8.5, "postprocess": 0.75},
            )
            for _ in range(count)
        ]


class DetectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_ultralytics = types.ModuleType("ultralytics")
        fake_ultralytics.YOLO = FakeModel
        cls.previous = sys.modules.get("ultralytics")
        sys.modules["ultralytics"] = fake_ultralytics
        sys.modules.pop("vision.detector", None)
        cls.detector = importlib.import_module("vision.detector")

    @classmethod
    def tearDownClass(cls):
        if cls.previous is None:
            sys.modules.pop("ultralytics", None)
        else:
            sys.modules["ultralytics"] = cls.previous

    def config(self):
        return {"device": 0, "confidence": 0.4, "imgsz": 640}

    def write_engine(self, path, batch=8, dynamic=True):
        metadata = json.dumps({
            "batch": batch,
            "imgsz": [640, 640],
            "args": {
                "batch": batch,
                "dynamic": dynamic,
                "quantize": 16,
            },
        }).encode("utf-8")
        path.write_bytes(struct.pack("<I", len(metadata)) + metadata + b"engine")

    def test_detect_uses_fixed_tensorrt_input_shape(self):
        model = FakeModel()
        detections = self.detector.detect(model, object(), self.config())
        self.assertEqual(detections[0].box, [1.0, 2.0, 30.0, 40.0])
        self.assertEqual(detections[0].confidence, 1.0)
        self.assertFalse(model.kwargs["rect"])
        self.assertEqual(model.kwargs["classes"], [0])

    def test_detect_batch_preserves_result_alignment(self):
        model = FakeModel()
        detections, timings = self.detector.detect_batch(
            model, [object(), object(), object()], self.config(), with_timing=True
        )
        self.assertEqual(len(detections), 3)
        self.assertEqual(len(timings), 3)
        self.assertEqual(model.kwargs["batch"], 3)
        self.assertEqual(detections[2][0].class_id, 0)

    def test_detect_can_return_internal_stage_timings(self):
        model = FakeModel()
        detections, timings = self.detector.detect(
            model, object(), self.config(), with_timing=True
        )
        self.assertEqual(len(detections), 1)
        self.assertEqual(timings["preprocess_ms"], 1.25)
        self.assertEqual(timings["inference_ms"], 8.5)
        self.assertEqual(timings["postprocess_ms"], 0.75)

    def test_loader_selects_configured_file(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.touch()
            model = self.detector.load_detector({"tensorrt_engine": str(engine)})
            self.assertEqual(model.path, str(engine))

    def test_reads_and_validates_dynamic_batch_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "batch.engine"
            self.write_engine(engine)
            capabilities = self.detector.read_engine_capabilities(engine)
            self.assertEqual(capabilities.batch_size, 8)
            self.assertTrue(capabilities.dynamic)
            self.assertEqual(capabilities.imgsz, (640, 640))
            self.assertEqual(capabilities.precision, "fp16")
            validated = self.detector.validate_engine_for_batching(
                {"tensorrt_engine": str(engine)},
                types.SimpleNamespace(enabled=True, max_batch_size=8),
            )
            self.assertEqual(validated, capabilities)

    def test_rejects_engine_with_different_image_size(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "batch.engine"
            self.write_engine(engine)
            with self.assertRaisesRegex(ValueError, "se solicito 320"):
                self.detector.validate_engine_for_batching(
                    {"tensorrt_engine": str(engine), "imgsz": 320},
                    types.SimpleNamespace(enabled=False, max_batch_size=1),
                )

    def test_rejects_fixed_or_undersized_batch_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "batch.engine"
            settings = types.SimpleNamespace(enabled=True, max_batch_size=8)
            self.write_engine(engine, batch=8, dynamic=False)
            with self.assertRaisesRegex(ValueError, "dynamic=true"):
                self.detector.validate_engine_for_batching(
                    {"tensorrt_engine": str(engine)}, settings
                )
            self.write_engine(engine, batch=4, dynamic=True)
            with self.assertRaisesRegex(ValueError, "batch maximo 4"):
                self.detector.validate_engine_for_batching(
                    {"tensorrt_engine": str(engine)}, settings
                )


if __name__ == "__main__":
    unittest.main()
