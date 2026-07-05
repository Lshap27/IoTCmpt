from app.schemas import CloudCommandResponse, CloudExchangeRequest
from app.services.command_service import normalize_command
from app.services.llm_service import LLMClient


def test_sensor_upload_and_latest(client):
    response = client.post(
        "/api/upload_sensor",
        json={
            "temperature_in": 25.2,
            "humidity_in": 69.2,
            "temperature_out": 32.1,
            "humidity_out": 55,
            "co2": 450,
            "tvoc": 120,
            "hcho": 0.03,
            "light": 100,
            "air_quality": "good",
            "recommend_open_window": False,
            "alarm_enabled": False,
            "reason": "ok",
        },
    )
    assert response.status_code == 200
    latest = client.get("/api/latest").json()
    assert latest["temperature_in"] == 25.2
    assert latest["air_quality"] == "good"
    assert latest["human_presence"] == "unknown"


def test_upload_image_validates_and_saves(client, tiny_jpeg):
    response = client.post(
        "/api/upload_image",
        files={"file": ("image.jpg", tiny_jpeg, "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["image_url"].startswith("http://testserver/images/")


def test_detect_pose_returns_503_when_model_missing(client, tiny_jpeg):
    response = client.post(
        "/api/detect_pose",
        files={"file": ("image.jpg", tiny_jpeg, "image/jpeg")},
    )
    assert response.status_code == 503
    latest = client.get("/api/latest").json()
    assert latest["pose"] == "姿态检测服务未加载"


def test_legacy_command_normalizes_for_firmware(client):
    response = client.post("/api/command", json={"device": "window", "command": "open"})
    assert response.status_code == 200
    pending = client.get("/api/command/pending").json()
    assert pending["status"] == "success"
    assert pending["command"] == "window.open"
    ack = client.post(f"/api/command/ack/{pending['id']}")
    assert ack.status_code == 200
    assert client.get("/api/command/pending").json()["status"] == "empty"


def test_cloud_exchange_without_llm_returns_none(client):
    response = client.post(
        "/api/cloud/exchange",
        json={
            "model": "demo-model",
            "device_state": {"temperature_c": 32, "recommend_open_window": True},
            "allowed_commands": ["window.open", "window.close", "alarm.on", "alarm.off"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["command"] == "none"
    assert "LLM" in payload["reason"]


def test_llm_invalid_command_falls_back_to_none(monkeypatch):
    class Settings:
        llm_endpoint = "http://example.invalid/v1/chat/completions"
        llm_api_key = "test"
        llm_model = "test-model"
        llm_timeout_seconds = 1

    client = LLMClient(Settings())
    monkeypatch.setattr(client, "_call_openai_compatible", lambda request: {"command": "door.unlock", "confidence": 0.9})
    response: CloudCommandResponse = client.exchange(
        CloudExchangeRequest(device_state={}, allowed_commands=["window.open"])
    )
    assert response.command == "none"


def test_command_normalization_rejects_unknown():
    assert normalize_command("light", "on") == "alarm.on"
