from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core import config
from app.db import models
from app.schemas import AiDecision, CommandMessage, TelemetryIn
from app.services.analysis import resolve_recent_image, run_ai_analysis
from app.services.autopilot import AutoPilot
from app.services.llm import LLMService, extract_json_object
from app.services.mqtt_ingest import ingest_mqtt_message
from app.services.telemetry import record_telemetry


def make_settings(**overrides) -> config.Settings:
    return config.Settings(_env_file=None, **overrides)


def naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def test_autopilot_settings_normalize_and_validate_controlled_values():
    settings = make_settings(autopilot_trigger_levels="alert,watch,alert", autopilot_min_confidence=0.75)
    assert settings.autopilot_trigger_levels == ["alert", "watch"]
    assert settings.autopilot_min_confidence == 0.75

    with pytest.raises(ValidationError):
        make_settings(autopilot_trigger_levels="danger")
    with pytest.raises(ValidationError):
        make_settings(autopilot_min_confidence=1.1)


class FakeMqtt:
    def __init__(self):
        self.published = []

    async def publish_json(self, topic, payload, qos=1, retain=False):
        self.published.append((topic, payload, qos, retain))
        return True


class FakeLLM:
    def __init__(self, decision: AiDecision):
        self.decision = decision
        self.calls = []

    async def analyze(self, device_state, *, image_path=None):
        self.calls.append((device_state, image_path))
        return self.decision


def make_decision(command_type="window.open", confidence=0.9, risk="medium") -> AiDecision:
    return AiDecision(
        command=CommandMessage(type=command_type, source="llm", confidence=confidence, reason="测试决策"),
        risk_level=risk,
        summary="测试决策",
        model="fake",
    )


ALERT_TELEMETRY = {
    "sensors": {"temperature_c": 27.0, "tvoc_ppb": 900, "eco2_ppm": 1400},
    "state": {"window_open": False, "alarm_on": False, "manual_override": False},
    "fusion": {
        "air_quality": "alert",
        "recommend_open_window": True,
        "alarm_enabled": True,
        "reason": "污染物浓度过高",
    },
}


# ---- LLM 服务 ----


def test_mock_llm_recommends_window_open():
    service = LLMService(make_settings(llm_endpoint="mock"))
    snapshot = {"telemetry": ALERT_TELEMETRY}
    decision = asyncio.run(service.analyze(snapshot))
    assert decision.command.type == "window.open"
    assert decision.command.confidence == 0.9
    assert decision.model == "mock"


def test_mock_llm_returns_none_when_normal():
    service = LLMService(make_settings(llm_endpoint="mock"))
    snapshot = {"telemetry": {"fusion": {"air_quality": "good"}, "state": {}}}
    decision = asyncio.run(service.analyze(snapshot))
    assert decision.command.type == "none"


def test_extract_json_object_strips_code_fences():
    content = '```json\n{"type": "none", "confidence": 0.5, "reason": "ok"}\n```'
    assert extract_json_object(content)["type"] == "none"


def test_extract_json_object_joins_content_parts():
    parts = [
        {"type": "text", "text": '{"type": "alarm.on"'},
        {"type": "text", "text": ', "confidence": 1}'},
    ]
    assert extract_json_object(parts)["type"] == "alarm.on"


def test_build_messages_attaches_image_as_base64():
    service = LLMService(make_settings(llm_vision_enabled=True))
    messages = service._build_messages({"device_id": "esp32s3-001"}, b"\xff\xd8\xff\xd9")
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_messages_text_only_without_image():
    service = LLMService(make_settings())
    messages = service._build_messages({"device_id": "esp32s3-001"}, None)
    assert isinstance(messages[1]["content"], str)


def test_response_format_variants():
    assert LLMService(make_settings(llm_response_format="json_object"))._response_format() == {"type": "json_object"}
    schema_format = LLMService(make_settings(llm_response_format="json_schema"))._response_format()
    assert schema_format["type"] == "json_schema"
    assert LLMService(make_settings(llm_response_format="none"))._response_format() is None


def test_thinking_settings_are_validated():
    settings = make_settings(llm_thinking_enabled=True, llm_reasoning_effort="max")
    assert settings.llm_thinking_enabled is True
    assert settings.llm_reasoning_effort == "max"


# ---- 视觉附图条件 ----


def test_resolve_recent_image_returns_fresh_file(tmp_path):
    settings = make_settings(uploads_dir=tmp_path, llm_image_max_age_seconds=600)
    device_dir = tmp_path / "esp32s3-001"
    device_dir.mkdir()
    (device_dir / "a.jpg").write_bytes(b"jpeg")
    asset = models.ImageAsset(device_id="esp32s3-001", filename="a.jpg", url="x", created_at=naive_utc_now())
    assert resolve_recent_image(settings, asset) == device_dir / "a.jpg"


def test_resolve_recent_image_skips_stale_asset(tmp_path):
    settings = make_settings(uploads_dir=tmp_path, llm_image_max_age_seconds=600)
    device_dir = tmp_path / "esp32s3-001"
    device_dir.mkdir()
    (device_dir / "a.jpg").write_bytes(b"jpeg")
    asset = models.ImageAsset(
        device_id="esp32s3-001",
        filename="a.jpg",
        url="x",
        created_at=naive_utc_now() - timedelta(seconds=3600),
    )
    assert resolve_recent_image(settings, asset) is None


def test_resolve_recent_image_skips_missing_file(tmp_path):
    settings = make_settings(uploads_dir=tmp_path)
    asset = models.ImageAsset(device_id="esp32s3-001", filename="gone.jpg", url="x", created_at=naive_utc_now())
    assert resolve_recent_image(settings, asset) is None


def test_resolve_recent_image_disabled(tmp_path):
    settings = make_settings(uploads_dir=tmp_path, llm_vision_enabled=False)
    asset = models.ImageAsset(device_id="esp32s3-001", filename="a.jpg", url="x", created_at=naive_utc_now())
    assert resolve_recent_image(settings, asset) is None


# ---- 分析管线 ----


def test_run_ai_analysis_publishes_high_confidence(client):
    from app.db.session import SessionLocal

    fake_mqtt = FakeMqtt()
    llm = FakeLLM(make_decision(confidence=0.9))
    db = SessionLocal()
    try:
        payload = asyncio.run(run_ai_analysis(db, "esp32s3-001", llm, fake_mqtt, trigger="test"))
        command = db.query(models.Command).filter(models.Command.command_id == payload["command"]["command_id"]).one()
        ai_result = db.query(models.AiResult).order_by(models.AiResult.id.desc()).first()
    finally:
        db.close()

    assert payload["published"] is True
    assert command.status == "published"
    assert ai_result.risk_level == "medium"
    assert len(fake_mqtt.published) == 1
    assert fake_mqtt.published[0][0] == "devices/esp32s3-001/command"


def test_run_ai_analysis_low_confidence_stays_pending(client):
    from app.db.session import SessionLocal

    fake_mqtt = FakeMqtt()
    llm = FakeLLM(make_decision(confidence=0.3))
    db = SessionLocal()
    try:
        payload = asyncio.run(run_ai_analysis(db, "esp32s3-001", llm, fake_mqtt, trigger="test"))
        command = db.query(models.Command).filter(models.Command.command_id == payload["command"]["command_id"]).one()
    finally:
        db.close()

    assert payload["published"] is False
    assert command.status == "pending"
    assert fake_mqtt.published == []


# ---- 自动决策闭环 ----


def test_autopilot_trigger_rules_and_cooldown():
    pilot = AutoPilot(make_settings(autopilot_cooldown_seconds=120), None)
    good = {"fusion": {"air_quality": "good", "alarm_enabled": False}}
    alert = {"fusion": {"air_quality": "alert", "alarm_enabled": False}}

    assert pilot.evaluate_trigger(good) is None
    assert pilot.should_run("dev", alert) == "air_quality=alert"

    # 冷却期现在由 run_once 在实际执行时记账，
    # should_run 自身不再消费/重置冷却计时器
    import time

    pilot._last_run["dev"] = time.monotonic()
    assert pilot.should_run("dev", alert) is None  # 冷却期内不再触发


def test_autopilot_alarm_enabled_triggers():
    pilot = AutoPilot(make_settings(), None)
    payload = {"fusion": {"air_quality": "good", "alarm_enabled": True}}
    assert pilot.evaluate_trigger(payload) == "alarm_enabled"


def test_autopilot_disabled_skips_and_toggle_restores():
    pilot = AutoPilot(make_settings(autopilot_enabled=False), None)
    alert = {"fusion": {"air_quality": "alert"}}
    assert pilot.should_run("dev", alert) is None
    pilot.set_enabled("dev", True)
    assert pilot.should_run("dev", alert) == "air_quality=alert"


def test_ingest_alert_telemetry_matches_autopilot_trigger(client):
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        envelope = ingest_mqtt_message(db, "devices/esp32s3-001/telemetry", dict(ALERT_TELEMETRY))
    finally:
        db.close()

    assert envelope is not None and envelope.type == "telemetry"
    pilot = AutoPilot(make_settings(), None)
    assert pilot.should_run("esp32s3-001", envelope.payload) == "air_quality=alert"


def test_autopilot_endpoints_toggle_and_latest_reflects(client):
    state = client.get("/api/devices/esp32s3-001/autopilot")
    assert state.status_code == 200
    assert state.json()["enabled"] is True

    updated = client.put("/api/devices/esp32s3-001/autopilot", json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    assert client.get("/api/devices/esp32s3-001/autopilot").json()["enabled"] is False
    assert client.get("/api/devices/esp32s3-001/latest").json()["autopilot"]["enabled"] is False


def test_analyze_route_broadcasts_analyzing_then_result(client):
    settings = config.get_settings()
    settings.llm_endpoint = "mock"

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        record_telemetry(db, TelemetryIn.model_validate({"device_id": "esp32s3-001", **ALERT_TELEMETRY}))
    finally:
        db.close()

    with client.websocket_connect("/ws/devices/esp32s3-001") as websocket:
        response = client.post("/api/devices/esp32s3-001/ai/analyze")
        assert response.status_code == 200
        first = websocket.receive_json()
        second = websocket.receive_json()

    assert first["type"] == "ai_analyzing"
    assert first["payload"]["trigger"] == "manual"
    assert second["type"] == "ai_result"
    body = response.json()
    assert body["command"]["type"] == "window.open"
    assert body["risk_level"] == "medium"
    # 测试环境没有真实 MQTT 连接，publish 失败时不得谎报 published
    assert body["published"] is False


def test_ai_report_uses_real_period_data_and_mock_llm(client):
    settings = config.get_settings()
    settings.llm_endpoint = "mock"

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        record_telemetry(db, TelemetryIn.model_validate({"device_id": "report-device", **ALERT_TELEMETRY}))
    finally:
        db.close()

    response = client.post("/api/devices/report-device/ai/report", json={"period": "day"})
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "day"
    assert body["model"] == "mock"
    assert body["coverage"]["sample_count"] == 1
    assert body["metrics"]["eco2_max_ppm"] == 1400
    assert body["metrics"]["alert_bucket_count"] == 1
    assert body["risk_level"] == "medium"
    assert body["recommendations"]


def test_ai_report_rejects_empty_period(client):
    response = client.post("/api/devices/no-data/ai/report", json={"period": "hour"})
    assert response.status_code == 404
    assert "没有遥测数据" in response.json()["detail"]
