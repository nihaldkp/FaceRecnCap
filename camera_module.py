"""Threaded webcam worker and explicit/automatic photo capture."""

from __future__ import annotations

import queue
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2

from face_recognition_module import FaceMatch, FaceRecognizer


class CameraError(Exception):
    """An expected webcam or photo-capture failure."""


class PhotoCaptureStore:
    """Writes timestamped JPEG images and maintains a thread-safe file count."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._count = sum(
            1 for path in self.directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )

    @staticmethod
    def _safe_name(name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
        return safe or "Capture"

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def save(self, frame_bgr, person_name: str) -> Path:
        if frame_bgr is None or frame_bgr.size == 0:
            raise CameraError("There is no valid camera image to save.")
        success, encoded = cv2.imencode(".jpg", frame_bgr)
        if not success:
            raise CameraError("OpenCV could not encode the captured photo.")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = self.directory / f"{self._safe_name(person_name)}_{timestamp}.jpg"
        try:
            with self._lock:
                destination.write_bytes(encoded.tobytes())
                self._count += 1
        except OSError as exc:
            raise CameraError(f"Could not save photo to {destination}: {exc}") from exc
        return destination


class CaptureScheduler:
    """Tracks the last automatic capture time independently for each person."""

    def __init__(self, interval_seconds: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._interval = self._validate_interval(interval_seconds)
        self._last_capture: dict[str, float] = {}

    @staticmethod
    def _validate_interval(seconds: float) -> float:
        interval = float(seconds)
        if interval <= 0:
            raise ValueError("Capture interval must be greater than zero.")
        return interval

    def set_interval(self, seconds: float) -> None:
        interval = self._validate_interval(seconds)
        with self._lock:
            self._interval = interval

    def is_due(self, person_name: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            previous = self._last_capture.get(person_name)
            return previous is None or current - previous >= self._interval

    def mark_captured(self, person_name: str, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._last_capture[person_name] = current


class CameraWorker:
    """Reads, recognizes, and optionally captures webcam frames on a worker thread."""

    def __init__(
        self,
        recognizer: FaceRecognizer,
        photo_store: PhotoCaptureStore,
        on_recognized: Callable[[str], object] | None = None,
        capture_interval: float = 5.0,
        auto_capture: bool = False,
        camera_index: int = 0,
    ) -> None:
        self.recognizer = recognizer
        self.photo_store = photo_store
        self.on_recognized = on_recognized
        self.camera_index = camera_index
        self.scheduler = CaptureScheduler(capture_interval)
        self._settings_lock = threading.Lock()
        self._auto_capture = bool(auto_capture)
        self._stop_event = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._latest_matches: tuple[FaceMatch, ...] = ()
        self._camera_active = False
        self._active_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._errors: queue.Queue[str] = queue.Queue()
        self._attendance_recorded: set[str] = set()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def camera_active(self) -> bool:
        with self._active_lock:
            return self._camera_active

    def start(self) -> None:
        if self.is_alive:
            raise CameraError("The camera worker is already running.")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="webcam-recognition", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> bool:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        return not self.is_alive

    def update_capture_settings(self, interval_seconds: float, auto_capture: bool) -> None:
        self.scheduler.set_interval(interval_seconds)
        with self._settings_lock:
            self._auto_capture = bool(auto_capture)

    def get_latest_snapshot(self):
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy(), self._latest_matches

    def _recognized_names(self, matches: tuple[FaceMatch, ...]) -> list[str]:
        return list(dict.fromkeys(match.name for match in matches if match.is_known))

    def capture_manual(self) -> Path:
        snapshot = self.get_latest_snapshot()
        if snapshot is None or not self.camera_active:
            raise CameraError("Start the camera and wait for a frame before taking a photo.")
        frame, matches = snapshot
        names = self._recognized_names(matches)
        label = "_".join(names) if names else "Manual_Capture"
        return self.photo_store.save(frame, label)

    def pop_error(self) -> str | None:
        try:
            return self._errors.get_nowait()
        except queue.Empty:
            return None

    def _run(self) -> None:
        capture = None
        try:
            capture = cv2.VideoCapture(self.camera_index)
            if not capture.isOpened():
                raise CameraError("The webcam could not be opened. Check camera permissions and availability.")
            with self._active_lock:
                self._camera_active = True
            failures = 0
            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 15:
                        raise CameraError("The webcam stopped providing frames.")
                    time.sleep(0.05)
                    continue
                failures = 0
                matches = self.recognizer.recognize(frame)
                with self._frame_lock:
                    self._latest_frame = frame.copy()
                    self._latest_matches = matches

                for name in self._recognized_names(matches):
                    if name not in self._attendance_recorded and self.on_recognized is not None:
                        try:
                            self.on_recognized(name)
                            self._attendance_recorded.add(name)
                        except (sqlite3.Error, OSError, ValueError) as exc:
                            self._errors.put(f"Attendance could not be recorded for {name}: {exc}")
                    with self._settings_lock:
                        enabled = self._auto_capture
                    if enabled and self.scheduler.is_due(name):
                        try:
                            self.photo_store.save(frame, name)
                            self.scheduler.mark_captured(name)
                        except CameraError as exc:
                            self._errors.put(str(exc))
        except Exception as exc:
            self._errors.put(str(exc) if isinstance(exc, CameraError) else f"Camera processing failed: {exc}")
        finally:
            if capture is not None:
                capture.release()
            with self._active_lock:
                self._camera_active = False
