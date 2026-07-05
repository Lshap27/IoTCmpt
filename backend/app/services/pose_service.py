from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import PoseEvent

POSE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10), (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    (17, 19), (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (27, 31), (29, 31), (28, 30), (28, 32), (30, 32),
]


@dataclass(frozen=True)
class PoseDetectionResult:
    pose: str
    human_presence: str
    pose_image_url: Optional[str]
    landmarks_count: int = 0


def calculate_angle(a, b, c) -> float:
    ba = np.array([a.x - b.x, a.y - b.y])
    bc = np.array([c.x - b.x, c.y - b.y])
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def analyze_pose(landmarks) -> str:
    nose = landmarks[0]
    left_shoulder = landmarks[11]
    right_shoulder = landmarks[12]
    left_hip = landmarks[23]
    right_hip = landmarks[24]
    left_knee = landmarks[25]
    right_knee = landmarks[26]
    left_ankle = landmarks[27]
    right_ankle = landmarks[28]

    lower_body_visible = (
        left_knee.visibility > 0.5
        and right_knee.visibility > 0.5
        and left_ankle.visibility > 0.5
        and right_ankle.visibility > 0.5
    )
    if lower_body_visible:
        avg_knee_angle = (
            calculate_angle(left_hip, left_knee, left_ankle)
            + calculate_angle(right_hip, right_knee, right_ankle)
        ) / 2
        is_standing = avg_knee_angle > 150
    else:
        is_standing = ((left_hip.y + right_hip.y) / 2) < 0.55

    posture_type = "站姿" if is_standing else "坐姿"
    shoulder_mid_x = (left_shoulder.x + right_shoulder.x) / 2
    shoulder_mid_y = (left_shoulder.y + right_shoulder.y) / 2
    hip_mid_x = (left_hip.x + right_hip.x) / 2
    hip_mid_y = (left_hip.y + right_hip.y) / 2

    torso_angle = abs(np.degrees(np.arctan2(shoulder_mid_x - hip_mid_x, abs(shoulder_mid_y - hip_mid_y) + 1e-8)))
    nose_to_shoulder_y = shoulder_mid_y - nose.y
    issues: list[str] = []
    if torso_angle > 20:
        issues.append("驼背" if is_standing else "趴桌")
    if nose_to_shoulder_y < 0.02:
        issues.append("低头")
    return f"{posture_type}{'、'.join(issues)}" if issues else f"{posture_type}端正"


def draw_landmarks(image, landmarks) -> None:
    h, w = image.shape[:2]
    for start, end in POSE_CONNECTIONS:
        x1, y1 = int(landmarks[start].x * w), int(landmarks[start].y * h)
        x2, y2 = int(landmarks[end].x * w), int(landmarks[end].y * h)
        cv2.line(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
    for landmark in landmarks:
        x, y = int(landmark.x * w), int(landmark.y * h)
        cv2.circle(image, (x, y), 4, (0, 0, 255), -1)


class PoseEstimator:
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.landmarker = None
        self.error: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.landmarker is not None

    def load(self) -> None:
        if not self.model_path.exists():
            self.error = f"姿态模型不存在: {self.model_path}"
            return
        try:
            from mediapipe import Image, ImageFormat
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

            options = PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self.landmarker = PoseLandmarker.create_from_options(options)
            self._mp_image = Image
            self._mp_image_format = ImageFormat
            self.error = None
        except Exception as exc:  # pragma: no cover - depends on native MediaPipe runtime
            self.landmarker = None
            self.error = f"姿态模型加载失败: {exc}"

    def detect(self, image_path: Path) -> PoseDetectionResult:
        image = cv2.imread(str(image_path))
        if image is None:
            return PoseDetectionResult("无法解析图片", "unknown", None)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = self._mp_image(image_format=self._mp_image_format.SRGB, data=image_rgb)
        result = self.landmarker.detect(mp_image)
        if not result.pose_landmarks:
            return PoseDetectionResult("未检测到人体，请确保图片中有完整的人体", "no", None)

        landmarks = result.pose_landmarks[0]
        pose = analyze_pose(landmarks)
        annotated_img = image.copy()
        draw_landmarks(annotated_img, landmarks)
        filename = f"pose_{uuid4()}.jpg"
        output_path = settings.images_dir / filename
        cv2.imwrite(str(output_path), annotated_img)
        return PoseDetectionResult(
            pose=pose,
            human_presence="yes",
            pose_image_url=f"{settings.base_url}/images/{filename}",
            landmarks_count=len(landmarks),
        )


def record_pose_detection(
    db: Session,
    pose: str,
    human_presence: str,
    image_url: Optional[str],
    pose_image_url: Optional[str],
) -> PoseEvent:
    event = PoseEvent(
        pose=pose,
        human_presence=human_presence,
        image_url=image_url,
        pose_image_url=pose_image_url,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
