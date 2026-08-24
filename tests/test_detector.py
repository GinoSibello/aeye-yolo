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

    def test_detect_uses_fixed_tensorrt_input_shape(self):
        model = FakeModel()
        boxes = self.detector.detect(model, object(), self.config())
        self.assertEqual(boxes, [[1.0, 2.0, 30.0, 40.0]])
        self.assertFalse(model.kwargs["rect"])
        self.assertEqual(model.kwargs["classes"], [0])

    def test_loader_selects_configured_file(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.touch()
            model = self.detector.load_detector({"tensorrt_engine": str(engine)})
            self.assertEqual(model.path, str(engine))


if __name__ == "__main__":
    unittest.main()
