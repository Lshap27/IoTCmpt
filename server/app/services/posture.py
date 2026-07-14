from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

POSTURE_ISSUE_LABELS = {
    "forward_lean": "前倾",
    "hunched": "驼背",
    "head_down": "低头",
}


@dataclass(frozen=True)
class PostureObservation:
    body_coverage: str = "insufficient"
    seated_state: str = "unknown"
    posture_code: str = "unknown"
    posture_issues: tuple[str, ...] = ()
    confidence: float = 0.0
    label: str = "姿态暂不可判"
    fresh: bool = False
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.posture_code != "unknown"

    @property
    def signature(self) -> tuple[str, tuple[str, ...], str]:
        return self.posture_code, self.posture_issues, self.seated_state


def _point_score(point: Any) -> float:
    return min(float(getattr(point, "visibility", 1.0)), float(getattr(point, "presence", 1.0)))


def _valid(point: Any, threshold: float) -> bool:
    return _point_score(point) >= threshold


def _coords(np: Any, point: Any) -> Any:
    return np.array([float(point.x), float(point.y), float(getattr(point, "z", 0.0))], dtype=float)


def _midpoint(np: Any, points: list[Any]) -> Any:
    return np.mean([_coords(np, point) for point in points], axis=0)


def _angle(np: Any, a: Any, b: Any, c: Any) -> float:
    ba = _coords(np, a) - _coords(np, b)
    bc = _coords(np, c) - _coords(np, b)
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def classify_posture(
    np: Any,
    landmarks: list[Any],
    world_landmarks: list[Any] | None,
    *,
    visibility_threshold: float = 0.5,
    forward_lean_degrees: float = 20.0,
    hunch_ratio_threshold: float = 0.25,
    head_down_degrees: float = 25.0,
) -> PostureObservation:
    if len(landmarks) < 29:
        return PostureObservation()

    world = world_landmarks if world_landmarks and len(world_landmarks) >= len(landmarks) else landmarks
    nose = landmarks[0]
    ears = [point for point in (landmarks[7], landmarks[8]) if _valid(point, visibility_threshold)]
    shoulders = [landmarks[11], landmarks[12]]
    hips = [landmarks[23], landmarks[24]]
    upper_points = [*shoulders, *hips]
    face_visible = _valid(nose, visibility_threshold) or bool(ears)
    if not face_visible or not all(_valid(point, visibility_threshold) for point in upper_points):
        return PostureObservation()

    valid_legs: list[tuple[int, int, int]] = []
    for indices in ((23, 25, 27), (24, 26, 28)):
        if all(_valid(landmarks[index], visibility_threshold) for index in indices):
            valid_legs.append(indices)
    body_coverage = "full_body" if valid_legs else "upper_body"

    world_shoulders = [world[11], world[12]]
    world_hips = [world[23], world[24]]
    shoulder_mid = _midpoint(np, world_shoulders)
    hip_mid = _midpoint(np, world_hips)
    torso = shoulder_mid - hip_mid
    torso_length = float(np.linalg.norm(torso))
    torso_angle = float(np.degrees(np.arctan2(np.linalg.norm(torso[[0, 2]]), abs(torso[1]) + 1e-8)))

    metrics: dict[str, float] = {
        "torso_angle_degrees": torso_angle,
        "torso_length": torso_length,
    }
    issues: list[str] = []
    if torso_angle > forward_lean_degrees:
        issues.append("forward_lean")

    world_ears = [world[7] if point is landmarks[7] else world[8] for point in ears]
    if world_ears and torso_length > 1e-8:
        ear_mid = _midpoint(np, world_ears)
        neck_horizontal = float(np.linalg.norm((ear_mid - shoulder_mid)[[0, 2]]))
        hunch_ratio = neck_horizontal / torso_length
        metrics["hunch_ratio"] = hunch_ratio
        if hunch_ratio > hunch_ratio_threshold:
            issues.append("hunched")

        if _valid(nose, visibility_threshold):
            nose_xyz = _coords(np, world[0])
            nose_from_ear = nose_xyz - ear_mid
            head_down_angle = float(
                np.degrees(np.arctan2(nose_from_ear[1], np.linalg.norm(nose_from_ear[[0, 2]]) + 1e-8))
            )
            metrics["head_down_degrees"] = head_down_angle
            if head_down_angle > head_down_degrees:
                issues.append("head_down")

    seated_state = "seated"
    used_points = [*upper_points, nose if _valid(nose, visibility_threshold) else ears[0]]
    if valid_legs:
        knee_angles = [_angle(np, world[hip], world[knee], world[ankle]) for hip, knee, ankle in valid_legs]
        knee_angle = float(sum(knee_angles) / len(knee_angles))
        metrics["knee_angle_degrees"] = knee_angle
        for hip, knee, ankle in valid_legs:
            used_points.extend((landmarks[hip], landmarks[knee], landmarks[ankle]))
        if 60.0 <= knee_angle <= 140.0:
            seated_state = "seated"
        elif knee_angle > 155.0:
            seated_state = "not_seated"
        else:
            seated_state = "unknown"

    confidence = float(sum(_point_score(point) for point in used_points) / len(used_points))
    ordered_issues = tuple(issue for issue in ("forward_lean", "hunched", "head_down") if issue in issues)
    if seated_state == "not_seated":
        return PostureObservation(
            body_coverage=body_coverage,
            seated_state=seated_state,
            posture_code="not_seated",
            confidence=confidence,
            label="非坐姿（暂不评估）",
            metrics=metrics,
        )
    if seated_state == "unknown":
        return PostureObservation(
            body_coverage=body_coverage,
            seated_state=seated_state,
            confidence=confidence,
            metrics=metrics,
        )

    posture_code = ordered_issues[0] if ordered_issues else "upright"
    label = "坐姿" + ("、".join(POSTURE_ISSUE_LABELS[issue] for issue in ordered_issues) or "端正")
    return PostureObservation(
        body_coverage=body_coverage,
        seated_state=seated_state,
        posture_code=posture_code,
        posture_issues=ordered_issues,
        confidence=confidence,
        label=label,
        metrics=metrics,
    )


@dataclass
class _PostureState:
    candidate_signature: tuple[str, tuple[str, ...], str] | None = None
    candidate_count: int = 0
    missing_count: int = 0
    stable: PostureObservation | None = None


class PostureSmoother:
    def __init__(self) -> None:
        self._states: dict[str, _PostureState] = {}

    def update(self, device_id: str, observation: PostureObservation) -> PostureObservation:
        state = self._states.setdefault(device_id, _PostureState())
        if observation.valid:
            state.missing_count = 0
            if state.stable and observation.signature == state.stable.signature:
                state.candidate_signature = None
                state.candidate_count = 0
                state.stable = replace(observation, fresh=True)
                return state.stable

            if observation.signature == state.candidate_signature:
                state.candidate_count += 1
            else:
                state.candidate_signature = observation.signature
                state.candidate_count = 1

            if state.candidate_count >= 2:
                state.stable = replace(observation, fresh=True)
                state.candidate_signature = None
                state.candidate_count = 0
                return state.stable
            if state.stable:
                return replace(state.stable, fresh=False)
            return replace(observation, posture_code="unknown", posture_issues=(), label="姿态确认中", fresh=False)

        state.candidate_signature = None
        state.candidate_count = 0
        state.missing_count += 1
        if state.stable and state.missing_count <= 2:
            return replace(state.stable, fresh=False)
        return replace(observation, label="姿态暂不可判", fresh=False)
