from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PersonDetection:
    found: bool
    confidence: float = 0.0
    bbox: tuple[float, float, float, float] | None = None
    error: str | None = None


@dataclass(frozen=True)
class PresenceResult:
    human_present: bool
    confidence: float
    source: str
    miss_count: int
    fallback_hit_count: int


@dataclass
class _PresenceState:
    stable: bool = False
    misses: int = 0
    fallback_hits: int = 0
    confidence: float = 0.0


class PresenceDetector:
    """MediaPipe Object Detector wrapper restricted to the COCO person class."""

    def __init__(self, model_path: Path, score_threshold: float) -> None:
        self.model_path = model_path
        self.score_threshold = score_threshold
        self._detector: Any = None

    def validate_model(self) -> None:
        if not self.model_path.is_file():
            raise FileNotFoundError(f"person detection model not found: {self.model_path}")

    def _ensure_detector(self) -> tuple[Any, Any, Any]:
        self.validate_model()
        from mediapipe import Image, ImageFormat
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        if self._detector is None:
            options = vision.ObjectDetectorOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=vision.RunningMode.IMAGE,
                max_results=1,
                score_threshold=self.score_threshold,
                category_allowlist=["person"],
            )
            self._detector = vision.ObjectDetector.create_from_options(options)
        return Image, ImageFormat, vision

    def detect(self, rgb: Any) -> PersonDetection:
        image_type, image_format, _vision = self._ensure_detector()
        result = self._detector.detect(image_type(image_format=image_format.SRGB, data=rgb))
        if not result.detections:
            return PersonDetection(found=False)

        detection = max(result.detections, key=lambda item: float(item.categories[0].score))
        category = detection.categories[0]
        height, width = rgb.shape[:2]
        box = detection.bounding_box
        pad_x = box.width * 0.15
        pad_y = box.height * 0.15
        left = max(0.0, (box.origin_x - pad_x) / width)
        top = max(0.0, (box.origin_y - pad_y) / height)
        right = min(1.0, (box.origin_x + box.width + pad_x) / width)
        bottom = min(1.0, (box.origin_y + box.height + pad_y) / height)
        return PersonDetection(
            found=True,
            confidence=float(category.score),
            bbox=(left, top, right, bottom),
        )

    def close(self) -> None:
        if self._detector is not None:
            self._detector.close()
            self._detector = None


class PresenceTracker:
    """Asymmetric hysteresis: enter quickly, leave only after sustained misses."""

    def __init__(self) -> None:
        self._states: dict[str, _PresenceState] = {}

    def update(
        self,
        device_id: str,
        detection: PersonDetection,
        *,
        pose_valid: bool,
        pose_confidence: float,
        inference_error: bool = False,
    ) -> PresenceResult:
        state = self._states.setdefault(device_id, _PresenceState())

        if detection.found:
            state.stable = True
            state.misses = 0
            state.fallback_hits = 0
            state.confidence = detection.confidence
            source = "object_detector"
        elif pose_valid:
            state.misses = 0
            state.fallback_hits += 1
            state.confidence = pose_confidence
            if state.stable or state.fallback_hits >= 2:
                state.stable = True
            source = "pose_fallback"
        elif inference_error or detection.error:
            # A failed inference says nothing about occupancy. Preserve all counters.
            source = "error"
        else:
            state.fallback_hits = 0
            state.misses += 1
            if state.misses >= 3:
                state.stable = False
                state.confidence = 0.0
            source = "none"

        return PresenceResult(
            human_present=state.stable,
            confidence=state.confidence if state.stable or pose_valid else 0.0,
            source=source,
            miss_count=state.misses,
            fallback_hit_count=state.fallback_hits,
        )
