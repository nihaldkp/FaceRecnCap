"""Face image loading, registration, and recognition helpers."""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


class FaceRecognitionError(Exception):
    """An expected image, registration, or recognition failure."""


@dataclass(frozen=True)
class FaceMatch:
    name: str
    location: tuple[int, int, int, int]
    distance: float | None

    @property
    def is_known(self) -> bool:
        return self.distance is not None


class FaceRecognizer:
    """Stores one encoding per image and matches camera frames against them."""

    def __init__(
        self,
        known_faces_dir: Path,
        tolerance: float = 0.48,
        backend: Any | None = None,
        confirmation_frames: int = 3,
    ) -> None:
        if tolerance <= 0:
            raise ValueError("Recognition tolerance must be greater than zero.")
        if confirmation_frames < 1:
            raise ValueError("Confirmation frames must be at least one.")
        self.known_faces_dir = Path(known_faces_dir)
        self.tolerance = tolerance
        self._backend = backend
        self._lock = threading.RLock()
        self._names: list[str] = []
        self._encodings: list[Any] = []
        self.confirmation_frames = confirmation_frames
        self._candidate_counts: dict[str, int] = {}
        self._confirmed_names: set[str] = set()

    def _get_backend(self):
        if self._backend is None:
            try:
                import face_recognition
            except ImportError as exc:
                raise FaceRecognitionError(
                    "The face-recognition package is unavailable. Install the project requirements."
                ) from exc
            self._backend = face_recognition
        return self._backend

    @staticmethod
    def _load_bgr_image(image_path: Path):
        path = Path(image_path)
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise FaceRecognitionError(f"Unsupported image format: {path.suffix or '(no extension)'}")
        try:
            image = cv2.imdecode(
                np.fromfile(str(path), dtype="uint8"),
                cv2.IMREAD_COLOR,
            )
        except (OSError, ValueError, cv2.error) as exc:
            raise FaceRecognitionError(f"Could not read image: {path}") from exc
        if image is None or image.size == 0:
            raise FaceRecognitionError(f"Image is empty or invalid: {path}")
        return image

    def encode_image(self, image_path: Path):
        """Validate a still image and return its sole face encoding."""
        image = self._load_bgr_image(Path(image_path))
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        backend = self._get_backend()
        locations = backend.face_locations(rgb)
        if len(locations) == 0:
            raise FaceRecognitionError(f"No face was found in {Path(image_path).name}.")
        if len(locations) > 1:
            raise FaceRecognitionError(f"Use an image containing exactly one face: {Path(image_path).name}.")
        encodings = backend.face_encodings(rgb, locations)
        if len(encodings) != 1:
            raise FaceRecognitionError(f"Could not create a face encoding for {Path(image_path).name}.")
        return encodings[0]

    def reload_known_faces(self) -> list[str]:
        """Load valid images; return per-file warnings for images that were skipped."""
        self.known_faces_dir.mkdir(parents=True, exist_ok=True)
        names: list[str] = []
        encodings: list[Any] = []
        warnings: list[str] = []
        for path in sorted(self.known_faces_dir.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            try:
                encoding = self.encode_image(path)
            except FaceRecognitionError as exc:
                warnings.append(f"{path.name}: {exc}")
                continue
            names.append(path.stem)
            encodings.append(encoding)
        with self._lock:
            self._names = names
            self._encodings = encodings
            self._candidate_counts.clear()
            self._confirmed_names.clear()
        return warnings

    def register_face(self, image_path: Path, person_name: str) -> Path:
        """Validate and copy a single-face image into Known_Faces, then reload."""
        name = person_name.strip()
        if not name or name in {".", ".."}:
            raise FaceRecognitionError("Enter a non-empty person name.")
        if any(character in '<>:"/\\|?*' for character in name) or any(ord(character) < 32 for character in name):
            raise FaceRecognitionError("The person name contains characters that cannot be used in a filename.")
        source = Path(image_path)
        if not source.is_file():
            raise FaceRecognitionError(f"Image file does not exist: {source}")
        if source.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise FaceRecognitionError(f"Unsupported image format: {source.suffix or '(no extension)'}")
        self.encode_image(source)
        self.known_faces_dir.mkdir(parents=True, exist_ok=True)
        destination = self.known_faces_dir / f"{name}{source.suffix.lower()}"
        if any(path.stem.casefold() == name.casefold() for path in self.known_faces_dir.iterdir() if path.is_file()):
            raise FaceRecognitionError(f"A face named '{name}' is already registered.")
        shutil.copy2(source, destination)
        self.reload_known_faces()
        return destination

    def recognize(self, frame_bgr) -> tuple[FaceMatch, ...]:
        """Return a known or unknown result for each face found in a BGR frame."""
        if frame_bgr is None or frame_bgr.size == 0:
            raise FaceRecognitionError("The camera returned an empty frame.")
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        backend = self._get_backend()
        locations = backend.face_locations(rgb)
        frame_encodings = backend.face_encodings(rgb, locations)
        with self._lock:
            names = tuple(self._names)
            known_encodings = tuple(self._encodings)
        results: list[FaceMatch] = []
        frame_known_names: set[str] = set()
        for index, location in enumerate(locations):
            if index >= len(frame_encodings) or not known_encodings:
                results.append(FaceMatch("Unknown Person", tuple(location), None))
                continue
            distances = backend.face_distance(list(known_encodings), frame_encodings[index])
            if len(distances) == 0:
                results.append(FaceMatch("Unknown Person", tuple(location), None))
                continue
            best_index = min(range(len(distances)), key=lambda candidate: float(distances[candidate]))
            distance = float(distances[best_index])
            if distance <= self.tolerance:
                candidate_name = names[best_index]
                frame_known_names.add(candidate_name)
                results.append(FaceMatch(candidate_name, tuple(location), distance))
            else:
                results.append(FaceMatch("Unknown Person", tuple(location), None))

        with self._lock:
            for name in tuple(self._candidate_counts):
                if name not in frame_known_names:
                    self._candidate_counts.pop(name, None)
                    self._confirmed_names.discard(name)
            for name in frame_known_names:
                self._candidate_counts[name] = self._candidate_counts.get(name, 0) + 1
                if self._candidate_counts[name] >= self.confirmation_frames:
                    self._confirmed_names.add(name)

            results = tuple(
                match if match.is_known and match.name in self._confirmed_names
                else FaceMatch("Unknown Person", match.location, None)
                for match in results
            )
        return tuple(results)
