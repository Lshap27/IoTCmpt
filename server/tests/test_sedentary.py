from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.triggers import enqueue_event_run
from app.core.config import get_settings
from app.db import models
from app.services.sedentary import detect_sedentary_event


def test_sedentary_pose_sequence_creates_event_and_ai_run(client):
    response = client.put(
        "/api/v1/devices/sedentary-device/automation-policy",
        json={
            "enabled": True,
            "event_trigger_enabled": True,
            "vision_interval_seconds": 5,
            "sedentary_trigger_enabled": True,
            "sedentary_threshold_seconds": 5,
        },
    )
    assert response.status_code == 200

    from app.db.session import SessionLocal

    started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
    with SessionLocal() as db:
        image = models.ImageAsset(
            device_id="sedentary-device",
            filename="pose.jpg",
            url="/uploads/sedentary-device/pose.jpg",
            content_type="image/jpeg",
            size_bytes=1,
        )
        db.add(image)
        db.flush()
        first = models.PoseResult(
            device_id="sedentary-device",
            source_image_id=image.id,
            human_present=True,
            label="坐姿端正",
            confidence=0.9,
            raw_payload={"seated_state": "seated", "posture_code": "upright"},
            created_at=started_at,
        )
        second = models.PoseResult(
            device_id="sedentary-device",
            source_image_id=image.id,
            human_present=True,
            label="坐姿端正",
            confidence=0.9,
            raw_payload={"seated_state": "seated", "posture_code": "upright"},
            created_at=started_at + timedelta(seconds=5),
        )
        db.add_all([first, second])
        db.commit()
        first_id, second_id = first.id, second.id

    assert detect_sedentary_event(SessionLocal, "sedentary-device", first_id) is None
    event = detect_sedentary_event(SessionLocal, "sedentary-device", second_id)
    assert event is not None
    assert event["type"] == "posture.sedentary"
    assert detect_sedentary_event(SessionLocal, "sedentary-device", second_id) is None

    enqueue_event_run(SessionLocal, get_settings(), "sedentary-device", event["type"])
    with SessionLocal() as db:
        stored_event = db.query(models.DeviceEvent).filter_by(device_id="sedentary-device").one()
        run = db.query(models.AiRun).filter_by(device_id="sedentary-device").one()
        assert stored_event.raw_payload["threshold_seconds"] == 5
        assert run.status == "queued"
        assert run.input_payload["event_type"] == "posture.sedentary"


def test_automation_policy_demo_intervals_accept_five_seconds(client):
    response = client.put(
        "/api/v1/devices/demo-device/automation-policy",
        json={
            "patrol_interval_seconds": 5,
            "patrol_force_interval_seconds": 5,
            "vision_interval_seconds": 5,
            "sedentary_threshold_seconds": 5,
            "strategy_min_interval_seconds": 5,
            "strategy_force_interval_seconds": 5,
        },
    )
    assert response.status_code == 200
    assert response.json()["sedentary_threshold_seconds"] == 5

    invalid = client.put(
        "/api/v1/devices/demo-device/automation-policy",
        json={"sedentary_threshold_seconds": 4},
    )
    assert invalid.status_code == 422
