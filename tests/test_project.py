"""Hardware-independent tests for recognition, capture scheduling, and attendance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from camera_module import CameraError, CameraWorker, CaptureScheduler, PhotoCaptureStore
from face_recognition_module import FaceRecognitionError, FaceRecognizer


class FakeFaceRecognitionBackend:
    def face_locations(self, rgb):
        average = float(np.mean(rgb))
        if average < 1:
            return []
        if average > 150:
            return [(0, 5, 5, 0), (5, 10, 10, 5)]
        return [(0, rgb.shape[1], rgb.shape[0], 0)]

    def face_encodings(self, rgb, locations):
        value = np.array([float(np.mean(rgb))])
        return [value.copy() for _ in locations]

    @staticmethod
    def face_distance(known_encodings, candidate):
        return np.array([abs(float(encoding[0]) - float(candidate[0])) for encoding in known_encodings])


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_image(self, path: Path, value: int) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        image = np.full((32, 32, 3), value, dtype=np.uint8)
        self.assertTrue(cv2.imwrite(str(path), image))
        return path

    def test_imports_and_loads_known_face_encoding(self):
        known_dir = self.root / "Known_Faces"
        self._write_image(known_dir / "Jordan.png", 40)
        recognizer = FaceRecognizer(known_dir, backend=FakeFaceRecognitionBackend())
        self.assertEqual(recognizer.reload_known_faces(), [])
        self.assertEqual(recognizer._names, ["Jordan"])
        self.assertEqual(len(recognizer._encodings), 1)

    def test_invalid_images_are_rejected_and_skipped_during_reload(self):
        known_dir = self.root / "Known_Faces"
        known_dir.mkdir()
        (known_dir / "broken.png").write_text("not an image", encoding="utf-8")
        recognizer = FaceRecognizer(known_dir, backend=FakeFaceRecognitionBackend())
        warnings = recognizer.reload_known_faces()
        self.assertEqual(len(warnings), 1)
        with self.assertRaises(FaceRecognitionError):
            recognizer.encode_image(known_dir / "broken.png")

    def test_registration_rejects_zero_or_multiple_faces(self):
        known_dir = self.root / "Known_Faces"
        recognizer = FaceRecognizer(known_dir, backend=FakeFaceRecognitionBackend())
        zero_face = self._write_image(self.root / "zero.png", 0)
        multiple_faces = self._write_image(self.root / "multiple.png", 200)
        with self.assertRaisesRegex(FaceRecognitionError, "No face"):
            recognizer.register_face(zero_face, "Nobody")
        with self.assertRaisesRegex(FaceRecognitionError, "exactly one face"):
            recognizer.register_face(multiple_faces, "Crowd")

    def test_recognition_returns_registered_and_unknown_faces(self):
        known_dir = self.root / "Known_Faces"
        self._write_image(known_dir / "Jordan.png", 40)
        recognizer = FaceRecognizer(known_dir, backend=FakeFaceRecognitionBackend())
        recognizer.reload_known_faces()
        known_frame = np.full((32, 32, 3), 40, dtype=np.uint8)
        unknown_frame = np.full((32, 32, 3), 220, dtype=np.uint8)
        recognizer.recognize(known_frame)
        recognizer.recognize(known_frame)
        known_matches = recognizer.recognize(known_frame)
        unknown_matches = recognizer.recognize(unknown_frame)
        self.assertEqual(known_matches[0].name, "Jordan")
        self.assertTrue(known_matches[0].is_known)
        self.assertEqual(len(unknown_matches), 2)
        self.assertTrue(all(match.name == "Unknown Person" for match in unknown_matches))

    def test_registration_copies_image_and_reloads_known_faces(self):
        source = self._write_image(self.root / "source.png", 35)
        recognizer = FaceRecognizer(self.root / "Known_Faces", backend=FakeFaceRecognitionBackend())
        destination = recognizer.register_face(source, "Jordan Lee")
        self.assertTrue(destination.is_file())
        self.assertEqual(recognizer._names, ["Jordan Lee"])
        with self.assertRaisesRegex(FaceRecognitionError, "already registered"):
            recognizer.register_face(source, "jordan lee")

    def test_capture_interval_is_independent_per_person(self):
        scheduler = CaptureScheduler(5)
        self.assertTrue(scheduler.is_due("Jordan", now=10))
        scheduler.mark_captured("Jordan", now=10)
        self.assertFalse(scheduler.is_due("Jordan", now=14.9))
        self.assertTrue(scheduler.is_due("Jordan", now=15))
        self.assertTrue(scheduler.is_due("Casey", now=10))
        scheduler.set_interval(2)
        self.assertTrue(scheduler.is_due("Jordan", now=12))

    def test_photo_store_saves_timestamped_photo(self):
        store = PhotoCaptureStore(self.root / "Captured_Photos")
        path = store.save(np.zeros((16, 16, 3), dtype=np.uint8), "Jordan Lee")
        self.assertTrue(path.is_file())
        self.assertRegex(path.name, r"^Jordan Lee_\d{8}_\d{6}_\d+\.jpg$")
        self.assertEqual(store.count, 1)

    def test_manual_capture_requires_camera_frame_then_saves_explicitly(self):
        store = PhotoCaptureStore(self.root / "Captured_Photos")
        worker = CameraWorker(FaceRecognizer(self.root / "Known_Faces", backend=FakeFaceRecognitionBackend()), store)
        with self.assertRaises(CameraError):
            worker.capture_manual()

        frame = np.zeros((16, 16, 3), dtype=np.uint8)
        worker._latest_frame = frame
        worker._latest_matches = ()
        with patch.object(CameraWorker, "camera_active", new_callable=lambda: property(lambda self: True)):
            path = worker.capture_manual()
        self.assertTrue(path.is_file())
        self.assertTrue(path.name.startswith("Manual_Capture_"))
        self.assertEqual(store.count, 1)

    def test_recognition_requires_consecutive_confirmation_before_known(self):
        known_dir = self.root / "Known_Faces"
        self._write_image(known_dir / "Jordan.png", 40)
        recognizer = FaceRecognizer(
            known_dir,
            tolerance=0.48,
            confirmation_frames=3,
            backend=FakeFaceRecognitionBackend(),
        )
        recognizer.reload_known_faces()
        frame = np.full((32, 32, 3), 40, dtype=np.uint8)
        first = recognizer.recognize(frame)
        second = recognizer.recognize(frame)
        self.assertTrue(all(not match.is_known for match in first))
        self.assertTrue(all(not match.is_known for match in second))
        third = recognizer.recognize(frame)
        self.assertTrue(third[0].is_known)
        self.assertEqual(third[0].name, "Jordan")

    def test_unknown_frame_does_not_confirm_known_name(self):
        known_dir = self.root / "Known_Faces"
        self._write_image(known_dir / "Jordan.png", 40)
        recognizer = FaceRecognizer(
            known_dir,
            tolerance=0.48,
            confirmation_frames=3,
            backend=FakeFaceRecognitionBackend(),
        )
        recognizer.reload_known_faces()
        unknown = np.full((32, 32, 3), 220, dtype=np.uint8)
        for _ in range(5):
            matches = recognizer.recognize(unknown)
            self.assertTrue(all(not match.is_known for match in matches))

    def test_worker_is_off_by_default_and_interval_is_per_person(self):
        store = PhotoCaptureStore(self.root / "Captured_Photos")
        worker = CameraWorker(
            FaceRecognizer(self.root / "Known_Faces", backend=FakeFaceRecognitionBackend()),
            store,
        )
        self.assertFalse(worker._auto_capture)
        worker.scheduler.mark_captured("Jordan", now=100)
        self.assertFalse(worker.scheduler.is_due("Jordan", now=104))
        self.assertTrue(worker.scheduler.is_due("Casey", now=104))

    def test_manual_capture_is_blocked_when_camera_is_off(self):
        store = PhotoCaptureStore(self.root / "Captured_Photos")
        worker = CameraWorker(
            FaceRecognizer(self.root / "Known_Faces", backend=FakeFaceRecognitionBackend()),
            store,
        )
        worker._latest_frame = np.zeros((16, 16, 3), dtype=np.uint8)
        worker._latest_matches = ()
        with self.assertRaises(CameraError):
            worker.capture_manual()

    def test_confirmation_requires_consecutive_known_frames(self):
        known_dir = self.root / "Known_Faces"
        self._write_image(known_dir / "Jordan.png", 40)
        recognizer = FaceRecognizer(
            known_dir,
            tolerance=0.48,
            confirmation_frames=3,
            backend=FakeFaceRecognitionBackend(),
        )
        recognizer.reload_known_faces()
        known = np.full((32, 32, 3), 40, dtype=np.uint8)
        unknown = np.full((32, 32, 3), 220, dtype=np.uint8)
        recognizer.recognize(known)
        recognizer.recognize(known)
        recognizer.recognize(unknown)
        self.assertFalse(recognizer._confirmed_names)
        self.assertFalse(recognizer._candidate_counts)

    def test_reloading_known_faces_resets_confirmation_state(self):
        known_dir = self.root / "Known_Faces"
        self._write_image(known_dir / "Jordan.png", 40)
        recognizer = FaceRecognizer(
            known_dir,
            tolerance=0.48,
            confirmation_frames=3,
            backend=FakeFaceRecognitionBackend(),
        )
        recognizer.reload_known_faces()
        frame = np.full((32, 32, 3), 40, dtype=np.uint8)
        for _ in range(3):
            recognizer.recognize(frame)
        self.assertTrue(recognizer._confirmed_names)
        recognizer.reload_known_faces()
        self.assertFalse(recognizer._confirmed_names)
        self.assertFalse(recognizer._candidate_counts)

if __name__ == "__main__":
    unittest.main()
