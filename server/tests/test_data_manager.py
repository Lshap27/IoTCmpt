from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base
from app.tools.data_manager import DataToolError, cleanup_data, generate_demo_data, preview_data


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def iso(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat()


def add_device(db: Session, device_id: str = "esp32s3-001") -> None:
    db.add(models.Device(device_id=device_id, display_name=device_id, status="offline"))
    db.commit()


def test_preview_is_device_scoped_and_end_exclusive(db: Session):
    add_device(db)
    add_device(db, "other")
    start = datetime(2026, 7, 12)
    end = start + timedelta(hours=1)
    db.add_all(
        [
            models.Telemetry(device_id="esp32s3-001", sampled_at=start),
            models.Telemetry(device_id="esp32s3-001", sampled_at=end - timedelta(seconds=1)),
            models.Telemetry(device_id="esp32s3-001", sampled_at=end),
            models.Telemetry(device_id="other", sampled_at=start),
            models.DeviceEvent(device_id="esp32s3-001", type="demo", created_at=start),
        ]
    )
    db.commit()

    result = preview_data(db, "esp32s3-001", iso(start), iso(end))

    assert result["counts"]["telemetry"] == 2
    assert result["counts"]["events"] == 1


def test_cleanup_only_deletes_selected_categories_in_range(db: Session):
    add_device(db)
    start = datetime(2026, 7, 12)
    end = start + timedelta(hours=1)
    db.add_all(
        [
            models.Telemetry(device_id="esp32s3-001", sampled_at=start),
            models.Telemetry(device_id="esp32s3-001", sampled_at=end + timedelta(seconds=1)),
            models.DeviceEvent(device_id="esp32s3-001", type="keep-event", created_at=start),
            models.Notification(device_id="esp32s3-001", content="保留通知", created_at=start),
            models.ImageAsset(
                device_id="esp32s3-001",
                filename="keep.jpg",
                url="/uploads/keep.jpg",
                created_at=start,
            ),
        ]
    )
    db.commit()

    result = cleanup_data(db, "esp32s3-001", iso(start), iso(end), ["telemetry"])

    assert result["deleted"]["telemetry"] == 1
    assert db.query(models.Telemetry).count() == 1
    assert db.query(models.DeviceEvent).count() == 1
    assert db.query(models.Notification).count() == 1
    assert db.query(models.ImageAsset).count() == 1


def test_ai_cleanup_removes_commands_and_runs(db: Session):
    add_device(db)
    start = datetime(2026, 7, 12)
    end = start + timedelta(hours=1)
    db.add_all(
        [
            models.Command(
                command_id="demo-command",
                device_id="esp32s3-001",
                type="led.on",
                created_at=start,
            ),
            models.AiRun(
                run_id="demo-run",
                trace_id="demo-trace",
                device_id="esp32s3-001",
                kind="decision",
                trigger="manual",
                status="succeeded",
                created_at=start,
            ),
        ]
    )
    db.commit()

    result = cleanup_data(db, "esp32s3-001", iso(start), iso(end), ["ai"])

    assert result["deleted"]["ai"] == 2
    assert db.query(models.Command).count() == 0
    assert db.query(models.AiRun).count() == 0


def test_demo_generation_covers_all_stages_and_is_repeatable(db: Session):
    start = datetime(2026, 7, 12)
    end = start + timedelta(hours=1)

    first = generate_demo_data(db, "esp32s3-001", iso(start), iso(end), 60)
    first_values = [
        (row.sampled_at, row.air_quality, row.smoke_detected, row.window_open, row.led_on)
        for row in db.query(models.Telemetry).order_by(models.Telemetry.sampled_at).all()
    ]
    second = generate_demo_data(db, "esp32s3-001", iso(start), iso(end), 60)
    second_values = [
        (row.sampled_at, row.air_quality, row.smoke_detected, row.window_open, row.led_on)
        for row in db.query(models.Telemetry).order_by(models.Telemetry.sampled_at).all()
    ]

    assert first["generated"] == {"telemetry": 60, "events": 5}
    assert second["generated"] == first["generated"]
    assert first_values == second_values
    assert db.query(models.Telemetry).count() == 60
    assert {event.type for event in db.query(models.DeviceEvent).all()} == {
        "demo.stage.normal",
        "air.quality.watch",
        "air.quality.alert",
        "smoke.detected",
        "smoke.cleared",
    }
    assert {row.air_quality for row in db.query(models.Telemetry).all()} >= {"good", "watch", "alert"}
    assert any(row.smoke_detected for row in db.query(models.Telemetry).all())


def test_demo_generation_rejects_more_than_ten_thousand_samples(db: Session):
    start = datetime(2026, 7, 12)
    end = start + timedelta(hours=8)

    with pytest.raises(DataToolError, match="10000"):
        generate_demo_data(db, "esp32s3-001", iso(start), iso(end), 2.5)
