from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.db import models
from app.services.events import serialize_event


def _is_seated(result: models.PoseResult) -> bool:
    raw = result.raw_payload or {}
    return result.human_present and raw.get("seated_state") == "seated"


def detect_sedentary_event(
    session_factory: sessionmaker[Session],
    device_id: str,
    pose_id: int,
) -> dict[str, Any] | None:
    """Create one sedentary event per uninterrupted seated session."""
    with session_factory() as db:
        policy = db.query(models.AutomationPolicy).filter_by(device_id=device_id).one_or_none()
        if policy is None or not policy.enabled or not policy.sedentary_trigger_enabled:
            return None

        current = db.get(models.PoseResult, pose_id)
        if current is None or current.device_id != device_id or current.created_at is None or not _is_seated(current):
            return None

        last_event = (
            db.query(models.DeviceEvent)
            .filter_by(device_id=device_id, type="posture.sedentary")
            .order_by(models.DeviceEvent.created_at.desc(), models.DeviceEvent.id.desc())
            .first()
        )
        if last_event is not None:
            if current.created_at <= last_event.created_at:
                return None
            observations_since_reminder = (
                db.query(models.PoseResult)
                .filter(
                    models.PoseResult.device_id == device_id,
                    models.PoseResult.created_at > last_event.created_at,
                    models.PoseResult.created_at <= current.created_at,
                )
                .order_by(models.PoseResult.created_at, models.PoseResult.id)
                .all()
            )
            if observations_since_reminder and all(_is_seated(row) for row in observations_since_reminder):
                return None

        threshold_seconds = policy.sedentary_threshold_seconds
        cutoff = current.created_at - timedelta(seconds=threshold_seconds)
        anchor = (
            db.query(models.PoseResult)
            .filter(models.PoseResult.device_id == device_id, models.PoseResult.created_at <= cutoff)
            .order_by(models.PoseResult.created_at.desc(), models.PoseResult.id.desc())
            .first()
        )
        if anchor is None or not _is_seated(anchor):
            return None

        observations = (
            db.query(models.PoseResult)
            .filter(
                models.PoseResult.device_id == device_id,
                models.PoseResult.created_at >= anchor.created_at,
                models.PoseResult.created_at <= current.created_at,
            )
            .order_by(models.PoseResult.created_at, models.PoseResult.id)
            .all()
        )
        max_gap_seconds = max(15, policy.vision_interval_seconds * 3)
        previous = None
        for observation in observations:
            if not _is_seated(observation):
                return None
            if (
                previous is not None
                and (observation.created_at - previous.created_at).total_seconds() > max_gap_seconds
            ):
                return None
            previous = observation

        duration_seconds = int((current.created_at - anchor.created_at).total_seconds())
        event = models.DeviceEvent(
            device_id=device_id,
            type="posture.sedentary",
            severity="warning",
            message=f"连续坐姿已达到 {threshold_seconds} 秒，请起身活动。",
            raw_payload={
                "type": "posture.sedentary",
                "source": "pose_analysis",
                "threshold_seconds": threshold_seconds,
                "duration_seconds": duration_seconds,
                "started_at": anchor.created_at.isoformat(timespec="seconds"),
                "pose_id": current.id,
            },
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return serialize_event(event)
