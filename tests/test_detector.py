import importlib
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


class FakeBoxes:
    xyxy = FakeTensor()

    def __len__(self):
        return 1


class FakeModel:
    def __init__(self, path=""):
        self.path = path
        self.kwargs = None

    def predict(self, frame, **kwargs):
        self.kwargs = kwargs
        return [types.SimpleNamespace(boxes=FakeBoxes())]


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

    def test_pytorch_function_preserves_original_predict_options(self):
        model = FakeModel()
        boxes = self.detector.detect_yolo(model, object(), self.config())
        self.assertEqual(boxes, [[1.0, 2.0, 30.0, 40.0]])
        self.assertNotIn("rect", model.kwargs)
        self.assertEqual(model.kwargs["classes"], [0])

    def test_tensorrt_function_uses_fixed_input_shape(self):
        model = FakeModel()
        boxes = self.detector.detect_tensorrt(model, object(), self.config())
        self.assertEqual(boxes, [[1.0, 2.0, 30.0, 40.0]])
        self.assertFalse(model.kwargs["rect"])

    def test_loader_selects_configured_file(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.touch()
            backend, model = self.detector.load_detector({
                "inference_backend": "tensorrt", "tensorrt_engine": str(engine)
            })
            self.assertEqual(backend, "tensorrt")
            self.assertEqual(model.path, str(engine))


if __name__ == "__main__":
    unittest.main()
