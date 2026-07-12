from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

from app.core import config
from app.db import models
from app.schemas import TelemetryIn
from app.services.commands import create_command, validate_command_type
from app.services.llm import LLMService
from app.services.mqtt_ingest import ingest_mqtt_message
from app.services.pose import PoseService, _pose_label
from app.services.telemetry import fetch_history_bucketed, record_telemetry


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "aiot-gateway"


def test_record_telemetry_and_latest(client):
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        record_telemetry(
            db,
            TelemetryIn(
                device_id="esp32s3-001",
                sensors={"temperature_c": 25.2, "humidity_percent": 69.2, "tvoc_ppb": 120},
                state={"window_open": False, "alarm_on": False, "manual_override": False, "led_on": True},
                fusion={"air_quality": "good", "reason": "ok"},
            ),
        )
    finally:
        db.close()

    latest = client.get("/api/devices/esp32s3-001/latest")
    assert latest.status_code == 200
    payload = latest.json()
    assert payload["device"]["status"] == "online"
    assert payload["telemetry"]["sensors"]["temperature_c"] == 25.2
    assert payload["telemetry"]["state"]["led_on"] is True

    history = client.get("/api/devices/esp32s3-001/history")
    assert history.status_code == 200
    assert history.json()[0]["fusion"]["air_quality"] == "good"


def test_bucketed_history_serializes_report_and_light_fields():
    class Result:
        def mappings(self):
            return [
                {
                    "bucket": datetime(2026, 7, 12, 1, 0, 0),
                    "temperature_c": 25.0,
                    "temperature_min_c": 23.0,
                    "temperature_max_c": 28.0,
                    "humidity_percent": 70.0,
                    "humidity_min_percent": 60.0,
                    "humidity_max_percent": 80.0,
                    "tvoc_ppb": 180.0,
                    "hcho_ug_m3": 25.0,
                    "eco2_ppm": 800.0,
                    "eco2_max_ppm": 1200.0,
                    "light_is_dark": True,
                    "smoke_detected": False,
                    "window_open": True,
                    "alarm_on": True,
                    "led_on": False,
                    "air_quality": "watch",
                    "sample_count": 12,
                }
            ]

    class Db:
        def execute(self, _statement, parameters):
            assert parameters == {"bucket": 3600, "device_id": "esp32s3-001", "limit": 168}
            return Result()

    payload = fetch_history_bucketed(Db(), "esp32s3-001", 3600, 168)
    assert payload[0]["temperature_min_c"] == 23.0
    assert payload[0]["eco2_max_ppm"] == 1200.0
    assert payload[0]["light_is_dark"] is True


def test_manual_command_is_validated_and_stored(client):
    response = client.post(
        "/api/devices/esp32s3-001/commands",
        json={"type": "window.open", "parameter": {}, "reason": "manual"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "window.open"
    assert payload["source"] == "frontend"

    led = client.post(
        "/api/devices/esp32s3-001/commands",
        json={"type": "led.on", "parameter": {}, "reason": "manual"},
    )
    assert led.status_code == 200
    assert led.json()["type"] == "led.on"


def test_image_upload(client):
    response = client.post(
        "/api/devices/esp32s3-001/images",
        files={"file": ("image.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["url"].startswith("http://testserver/uploads/esp32s3-001/")


def test_image_retention_keeps_newest_100(client):
    paths = []
    for index in range(101):
        response = client.post(
            "/api/devices/esp32s3-001/images",
            files={"file": (f"image-{index}.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
        )
        assert response.status_code == 200
        paths.append(response.json()["url"].removeprefix("http://testserver"))

    assert client.get(paths[0]).status_code == 404
    assert client.get(paths[-1]).status_code == 200


def test_llm_invalid_command_falls_back_to_none(client, monkeypatch):
    settings = config.get_settings()
    settings.llm_endpoint = "http://example.invalid/v1/chat/completions"
    settings.llm_api_key = "test"
    service = LLMService(settings)

    async def fake_call(state, *, image_path=None):
        return {"type": "door.unlock", "confidence": 1}

    monkeypatch.setattr(service, "_call_openai_compatible", fake_call)
    decision = asyncio.run(service.analyze({"device_id": "esp32s3-001"}))
    assert decision.command.type == "none"
    assert "不可执行" in decision.command.reason


def test_mock_llm_never_opens_window_for_smoke_only(client):
    settings = config.get_settings()
    settings.llm_endpoint = "mock"
    service = LLMService(settings)
    decision = asyncio.run(
        service.analyze(
            {
                "telemetry": {
                    "sensors": {"smoke_detected": True},
                    "state": {"window_open": False, "alarm_on": True},
                    "fusion": {"air_quality": "alert", "alarm_enabled": True},
                }
            }
        )
    )
    assert decision.command.type == "none"


def test_command_validation_rejects_unknown():
    assert validate_command_type("door.unlock") == "none"


def test_service_command_creation(client):
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        command = create_command(db, "esp32s3-001", "alarm.on", reason="rule")
        assert command.type == "alarm.on"
        assert command.status == "pending"
    finally:
        db.close()


def test_mqtt_malformed_telemetry_returns_error_envelope(client):
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        envelope = ingest_mqtt_message(
            db,
            "devices/esp32s3-001/telemetry",
            {"sensors": "not-an-object"},
        )
    finally:
        db.close()

    assert envelope is not None
    assert envelope.type == "error"
    assert envelope.device_id == "esp32s3-001"
    assert envelope.payload["topic"] == "devices/esp32s3-001/telemetry"


def test_mqtt_command_ack_updates_command_status(client):
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        command = create_command(db, "esp32s3-001", "window.open", reason="manual")
        envelope = ingest_mqtt_message(
            db,
            "devices/esp32s3-001/command_ack",
            {
                "command_id": command.command_id,
                "status": "executed",
                "message": "ok",
                "executed_at": "2026-07-07T00:00:00Z",
            },
        )
        updated = db.query(models.Command).filter(models.Command.command_id == command.command_id).one()
    finally:
        db.close()

    assert envelope is not None
    assert envelope.type == "command_ack"
    assert envelope.payload["known_command"] is True
    assert updated.status == "executed"
    assert updated.executed_at is not None


def test_command_http_broadcasts_websocket_event(client):
    with client.websocket_connect("/ws/devices/esp32s3-001") as websocket:
        response = client.post(
            "/api/devices/esp32s3-001/commands",
            json={"type": "alarm.on", "parameter": {}, "reason": "dashboard"},
        )
        assert response.status_code == 200
        event = websocket.receive_json()

    assert event["type"] == "command"
    assert event["device_id"] == "esp32s3-001"
    assert event["payload"]["type"] == "alarm.on"


def test_smoke_event_is_deduplicated_and_acknowledged(client):
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        first = ingest_mqtt_message(
            db,
            "devices/esp32s3-001/event",
            {"type": "smoke.detected", "severity": "critical", "message": "smoke"},
        )
        second = ingest_mqtt_message(
            db,
            "devices/esp32s3-001/event",
            {"type": "smoke.detected", "severity": "critical", "message": "smoke"},
        )
    finally:
        db.close()

    assert first is not None and second is not None
    assert first.payload["id"] == second.payload["id"]
    events = client.get("/api/devices/esp32s3-001/events?type=smoke.detected")
    assert events.status_code == 200
    assert len(events.json()) == 1
    event_id = events.json()[0]["id"]
    ack = client.post(f"/api/devices/esp32s3-001/events/{event_id}/ack")
    assert ack.status_code == 200
    assert ack.json()["acknowledged_at"] is not None


def test_pose_queue_keeps_only_latest_image(client):
    settings = config.get_settings()
    settings.pose_enabled = True
    service = PoseService(settings)

    async def exercise():
        await service.enqueue("esp32s3-001", 1)
        await service.enqueue("esp32s3-001", 2)
        return service.queue.get_nowait()

    assert asyncio.run(exercise()) == ("esp32s3-001", 2)


def test_pose_label_reports_standing_issues():
    points = [SimpleNamespace(x=0.5, y=0.5, visibility=1.0) for _ in range(33)]
    points[0] = SimpleNamespace(x=0.8, y=0.6, visibility=1.0)
    points[11] = SimpleNamespace(x=0.8, y=0.3, visibility=1.0)
    points[12] = SimpleNamespace(x=0.8, y=0.3, visibility=1.0)
    points[23] = SimpleNamespace(x=0.5, y=0.5, visibility=1.0)
    points[24] = SimpleNamespace(x=0.5, y=0.5, visibility=1.0)
    points[25] = SimpleNamespace(x=0.5, y=0.7, visibility=1.0)
    points[26] = SimpleNamespace(x=0.5, y=0.7, visibility=1.0)
    points[27] = SimpleNamespace(x=0.5, y=0.9, visibility=1.0)
    points[28] = SimpleNamespace(x=0.5, y=0.9, visibility=1.0)

    import numpy as np

    assert _pose_label(np, points) == "站姿驼背、低头"


def test_pose_service_rejects_missing_model(client, tmp_path):
    settings = config.get_settings()
    settings.pose_model_path = tmp_path / "missing.task"
    service = PoseService(settings)
    try:
        service.process_now("esp32s3-001", 1)
    except FileNotFoundError as exc:
        assert "pose model not found" in str(exc)
    else:
        raise AssertionError("missing pose model was accepted")


def test_latest_includes_pose_result(client):
    from app.db.session import SessionLocal

    upload = client.post(
        "/api/devices/esp32s3-001/images",
        files={"file": ("image.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
    ).json()
    db = SessionLocal()
    try:
        pose = models.PoseResult(
            device_id="esp32s3-001",
            source_image_id=upload["id"],
            human_present=True,
            label="坐姿低头",
            confidence=0.88,
            raw_payload={},
        )
        db.add(pose)
        db.commit()
    finally:
        db.close()

    latest = client.get("/api/devices/esp32s3-001/latest").json()
    assert latest["pose"]["label"] == "坐姿低头"
    assert latest["pose"]["source_image_url"].startswith("http://testserver/uploads/")
