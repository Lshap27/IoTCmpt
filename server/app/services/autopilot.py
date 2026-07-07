from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import Settings
from app.db import models
from app.db.session import SessionLocal
from app.schemas import WebSocketEnvelope
from app.services.analysis import run_ai_analysis
from app.services.llm import LLMService
from app.services.mqtt import MqttService
from app.services.websocket import manager

LOGGER = logging.getLogger(__name__)


class AutoPilot:
    """遥测驱动的自动决策闭环：触发规则 + 冷却期 + 每设备开关。

    注意：不以 manual_override 作为跳过条件——云端开/关窗命令会让固件进入
    manual_override，若据此跳过，首次自动动作之后闭环就会自锁。
    """

    def __init__(self, settings: Settings, llm: LLMService, mqtt_service: MqttService | None = None) -> None:
        self.settings = settings
        self.llm = llm
        self.mqtt_service = mqtt_service
        self._enabled: dict[str, bool] = {}
        self._last_run: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def is_enabled(self, device_id: str) -> bool:
        return self._enabled.get(device_id, self.settings.autopilot_enabled)

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        self._enabled[device_id] = enabled

    def describe(self, device_id: str) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "enabled": self.is_enabled(device_id),
            "cooldown_seconds": self.settings.autopilot_cooldown_seconds,
            "min_confidence": self.settings.autopilot_min_confidence,
            "trigger_levels": self.settings.autopilot_trigger_levels,
        }

    def evaluate_trigger(self, telemetry_payload: dict[str, Any]) -> str | None:
        fusion = telemetry_payload.get("fusion") or {}
        air_quality = fusion.get("air_quality")
        if air_quality in self.settings.autopilot_trigger_levels:
            return f"air_quality={air_quality}"
        if fusion.get("alarm_enabled"):
            return "alarm_enabled"
        return None

    def should_run(self, device_id: str, telemetry_payload: dict[str, Any]) -> str | None:
        """检查开关、触发规则与冷却期；全部通过则记账并返回触发原因。"""
        if not self.is_enabled(device_id):
            return None
        trigger = self.evaluate_trigger(telemetry_payload)
        if trigger is None:
            return None
        now = time.monotonic()
        last = self._last_run.get(device_id)
        if last is not None and now - last < self.settings.autopilot_cooldown_seconds:
            return None
        self._last_run[device_id] = now
        return trigger

    def maybe_trigger(
        self, device_id: str, telemetry_payload: dict[str, Any], loop: asyncio.AbstractEventLoop
    ) -> None:
        """在 MQTT 回调线程中调用：命中触发条件时把分析任务调度到事件循环。"""
        trigger = self.should_run(device_id, telemetry_payload)
        if trigger is None:
            return
        asyncio.run_coroutine_threadsafe(self.run_once(device_id, trigger), loop)

    async def run_once(self, device_id: str, trigger: str) -> None:
        lock = self._locks.setdefault(device_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            db = SessionLocal()
            try:
                db.add(
                    models.DeviceEvent(
                        device_id=device_id,
                        type="autopilot",
                        severity="info",
                        message=f"自动决策触发：{trigger}",
                        raw_payload={"trigger": trigger},
                    )
                )
                db.commit()
                await manager.broadcast(
                    device_id,
                    WebSocketEnvelope(
                        type="event",
                        device_id=device_id,
                        payload={"type": "autopilot", "severity": "info", "message": f"自动决策触发：{trigger}"},
                    ).model_dump(mode="json"),
                )
                await run_ai_analysis(db, device_id, self.llm, self.mqtt_service, trigger=f"auto:{trigger}")
            except Exception:
                LOGGER.exception("autopilot analysis failed for %s", device_id)
            finally:
                db.close()
