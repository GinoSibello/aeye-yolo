import unittest

from vision.tracker import tracked_detections


class TrackerTest(unittest.TestCase):
    def test_bytetrack_rows_keep_box_id_and_confidence(self):
        tracks = tracked_detections([[1, 2, 30, 40, 7, 0.85, 0, 0]])
        self.assertEqual(tracks[0].box, [1.0, 2.0, 30.0, 40.0])
        self.assertEqual(tracks[0].track_id, 7)
        self.assertAlmostEqual(tracks[0].confidence, 0.85)


if __name__ == "__main__":
    unittest.main()
