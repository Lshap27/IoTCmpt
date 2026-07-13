from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.db import models
from app.db.session import SessionLocal
from app.schemas import WebSocketEnvelope
from app.services.analysis import run_ai_analysis
from app.services.llm import LLMService, VisionUnsupportedError
from app.services.mqtt import MqttGateway
from app.services.websocket import manager

LOGGER = logging.getLogger(__name__)


class AutoPilot:
    """遥测驱动的自动决策闭环：触发规则 + 冷却期 + 每设备开关。

    注意：不以 manual_override 作为跳过条件——云端开/关窗命令会让固件进入
    manual_override，若据此跳过，首次自动动作之后闭环就会自锁。
    """

    def __init__(self, settings: Settings, llm: LLMService, mqtt_service: MqttGateway | None = None) -> None:
        self.settings = settings
        self.llm = llm
        self.mqtt_service = mqtt_service
        self._enabled: dict[str, bool] = {}
        self._last_run: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._vision_interval_enabled: dict[str, bool] = {}
        self._vision_interval_seconds: dict[str, float] = {}
        self._sedentary_threshold_seconds: dict[str, float] = {}
        self._smoke_silence_seconds: dict[str, int] = {}
        self._vision_capability = "unknown"
        self._last_vision_run: dict[str, float] = {}
        self._last_air_quality: dict[str, str] = {}
        self._lighting_state: dict[str, tuple[bool, bool | None]] = {}
        self._sedentary_started: dict[str, float] = {}
        self._sedentary_announced: set[str] = set()
        self._nonseated_frames: dict[str, int] = {}
        self._last_present_at: dict[str, float] = {}

    def is_enabled(self, device_id: str) -> bool:
        return self._enabled.get(device_id, self.settings.autopilot_enabled)

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        self._enabled[device_id] = enabled

    def update(self, device_id: str, **values: Any) -> None:
        if values.get("enabled") is not None:
            self._enabled[device_id] = bool(values["enabled"])
        if values.get("vision_interval_enabled") is not None:
            self._vision_interval_enabled[device_id] = bool(values["vision_interval_enabled"])
        if values.get("vision_interval_seconds") is not None:
            self._vision_interval_seconds[device_id] = float(values["vision_interval_seconds"])
        if values.get("sedentary_threshold_seconds") is not None:
            self._sedentary_threshold_seconds[device_id] = float(values["sedentary_threshold_seconds"])
        if values.get("smoke_silence_seconds") is not None:
            self._smoke_silence_seconds[device_id] = int(values["smoke_silence_seconds"])

    def set_vision_capability(self, capability: str) -> None:
        self._vision_capability = capability

    def describe(self, device_id: str) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "enabled": self.is_enabled(device_id),
            "cooldown_seconds": self.settings.autopilot_cooldown_seconds,
            "min_confidence": self.settings.autopilot_min_confidence,
            "trigger_levels": self.settings.autopilot_trigger_levels,
            "vision_capability": self._vision_capability,
            "vision_interval_enabled": self._vision_interval_enabled.get(
                device_id, self.settings.vision_interval_enabled
            ),
            "vision_interval_effective": self._vision_capability != "unsupported"
            and self._vision_interval_enabled.get(device_id, self.settings.vision_interval_enabled),
            "vision_interval_seconds": self._vision_interval_seconds.get(
                device_id, self.settings.vision_interval_seconds
            ),
            "sedentary_threshold_seconds": self._sedentary_threshold_seconds.get(
                device_id, self.settings.sedentary_threshold_seconds
            ),
            "smoke_silence_seconds": self._smoke_silence_seconds.get(device_id, self.settings.smoke_silence_seconds),
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
        """检查开关、触发规则与冷却期；通过则返回触发原因（冷却期由 run_once 实际开跑时记账）。"""
        if not self.is_enabled(device_id):
            return None
        trigger = self.evaluate_trigger(telemetry_payload)
        if trigger is None:
            return None
        now = time.monotonic()
        last = self._last_run.get(device_id)
        if last is not None and now - last < self.settings.autopilot_cooldown_seconds:
            return None
        return trigger

    def maybe_trigger(self, device_id: str, telemetry_payload: dict[str, Any]) -> None:
        """在事件循环内调用：命中触发条件时调度后台分析任务。"""
        fusion = telemetry_payload.get("fusion") or {}
        current = str(fusion.get("air_quality") or "unknown")
        previous = self._last_air_quality.get(device_id)
        self._last_air_quality[device_id] = current
        trigger = self.should_run(device_id, telemetry_payload)
        if trigger is None:
            return
        intent = "air_change" if previous == "good" and current in {"watch", "alert"} else "general"
        task = asyncio.create_task(self.run_once(device_id, trigger, analysis_intent=intent))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def maybe_trigger_vision(self, device_id: str, image_path: Path) -> None:
        state = self.describe(device_id)
        if not state["vision_interval_effective"]:
            return
        now = time.monotonic()
        if now - self._last_vision_run.get(device_id, 0.0) < state["vision_interval_seconds"]:
            return
        self._last_vision_run[device_id] = now
        task = asyncio.create_task(
            self.run_once(device_id, "vision_interval", image_path=image_path, analysis_intent="vision_interval")
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def trigger_smoke(self, device_id: str) -> None:
        task = asyncio.create_task(self.run_once(device_id, "smoke", analysis_intent="smoke"))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def on_pose_result(self, device_id: str, payload: dict[str, Any]) -> None:
        db = SessionLocal()
        try:
            latest = (
                db.query(models.Telemetry)
                .filter(models.Telemetry.device_id == device_id)
                .order_by(models.Telemetry.sampled_at.desc())
                .first()
            )
            light = latest.light_is_dark if latest else None
        finally:
            db.close()
        present = bool(payload.get("human_present"))
        lighting = (present, light)
        if self.is_enabled(device_id) and self._lighting_state.get(device_id) != lighting:
            self._lighting_state[device_id] = lighting
            task = asyncio.create_task(self.run_once(device_id, "lighting", analysis_intent="lighting"))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        seated = present and str(payload.get("label") or "").startswith("坐姿")
        now = time.monotonic()
        if present:
            self._last_present_at[device_id] = now
        if seated:
            self._nonseated_frames[device_id] = 0
            self._sedentary_started.setdefault(device_id, now)
            threshold = self.describe(device_id)["sedentary_threshold_seconds"]
            if (
                self.is_enabled(device_id)
                and device_id not in self._sedentary_announced
                and now - self._sedentary_started[device_id] >= threshold
            ):
                self._sedentary_announced.add(device_id)
                task = asyncio.create_task(self.run_once(device_id, "sedentary", analysis_intent="sedentary"))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        elif present:
            self._nonseated_frames[device_id] = self._nonseated_frames.get(device_id, 0) + 1
            if self._nonseated_frames[device_id] < 2:
                return
            self._sedentary_started.pop(device_id, None)
            self._sedentary_announced.discard(device_id)
        elif now - self._last_present_at.get(device_id, now) >= 30:
            self._nonseated_frames[device_id] = 0
            self._sedentary_started.pop(device_id, None)
            self._sedentary_announced.discard(device_id)

    async def run_once(
        self,
        device_id: str,
        trigger: str,
        *,
        image_path: Path | None = None,
        analysis_intent: str = "general",
    ) -> None:
        lock = self._locks.setdefault(device_id, asyncio.Lock())
        if lock.locked():
            # 上一轮分析还在进行：直接丢弃本次触发，且不消耗冷却期
            return
        async with lock:
            # 真正开跑才记账冷却期，被锁丢弃的触发不应重置计时
            self._last_run[device_id] = time.monotonic()
            db = SessionLocal()
            try:

                def _record_trigger() -> None:
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

                # 同步 DB 提交移出事件循环，避免 Postgres 卡顿时冻结整个网关
                await asyncio.to_thread(_record_trigger)
                await manager.broadcast(
                    device_id,
                    WebSocketEnvelope(
                        type="event",
                        device_id=device_id,
                        payload={"type": "autopilot", "severity": "info", "message": f"自动决策触发：{trigger}"},
                    ).model_dump(mode="json"),
                )
                await run_ai_analysis(
                    db,
                    device_id,
                    self.llm,
                    self.mqtt_service,
                    trigger=f"auto:{trigger}",
                    image_path=image_path,
                    analysis_intent=analysis_intent,
                )
                if image_path is not None:
                    self.set_vision_capability("supported")
            except VisionUnsupportedError:
                self.set_vision_capability("unsupported")
                LOGGER.warning("vision analysis unsupported by current model %s", self.settings.llm_model)
            except Exception:
                LOGGER.exception("autopilot analysis failed for %s", device_id)
            finally:
                db.close()
