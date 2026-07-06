from __future__ import annotations

from app.core import config
from app.schemas import TelemetryIn
from app.services.commands import create_command, validate_command_type
from app.services.llm import LLMService
from app.services.telemetry import record_telemetry


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
                state={"window_open": False, "alarm_on": False, "manual_override": False},
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

    history = client.get("/api/devices/esp32s3-001/history")
    assert history.status_code == 200
    assert history.json()[0]["fusion"]["air_quality"] == "good"


def test_manual_command_is_validated_and_stored(client):
    response = client.post(
        "/api/devices/esp32s3-001/commands",
        json={"type": "window.open", "parameter": {}, "reason": "manual"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "window.open"
    assert payload["source"] == "frontend"


def test_image_upload(client):
    response = client.post(
        "/api/devices/esp32s3-001/images",
        files={"file": ("image.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["url"].startswith("http://testserver/uploads/esp32s3-001/")


def test_llm_invalid_command_falls_back_to_none(client, monkeypatch):
    settings = config.get_settings()
    settings.llm_endpoint = "http://example.invalid/v1/chat/completions"
    settings.llm_api_key = "test"
    service = LLMService(settings)
    monkeypatch.setattr(service, "_call_openai_compatible", lambda state: {"type": "door.unlock", "confidence": 1})
    command = service.analyze({"device_id": "esp32s3-001"})
    assert command.type == "none"
    assert "不允许" in command.reason


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
