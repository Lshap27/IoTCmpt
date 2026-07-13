from __future__ import annotations

import asyncio
import logging
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


def serialize_pose_result(db: Session, result: models.PoseResult) -> dict[str, Any]:
    source = db.get(models.ImageAsset, result.source_image_id)
    annotated = db.get(models.ImageAsset, result.annotated_image_id) if result.annotated_image_id else None
    return {
        "id": result.id,
        "device_id": result.device_id,
        "human_present": result.human_present,
        "label": result.label,
        "confidence": result.confidence,
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


def _angle(np: Any, a: Any, b: Any, c: Any) -> float:
    ba = np.array([a.x - b.x, a.y - b.y])
    bc = np.array([c.x - b.x, c.y - b.y])
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def _pose_label(np: Any, landmarks: list[Any]) -> str:
    nose = landmarks[0]
    left_shoulder, right_shoulder = landmarks[11], landmarks[12]
    left_hip, right_hip = landmarks[23], landmarks[24]
    left_knee, right_knee = landmarks[25], landmarks[26]
    left_ankle, right_ankle = landmarks[27], landmarks[28]

    lower_visible = all(point.visibility > 0.5 for point in (left_knee, right_knee, left_ankle, right_ankle))
    if lower_visible:
        knee_angle = (_angle(np, left_hip, left_knee, left_ankle) + _angle(np, right_hip, right_knee, right_ankle)) / 2
        standing = knee_angle > 150
    else:
        standing = (left_hip.y + right_hip.y) / 2 < 0.55

    shoulder_x = (left_shoulder.x + right_shoulder.x) / 2
    shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
    hip_x = (left_hip.x + right_hip.x) / 2
    hip_y = (left_hip.y + right_hip.y) / 2
    torso_angle = abs(float(np.degrees(np.arctan2(shoulder_x - hip_x, abs(shoulder_y - hip_y) + 1e-8))))
    issues: list[str] = []
    if torso_angle > 20:
        issues.append("驼背" if standing else "趴桌")
    if shoulder_y - nose.y < 0.02:
        issues.append("低头")
    return ("站姿" if standing else "坐姿") + ("、".join(issues) if issues else "端正")


class PoseService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue(maxsize=1)
        self.worker: asyncio.Task[None] | None = None
        self.detector: Any = None
        self.result_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._presence_counts: dict[str, tuple[int, int, bool]] = {}

    async def start(self) -> None:
        if self.settings.pose_enabled and self.worker is None:
            self.worker = asyncio.create_task(self._worker(), name="pose-worker")

    async def stop(self) -> None:
        if self.worker is None:
            return
        self.worker.cancel()
        with suppress(asyncio.CancelledError):
            await self.worker
        self.worker = None

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

    def _ensure_detector(self) -> tuple[Any, Any, Any, Any, Any]:
        if not self.settings.pose_model_path.is_file():
            raise FileNotFoundError(f"pose model not found: {self.settings.pose_model_path}")
        import cv2
        import numpy as np
        from mediapipe import Image, ImageFormat  # type: ignore[import-untyped]
        from mediapipe.tasks import python as mp_python  # type: ignore[import-untyped]
        from mediapipe.tasks.python import vision  # type: ignore[import-untyped]

        if self.detector is None:
            options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(self.settings.pose_model_path)),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=self.settings.pose_detection_confidence,
                min_pose_presence_confidence=self.settings.pose_presence_confidence,
            )
            self.detector = vision.PoseLandmarker.create_from_options(options)
        return cv2, np, vision, Image, ImageFormat

    def process_now(self, device_id: str, source_image_id: int) -> dict[str, Any]:
        cv2, np, _vision, mp_image_type, mp_image_format = self._ensure_detector()
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
            result = self.detector.detect(mp_image_type(image_format=mp_image_format.SRGB, data=rgb))

            enhanced = False
            if not result.pose_landmarks:
                lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
                light, a_channel, b_channel = cv2.split(lab)
                light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(light)
                enhanced_bgr = cv2.cvtColor(cv2.merge((light, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
                enhanced_rgb = cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB)
                result = self.detector.detect(mp_image_type(image_format=mp_image_format.SRGB, data=enhanced_rgb))
                enhanced = bool(result.pose_landmarks)

            annotated_asset = None
            if not result.pose_landmarks:
                label, confidence, raw_present = "未检测到人体", 0.0, False
                raw = {"landmarks_count": 0, "enhanced_retry": True, "enhanced_detected": False}
            else:
                landmarks = result.pose_landmarks[0]
                label = _pose_label(np, landmarks)
                confidence = sum(float(point.visibility) for point in landmarks) / len(landmarks)
                raw_present = True
                height, width = image.shape[:2]
                for first, second in POSE_CONNECTIONS:
                    a, b = landmarks[first], landmarks[second]
                    cv2.line(
                        image,
                        (int(a.x * width), int(a.y * height)),
                        (int(b.x * width), int(b.y * height)),
                        (0, 255, 0),
                        2,
                    )
                for point in landmarks:
                    cv2.circle(image, (int(point.x * width), int(point.y * height)), 4, (0, 0, 255), -1)
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
                raw = {"landmarks_count": len(landmarks), "enhanced_retry": enhanced, "enhanced_detected": enhanced}

            hits, misses, stable = self._presence_counts.get(device_id, (0, 0, False))
            if raw_present:
                hits, misses = hits + 1, 0
                if hits >= 2:
                    stable = True
            else:
                hits, misses = 0, misses + 1
                if misses >= 3:
                    stable = False
            self._presence_counts[device_id] = (hits, misses, stable)
            human_present = stable
            raw.update(
                {
                    "raw_human_present": raw_present,
                    "stable_human_present": stable,
                    "hit_count": hits,
                    "miss_count": misses,
                }
            )
            if stable and not raw_present:
                label = "人体短暂丢失（保持有人）"

            pose = models.PoseResult(
                device_id=device_id,
                source_image_id=source.id,
                annotated_image_id=annotated_asset.id if annotated_asset else None,
                human_present=human_present,
                label=label,
                confidence=confidence,
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
