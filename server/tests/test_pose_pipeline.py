from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.core.config import Settings
from app.services.pose import PoseService
from app.services.posture import PostureObservation, PostureSmoother, classify_posture
from app.services.presence import PersonDetection, PresenceTracker


def point(x=0.5, y=0.5, z=0.0, score=1.0):
    return SimpleNamespace(x=x, y=y, z=z, visibility=score, presence=score, name=None)


def upper_body(*, shoulder_x=0.5, ear_x=0.52, nose_y=0.18):
    points = [point(score=0.0) for _ in range(33)]
    points[0] = point(ear_x + 0.02, nose_y)
    points[7] = point(ear_x, 0.22)
    points[8] = point(ear_x, 0.22)
    points[11] = point(shoulder_x - 0.05, 0.3)
    points[12] = point(shoulder_x + 0.05, 0.3)
    points[23] = point(0.46, 0.7)
    points[24] = point(0.54, 0.7)
    return points


def add_seated_legs(points):
    points[25] = point(0.46, 0.85)
    points[27] = point(0.65, 0.85)
    points[26] = point(0.54, 0.85)
    points[28] = point(0.35, 0.85)
    return points


def add_straight_legs(points):
    points[25] = point(0.46, 0.85)
    points[27] = point(0.46, 1.0)
    points[26] = point(0.54, 0.85)
    points[28] = point(0.54, 1.0)
    return points


def test_upper_body_upright_and_full_body_seated_are_separate_coverages():
    upper = classify_posture(np, upper_body(), None)
    full = classify_posture(np, add_seated_legs(upper_body()), None)

    assert upper.body_coverage == "upper_body"
    assert upper.seated_state == "seated"
    assert upper.posture_code == "upright"
    assert upper.label == "坐姿端正"
    assert full.body_coverage == "full_body"
    assert full.seated_state == "seated"


def test_posture_classifier_separates_forward_lean_hunch_and_head_down():
    forward = classify_posture(np, upper_body(shoulder_x=0.7, ear_x=0.72), None)
    hunched = classify_posture(np, upper_body(ear_x=0.66), None)
    head_down = classify_posture(np, upper_body(nose_y=0.36), None)

    assert forward.posture_code == "forward_lean"
    assert forward.posture_issues[0] == "forward_lean"
    assert hunched.posture_code == "hunched"
    assert hunched.posture_issues == ("hunched",)
    assert head_down.posture_code == "head_down"
    assert head_down.posture_issues == ("head_down",)


def test_full_body_straight_legs_are_not_evaluated_as_seated():
    result = classify_posture(np, add_straight_legs(upper_body()), None)
    assert result.body_coverage == "full_body"
    assert result.seated_state == "not_seated"
    assert result.posture_code == "not_seated"


def test_missing_hips_is_unknown_not_absent():
    points = upper_body()
    points[23] = point(score=0.2)
    result = classify_posture(np, points, None)
    assert result.body_coverage == "insufficient"
    assert result.posture_code == "unknown"


def test_posture_smoother_confirms_switch_and_holds_two_missing_frames():
    smoother = PostureSmoother()
    upright = classify_posture(np, upper_body(), None)

    assert smoother.update("dev", upright).posture_code == "unknown"
    stable = smoother.update("dev", upright)
    assert stable.posture_code == "upright"
    assert stable.fresh is True

    for _ in range(2):
        held = smoother.update("dev", PostureObservation())
        assert held.posture_code == "upright"
        assert held.fresh is False
    assert smoother.update("dev", PostureObservation()).posture_code == "unknown"


def test_presence_tracker_uses_object_detector_immediately_and_three_misses_to_leave():
    tracker = PresenceTracker()
    present = tracker.update(
        "dev",
        PersonDetection(found=True, confidence=0.8),
        pose_valid=False,
        pose_confidence=0.0,
    )
    assert present.human_present is True
    assert present.source == "object_detector"

    for _ in range(2):
        held = tracker.update(
            "dev",
            PersonDetection(found=False),
            pose_valid=False,
            pose_confidence=0.0,
        )
        assert held.human_present is True
    absent = tracker.update(
        "dev",
        PersonDetection(found=False),
        pose_valid=False,
        pose_confidence=0.0,
    )
    assert absent.human_present is False


def test_presence_tracker_allows_two_pose_fallback_hits_and_preserves_errors():
    tracker = PresenceTracker()
    first = tracker.update(
        "dev",
        PersonDetection(found=False),
        pose_valid=True,
        pose_confidence=0.75,
    )
    second = tracker.update(
        "dev",
        PersonDetection(found=False),
        pose_valid=True,
        pose_confidence=0.75,
    )
    errored = tracker.update(
        "dev",
        PersonDetection(found=False, error="inference failed"),
        pose_valid=False,
        pose_confidence=0.0,
        inference_error=True,
    )

    assert first.human_present is False
    assert second.human_present is True
    assert second.source == "pose_fallback"
    assert errored.human_present is True
    assert errored.source == "error"
    assert errored.miss_count == 0


def test_person_bbox_is_manually_cropped_and_landmarks_are_mapped_back(monkeypatch):
    class FakeImage:
        def __init__(self, *, image_format, data):
            self.image_format = image_format
            self.data = data

    class FakeImageFormat:
        SRGB = "srgb"

    class FakeDetector:
        crop_shape = None

        def detect(self, image):
            self.crop_shape = image.data.shape
            return SimpleNamespace(pose_landmarks=[[point(0.2, 0.4, 0.1)]])

    detector = FakeDetector()
    service = PoseService(Settings(_env_file=None, person_detection_enabled=False))
    monkeypatch.setattr(service, "_pose_detector", lambda *_args, **_kwargs: detector)
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    result = service._detect_pose(
        "dev",
        rgb,
        None,
        PersonDetection(found=True, confidence=0.8, bbox=(0.25, 0.25, 0.75, 0.75)),
        FakeImage,
        FakeImageFormat,
        object(),
        object(),
    )

    mapped = result.pose_landmarks[0][0]
    assert detector.crop_shape == (50, 100, 3)
    assert mapped.x == 0.35
    assert mapped.y == 0.45
    assert mapped.z == 0.05
