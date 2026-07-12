from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiomqtt

from app.core.config import Settings

LOGGER = logging.getLogger(__name__)

MessageHandler = Callable[[str, dict[str, Any]], Awaitable[None]]

SUBSCRIPTIONS: tuple[tuple[str, int], ...] = (
    ("devices/+/status", 1),
    ("devices/+/telemetry", 0),
    ("devices/+/event", 1),
    ("devices/+/command_ack", 1),
    ("devices/+/log", 0),
)


def _decode_payload(raw: bytes | bytearray | str | Any) -> dict[str, Any]:
    text = bytes(raw).decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            payload = {"value": payload}
    except Exception:
        payload = {"raw": text}
    return payload


class MqttGateway:
    """asyncio 原生的 MQTT 接入：单事件循环内订阅、发布与自动重连。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self, handler: MessageHandler) -> None:
        if not self.settings.mqtt_enabled:
            LOGGER.info("MQTT disabled")
            return
        self._task = asyncio.create_task(self.run(handler), name="mqtt-gateway")

    async def run(self, handler: MessageHandler) -> None:
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self.settings.mqtt_host,
                    port=self.settings.mqtt_port,
                    identifier=self.settings.mqtt_client_id,
                    username=self.settings.mqtt_username or None,
                    password=self.settings.mqtt_password or None,
                ) as client:
                    self._client = client
                    LOGGER.info("MQTT connected to %s:%s", self.settings.mqtt_host, self.settings.mqtt_port)
                    for topic, qos in SUBSCRIPTIONS:
                        await client.subscribe(topic, qos=qos)
                    async for message in client.messages:
                        payload = _decode_payload(message.payload)
                        try:
                            await handler(str(message.topic), payload)
                        except Exception:
                            LOGGER.exception("MQTT message handler failed for %s", message.topic)
            except aiomqtt.MqttError as exc:
                LOGGER.warning(
                    "MQTT connection lost (%s); reconnecting in %.1fs", exc, self.settings.mqtt_reconnect_seconds
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # 本循环是 MQTT 接入的唯一守护者：任何意外异常若逃逸，任务会静默死亡，
                # 网关看似健康但再也收不到遥测。兜底记录并照常重连。
                LOGGER.exception(
                    "MQTT loop crashed unexpectedly; reconnecting in %.1fs", self.settings.mqtt_reconnect_seconds
                )
            finally:
                self._client = None
            await asyncio.sleep(self.settings.mqtt_reconnect_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._client = None

    async def publish_json(self, topic: str, payload: dict[str, Any], qos: int = 1, retain: bool = False) -> bool:
        """发布成功返回 True；未连接或发布失败返回 False，调用方据此决定是否推进指令状态。"""
        client = self._client
        if client is None:
            LOGGER.info("MQTT publish skipped because client is not connected: %s", topic)
            return False
        try:
            await client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=qos, retain=retain)
        except aiomqtt.MqttError:
            LOGGER.warning("MQTT publish failed: %s", topic)
            return False
        return True
