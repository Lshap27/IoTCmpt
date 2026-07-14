from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.timeutil import iso_utc
from app.db import models
from app.db.session import SessionLocal
from app.schemas import WebSocketEnvelope
from app.services.images import prune_images
from app.services.posture import PostureObservation, PostureSmoother, classify_posture
from app.services.presence import PersonDetection, PresenceDetector, PresenceTracker
from app.services.websocket import manager

LOGGER = logging.getLogger(__name__)

POSE_CONNECTIONS = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 7),
    (0, 4),
    (4, 5),
    (5, 6),
    (6, 8),
    (9, 10),
    (11, 12),
    (11, 13),
    (13, 15),
    (15, 17),
    (15, 19),
    (15, 21),
    (17, 19),
    (12, 14),
    (14, 16),
    (16, 18),
    (16, 20),
    (16, 22),
    (18, 20),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (24, 26),
    (25, 27),
    (26, 28),
    (27, 29),
    (27, 31),
    (29, 31),
    (28, 30),
    (28, 32),
    (30, 32),
]


def _legacy_posture(result: models.PoseResult) -> dict[str, Any]:
    label = result.label
    issues: list[str] = []
    if "前倾" in label or "趴桌" in label:
        issues.append("forward_lean")
    if "驼背" in label:
        issues.append("hunched")
    if "低头" in label:
        issues.append("head_down")
    if label.startswith("站姿") or label.startswith("非坐姿"):
        seated_state, posture_code = "not_seated", "not_seated"
    elif label.startswith("坐姿"):
        seated_state, posture_code = "seated", issues[0] if issues else "upright"
    else:
        seated_state, posture_code = "unknown", "unknown"
    return {
        "presence_confidence": result.confidence if result.human_present else 0.0,
        "presence_source": "pose_fallback" if result.human_present else "none",
        "body_coverage": "insufficient",
        "seated_state": seated_state,
        "posture_code": posture_code,
        "posture_issues": issues,
        "posture_confidence": result.confidence,
        "posture_fresh": True,
    }


def serialize_pose_result(db: Session, result: models.PoseResult) -> dict[str, Any]:
    source = db.get(models.ImageAsset, result.source_image_id)
    annotated = db.get(models.ImageAsset, result.annotated_image_id) if result.annotated_image_id else None
    structure = _legacy_posture(result)
    raw = result.raw_payload or {}
    for key in structure:
        if key in raw:
            structure[key] = raw[key]
    return {
        "id": result.id,
        "device_id": result.device_id,
        "human_present": result.human_present,
        "label": result.label,
        "confidence": result.confidence,
        **structure,
        "source_image_url": source.url if source else "",
        "annotated_image_url": annotated.url if annotated else None,
        "created_at": iso_utc(result.created_at),
    }


def latest_pose_result(db: Session, device_id: str) -> models.PoseResult | None:
    return (
        db.query(models.PoseResult)
        .filter(models.PoseResult.device_id == device_id)
        .order_by(models.PoseResult.created_at.desc())
        .first()
    )


def _pose_label(np: Any, landmarks: list[Any], world_landmarks: list[Any] | None = None) -> str:
    """Compatibility helper kept for focused posture unit tests."""
    return classify_posture(np, landmarks, world_landmarks).label


def _landmark_valid(point: Any, threshold: float) -> bool:
    visibility = float(getattr(point, "visibility", 1.0))
    presence = float(getattr(point, "presence", 1.0))
    return min(visibility, presence) >= threshold


class PoseService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue(maxsize=1)
        self.worker: asyncio.Task[None] | None = None
        self.result_handler: Callable[[str, dict[str, Any]], None] | None = None
        self.presence_detector = PresenceDetector(
            settings.person_detection_model_path,
            settings.person_detection_confidence,
        )
        self.presence_tracker = PresenceTracker()
        self.posture_smoother = PostureSmoother()
        self._pose_detectors: dict[str, Any] = {}
        self._crop_pose_detector: Any = None
        self._last_timestamps: dict[str, int] = {}

    def _validate_models(self) -> None:
        if not self.settings.pose_model_path.is_file():
            raise FileNotFoundError(f"pose model not found: {self.settings.pose_model_path}")
        if self.settings.person_detection_enabled:
            self.presence_detector.validate_model()

    async def start(self) -> None:
        if self.settings.pose_enabled and self.worker is None:
            self._validate_models()
            self.worker = asyncio.create_task(self._worker(), name="pose-worker")

    async def stop(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
            self.worker = None
        self.presence_detector.close()
        for detector in self._pose_detectors.values():
            detector.close()
        self._pose_detectors.clear()
        if self._crop_pose_detector is not None:
            self._crop_pose_detector.close()
            self._crop_pose_detector = None

    async def enqueue(self, device_id: str, source_image_id: int) -> None:
        if not self.settings.pose_enabled:
            return
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait((device_id, source_image_id))

    async def _worker(self) -> None:
        while True:
            device_id, source_image_id = await self.queue.get()
            try:
                payload = await asyncio.to_thread(self.process_now, device_id, source_image_id)
                await manager.broadcast(
                    device_id,
                    WebSocketEnvelope(type="pose_result", device_id=device_id, payload=payload).model_dump(mode="json"),
                )
                if self.result_handler:
                    self.result_handler(device_id, payload)
            except Exception:
                LOGGER.exception("pose analysis failed for image %s", source_image_id)
            finally:
                self.queue.task_done()

    def _runtime(self) -> tuple[Any, Any, Any, Any, Any, Any]:
        self._validate_models()
        import cv2
        import numpy as np
        from mediapipe import Image, ImageFormat
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        return cv2, np, Image, ImageFormat, mp_python, vision

    def _create_pose_detector(self, mp_python: Any, vision: Any, running_mode: Any) -> Any:
        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(self.settings.pose_model_path)),
            running_mode=running_mode,
            num_poses=1,
            min_pose_detection_confidence=self.settings.pose_detection_confidence,
            min_pose_presence_confidence=self.settings.pose_presence_confidence,
            min_tracking_confidence=self.settings.pose_tracking_confidence,
        )
        return vision.PoseLandmarker.create_from_options(options)

    def _pose_detector(self, device_id: str, mp_python: Any, vision: Any, *, video: bool) -> Any:
        if not video:
            if self._crop_pose_detector is None:
                self._crop_pose_detector = self._create_pose_detector(mp_python, vision, vision.RunningMode.IMAGE)
            return self._crop_pose_detector

        detector = self._pose_detectors.get(device_id)
        if detector is None:
            detector = self._create_pose_detector(mp_python, vision, vision.RunningMode.VIDEO)
            self._pose_detectors[device_id] = detector
        return detector

    def _next_timestamp(self, device_id: str, created_at: Any) -> int:
        candidate = int(created_at.timestamp() * 1000) if created_at is not None else int(time.time() * 1000)
        timestamp = max(candidate, self._last_timestamps.get(device_id, candidate - 1) + 1)
        self._last_timestamps[device_id] = timestamp
        return timestamp

    def _detect_pose(
        self,
        device_id: str,
        rgb: Any,
        created_at: Any,
        detection: PersonDetection,
        image_type: Any,
        image_format: Any,
        mp_python: Any,
        vision: Any,
        *,
        use_person_crop: bool = True,
    ) -> Any:
        pose_rgb = rgb
        crop_transform: tuple[float, float, float, float] | None = None
        if use_person_crop and detection.bbox:
            left, top, right, bottom = detection.bbox
            height, width = rgb.shape[:2]
            x1, y1 = max(0, int(left * width)), max(0, int(top * height))
            x2, y2 = min(width, int(right * width)), min(height, int(bottom * height))
            if x2 - x1 >= 2 and y2 - y1 >= 2:
                pose_rgb = rgb[y1:y2, x1:x2]
                crop_transform = (x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height)
        image = image_type(image_format=image_format.SRGB, data=pose_rgb)
        if crop_transform:
            result = self._pose_detector(device_id, mp_python, vision, video=False).detect(image)
        else:
            result = self._pose_detector(device_id, mp_python, vision, video=True).detect_for_video(
                image,
                self._next_timestamp(device_id, created_at),
            )
        if crop_transform and result.pose_landmarks:
            offset_x, offset_y, scale_x, scale_y = crop_transform
            result.pose_landmarks[0] = [
                type(point)(
                    x=offset_x + float(point.x) * scale_x,
                    y=offset_y + float(point.y) * scale_y,
                    z=float(point.z) * scale_x,
                    visibility=point.visibility,
                    presence=point.presence,
                    name=point.name,
                )
                for point in result.pose_landmarks[0]
            ]
        return result

    def _annotate(
        self,
        cv2: Any,
        image: Any,
        detection: PersonDetection,
        landmarks: list[Any] | None,
        observation: PostureObservation,
    ) -> bool:
        height, width = image.shape[:2]
        drew = False
        if detection.bbox:
            left, top, right, bottom = detection.bbox
            cv2.rectangle(
                image,
                (int(left * width), int(top * height)),
                (int(right * width), int(bottom * height)),
                (255, 170, 0),
                2,
            )
            drew = True
        if landmarks:
            threshold = self.settings.pose_landmark_visibility
            for first, second in POSE_CONNECTIONS:
                a, b = landmarks[first], landmarks[second]
                if not (_landmark_valid(a, threshold) and _landmark_valid(b, threshold)):
                    continue
                cv2.line(
                    image,
                    (int(a.x * width), int(a.y * height)),
                    (int(b.x * width), int(b.y * height)),
                    (0, 255, 0),
                    2,
                )
            for point in landmarks:
                if _landmark_valid(point, threshold):
                    cv2.circle(image, (int(point.x * width), int(point.y * height)), 4, (0, 0, 255), -1)
            drew = True
        if drew:
            cv2.putText(
                image,
                observation.body_coverage,
                (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
        return drew

    def process_now(self, device_id: str, source_image_id: int) -> dict[str, Any]:
        cv2, np, image_type, image_format, mp_python, vision = self._runtime()
        db = SessionLocal()
        try:
            source = db.get(models.ImageAsset, source_image_id)
            if source is None or source.device_id != device_id:
                raise ValueError("source image does not belong to device")
            source_path = self.settings.uploads_dir / source.device_id / source.filename
            image = cv2.imread(str(source_path))
            if image is None:
                raise ValueError("unable to decode JPEG")
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            detection_error = False
            if self.settings.person_detection_enabled:
                try:
                    detection = self.presence_detector.detect(rgb)
                except Exception as exc:
                    LOGGER.exception("person detection failed for image %s", source_image_id)
                    detection = PersonDetection(found=False, error=str(exc))
                    detection_error = True
            else:
                detection = PersonDetection(found=False)

            pose_error = False
            enhanced = False
            full_frame_retry = False
            try:
                result = self._detect_pose(
                    device_id,
                    rgb,
                    source.created_at,
                    detection,
                    image_type,
                    image_format,
                    mp_python,
                    vision,
                )
                if not result.pose_landmarks and detection.bbox:
                    result = self._detect_pose(
                        device_id,
                        rgb,
                        source.created_at,
                        detection,
                        image_type,
                        image_format,
                        mp_python,
                        vision,
                        use_person_crop=False,
                    )
                    full_frame_retry = True
                if not result.pose_landmarks:
                    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
                    light, a_channel, b_channel = cv2.split(lab)
                    light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(light)
                    enhanced_bgr = cv2.cvtColor(cv2.merge((light, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
                    enhanced_rgb = cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB)
                    result = self._detect_pose(
                        device_id,
                        enhanced_rgb,
                        source.created_at,
                        detection,
                        image_type,
                        image_format,
                        mp_python,
                        vision,
                        use_person_crop=False,
                    )
                    enhanced = bool(result.pose_landmarks)
            except Exception:
                LOGGER.exception("pose landmark detection failed for image %s", source_image_id)
                result = None
                pose_error = True

            landmarks = result.pose_landmarks[0] if result and result.pose_landmarks else None
            world_landmarks = result.pose_world_landmarks[0] if result and result.pose_world_landmarks else None
            raw_observation = (
                classify_posture(
                    np,
                    landmarks,
                    world_landmarks,
                    visibility_threshold=self.settings.pose_landmark_visibility,
                    forward_lean_degrees=self.settings.pose_forward_lean_degrees,
                    hunch_ratio_threshold=self.settings.pose_hunch_ratio,
                    head_down_degrees=self.settings.pose_head_down_degrees,
                )
                if landmarks
                else PostureObservation()
            )
            observation = self.posture_smoother.update(device_id, raw_observation)
            pose_valid = raw_observation.body_coverage != "insufficient"
            presence = self.presence_tracker.update(
                device_id,
                detection,
                pose_valid=pose_valid,
                pose_confidence=raw_observation.confidence,
                inference_error=detection_error or pose_error,
            )

            if not presence.human_present:
                label = "未检测到人体"
            elif observation.posture_code == "unknown" and observation.label == "姿态暂不可判":
                label = "检测到人体，姿态暂不可判"
            else:
                label = observation.label

            annotated_asset = None
            if self._annotate(cv2, image, detection, landmarks, observation):
                filename = f"pose-{uuid4().hex}.jpg"
                path = self.settings.uploads_dir / device_id / filename
                if not cv2.imwrite(str(path), image):
                    raise OSError("failed to write annotated image")
                annotated_asset = models.ImageAsset(
                    device_id=device_id,
                    filename=filename,
                    url=f"{self.settings.base_url}/uploads/{device_id}/{filename}",
                    content_type="image/jpeg",
                    size_bytes=path.stat().st_size,
                    kind="pose_annotated",
                )
                db.add(annotated_asset)
                db.flush()

            raw: dict[str, Any] = {
                "landmarks_count": len(landmarks) if landmarks else 0,
                "enhanced_retry": not bool(landmarks) or enhanced,
                "enhanced_detected": enhanced,
                "full_frame_retry": full_frame_retry,
                "person_bbox": list(detection.bbox) if detection.bbox else None,
                "presence_confidence": presence.confidence,
                "presence_source": presence.source,
                "presence_miss_count": presence.miss_count,
                "pose_fallback_hit_count": presence.fallback_hit_count,
                "body_coverage": observation.body_coverage,
                "seated_state": observation.seated_state,
                "posture_code": observation.posture_code,
                "posture_issues": list(observation.posture_issues),
                "posture_confidence": observation.confidence,
                "posture_fresh": observation.fresh,
                "posture_metrics": raw_observation.metrics,
            }
            if detection.error:
                raw["presence_error"] = detection.error
            if pose_error:
                raw["pose_error"] = True

            pose = models.PoseResult(
                device_id=device_id,
                source_image_id=source.id,
                annotated_image_id=annotated_asset.id if annotated_asset else None,
                human_present=presence.human_present,
                label=label,
                confidence=observation.confidence if presence.human_present else 0.0,
                raw_payload=raw,
            )
            db.add(pose)
            db.commit()
            db.refresh(pose)
            payload = serialize_pose_result(db, pose)
            prune_images(db, self.settings, device_id)
            return payload
        finally:
            db.close()
