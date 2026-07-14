from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.timeutil import iso_utc
from app.db import models
from app.services.commands import serialize_command
from app.services.pose import latest_pose_result, serialize_pose_result
from app.services.telemetry import serialize_telemetry


def latest_image_asset(db: Session, device_id: str) -> models.ImageAsset | None:
    return (
        db.query(models.ImageAsset)
        .filter(models.ImageAsset.device_id == device_id)
        .filter(models.ImageAsset.kind == "capture")
        .order_by(models.ImageAsset.created_at.desc())
        .first()
    )


def resolve_recent_image(
    settings: Settings,
    asset: models.ImageAsset | None,
    *,
    max_age_seconds: float | None = None,
) -> Path | None:
    """返回新鲜的本地图片路径；调用方决定普通分析或强制视觉分析的时效。"""
    if asset is None:
        return None
    if asset.created_at is None:
        return None
    age = datetime.now(UTC).replace(tzinfo=None) - asset.created_at
    if age.total_seconds() > (max_age_seconds or settings.llm_image_max_age_seconds):
        return None
    path = Path(settings.uploads_dir) / asset.device_id / asset.filename
    if not path.is_file():
        return None
    return path


def collect_device_snapshot(db: Session, device_id: str, *, include_trend: bool = False) -> dict[str, Any]:
    device = db.query(models.Device).filter(models.Device.device_id == device_id).one_or_none()
    telemetry = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.device_id == device_id)
        .order_by(models.Telemetry.sampled_at.desc())
        .first()
    )
    image = latest_image_asset(db, device_id)
    command = (
        db.query(models.Command)
        .filter(models.Command.device_id == device_id)
        .order_by(models.Command.created_at.desc())
        .first()
    )
    pose = latest_pose_result(db, device_id)

    snapshot: dict[str, Any] = {
        "device": {
            "device_id": device_id,
            "display_name": device.display_name if device else device_id,
            "status": device.status if device else "unknown",
            "last_seen_at": iso_utc(device.last_seen_at) if device else None,
        },
        "telemetry": serialize_telemetry(telemetry) if telemetry else None,
        "image": {"id": image.id, "url": image.url, "created_at": iso_utc(image.created_at)} if image else None,
        "pose": serialize_pose_result(db, pose) if pose else None,
        "command": serialize_command(command) if command else None,
    }

    if include_trend:
        rows = (
            db.query(models.Telemetry)
            .filter(models.Telemetry.device_id == device_id)
            .order_by(models.Telemetry.sampled_at.desc())
            .limit(10)
            .all()
        )
        snapshot["trend"] = [
            {
                "sampled_at": row.sampled_at.isoformat(timespec="seconds"),
                "temperature_c": row.temperature_c,
                "humidity_percent": row.humidity_percent,
                "tvoc_ppb": row.tvoc_ppb,
                "eco2_ppm": row.eco2_ppm,
                "air_quality": row.air_quality,
                "smoke_detected": row.smoke_detected,
                "led_on": row.led_on,
            }
            for row in reversed(rows)
        ]
        levels = {"unknown": 0, "good": 1, "watch": 2, "alert": 3}
        if len(rows) >= 2:
            oldest, newest = rows[-1], rows[0]
            old_level = levels.get(oldest.air_quality or "unknown", 0)
            new_level = levels.get(newest.air_quality or "unknown", 0)
            rising_pollutants = any(
                old is not None and new is not None and new > old * 1.1
                for old, new in ((oldest.tvoc_ppb, newest.tvoc_ppb), (oldest.eco2_ppm, newest.eco2_ppm))
            )
            snapshot["air_trend"] = (
                "worsening"
                if new_level > old_level or rising_pollutants
                else ("improving" if new_level < old_level else "stable")
            )
        else:
            snapshot["air_trend"] = "stable"
        state = (snapshot.get("telemetry") or {}).get("state") or {}
        snapshot["actions_already_taken"] = ["窗户已经打开"] if state.get("window_open") else []

    return snapshot
