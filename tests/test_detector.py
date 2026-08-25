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
        return [types.SimpleNamespace(
            boxes=FakeBoxes(),
            speed={"preprocess": 1.25, "inference": 8.5, "postprocess": 0.75},
        )]


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
        detections = self.detector.detect(model, object(), self.config())
        self.assertEqual(detections[0].box, [1.0, 2.0, 30.0, 40.0])
        self.assertEqual(detections[0].confidence, 1.0)
        self.assertFalse(model.kwargs["rect"])
        self.assertEqual(model.kwargs["classes"], [0])

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


if __name__ == "__main__":
    unittest.main()
