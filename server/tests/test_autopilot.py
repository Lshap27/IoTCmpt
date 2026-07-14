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

    assert make_settings().sedentary_threshold_seconds == 7200
    assert make_settings(sedentary_threshold_seconds=5).sedentary_threshold_seconds == 5
    with pytest.raises(ValidationError):
        make_settings(sedentary_threshold_seconds=4)


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
        "alarm_enabled": False,
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


def test_general_analysis_never_attaches_an_image(client, tmp_path):
    from app.db.session import SessionLocal

    llm = FakeLLM(make_decision(command_type="none"))
    db = SessionLocal()
    try:
        asyncio.run(run_ai_analysis(db, "esp32s3-001", llm, FakeMqtt(), trigger="manual"))
    finally:
        db.close()
    assert llm.calls[0][1] is None


def test_open_window_blocks_duplicate_open_decision(client):
    from app.db.session import SessionLocal

    db = SessionLocal()
    mqtt = FakeMqtt()
    try:
        record_telemetry(
            db,
            TelemetryIn.model_validate(
                {
                    "device_id": "esp32s3-001",
                    **ALERT_TELEMETRY,
                    "state": {"window_open": True, "alarm_on": False, "manual_override": False},
                }
            ),
        )
        payload = asyncio.run(run_ai_analysis(db, "esp32s3-001", FakeLLM(make_decision()), mqtt))
    finally:
        db.close()
    assert payload["command"]["type"] == "none"
    assert "窗户已经打开" in payload["reason"]
    assert mqtt.published == []


def test_runtime_automation_settings_are_reported():
    pilot = AutoPilot(make_settings(), None)
    pilot.update(
        "dev",
        vision_interval_enabled=True,
        vision_interval_seconds=90,
        sedentary_threshold_seconds=1800,
        smoke_silence_seconds=45,
    )
    state = pilot.describe("dev")
    assert state["vision_interval_enabled"] is True
    assert state["vision_interval_seconds"] == 90
    assert state["sedentary_threshold_seconds"] == 1800
    assert state["smoke_silence_seconds"] == 45


def test_sedentary_timer_survives_unknown_pose_and_resets_only_after_sustained_exit(monkeypatch):
    class FakeDb:
        def query(self, _model):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return None

        def close(self):
            pass

    monkeypatch.setattr("app.services.autopilot.SessionLocal", FakeDb)
    pilot = AutoPilot(make_settings(autopilot_enabled=False), None)
    now = 0.0
    monkeypatch.setattr("app.services.autopilot._monotonic", lambda: now)

    pilot.on_pose_result("dev", {"human_present": True, "seated_state": "seated", "label": "坐姿端正"})
    assert pilot._sedentary_started["dev"] == 0.0

    now = 2.0
    pilot.on_pose_result("dev", {"human_present": True, "seated_state": "unknown", "label": "姿态暂不可判"})
    now = 4.0
    pilot.on_pose_result("dev", {"human_present": True, "seated_state": "unknown", "label": "姿态暂不可判"})
    assert pilot._sedentary_started["dev"] == 0.0

    now = 5.0
    pilot.on_pose_result("dev", {"human_present": True, "seated_state": "not_seated", "label": "非坐姿"})
    now = 14.9
    pilot.on_pose_result("dev", {"human_present": True, "seated_state": "not_seated", "label": "非坐姿"})
    assert pilot._sedentary_started["dev"] == 0.0
    now = 15.0
    pilot.on_pose_result("dev", {"human_present": True, "seated_state": "not_seated", "label": "非坐姿"})
    assert "dev" not in pilot._sedentary_started

    now = 20.0
    pilot.on_pose_result("dev", {"human_present": True, "seated_state": "seated", "label": "坐姿驼背"})
    now = 49.9
    pilot.on_pose_result("dev", {"human_present": False, "seated_state": "unknown", "label": "未检测到人体"})
    assert pilot._sedentary_started["dev"] == 20.0
    now = 50.0
    pilot.on_pose_result("dev", {"human_present": False, "seated_state": "unknown", "label": "未检测到人体"})
    assert "dev" not in pilot._sedentary_started


# ---- 自动决策闭环 ----


def test_autopilot_disabled_skips_and_toggle_restores():
    pilot = AutoPilot(make_settings(autopilot_enabled=False), None)
    assert pilot.is_enabled("dev") is False
    pilot.set_enabled("dev", True)
    assert pilot.is_enabled("dev") is True


def test_firmware_rule_mqtt_events_do_not_call_llm_or_publish_commands(client):
    pilot = client.app.state.autopilot
    llm = FakeLLM(make_decision())
    mqtt = FakeMqtt()
    pilot.llm = llm
    pilot.mqtt_service = mqtt
    handler = client.app.state.mqtt_message_handler

    asyncio.run(handler("devices/esp32s3-001/telemetry", dict(ALERT_TELEMETRY)))
    asyncio.run(
        handler(
            "devices/esp32s3-001/event",
            {"type": "smoke.detected", "severity": "critical", "message": "MQ-2 检测到烟雾"},
        )
    )

    assert llm.calls == []
    assert mqtt.published == []


def test_autopilot_endpoints_toggle_and_latest_reflects(client):
    state = client.get("/api/devices/esp32s3-001/autopilot")
    assert state.status_code == 200
    assert state.json()["enabled"] is True

    updated = client.put("/api/devices/esp32s3-001/autopilot", json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    assert client.get("/api/devices/esp32s3-001/autopilot").json()["enabled"] is False
    assert client.get("/api/devices/esp32s3-001/latest").json()["autopilot"]["enabled"] is False

    minimum = client.put("/api/devices/esp32s3-001/autopilot", json={"sedentary_threshold_seconds": 5})
    assert minimum.status_code == 200
    assert minimum.json()["sedentary_threshold_seconds"] == 5
    assert client.put("/api/devices/esp32s3-001/autopilot", json={"sedentary_threshold_seconds": 4}).status_code == 422

    schema = client.get("/openapi.json").json()["components"]["schemas"]["AutopilotState"]
    assert schema["properties"]["trigger_levels"]["deprecated"] is True


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
