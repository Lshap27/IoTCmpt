from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.core.config import Settings

LOGGER = logging.getLogger(__name__)


class MqttService:
    def __init__(self, settings: Settings, message_handler: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.settings = settings
        self.message_handler = message_handler
        self.client = None

    def start(self) -> None:
        if not self.settings.mqtt_enabled:
            LOGGER.info("MQTT disabled")
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            LOGGER.warning("paho-mqtt is not installed; MQTT disabled")
            return

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.settings.mqtt_client_id)
        if self.settings.mqtt_username:
            client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code == 0:
                client.subscribe("devices/+/status", qos=1)
                client.subscribe("devices/+/telemetry", qos=0)
                client.subscribe("devices/+/event", qos=1)
                client.subscribe("devices/+/command_ack", qos=1)
                client.subscribe("devices/+/log", qos=0)
            else:
                LOGGER.warning("MQTT connect failed: %s", reason_code)

        def on_message(client, userdata, message):
            if self.message_handler is None:
                return
            try:
                payload = json.loads(message.payload.decode("utf-8"))
                if not isinstance(payload, dict):
                    payload = {"value": payload}
            except Exception:
                payload = {"raw": message.payload.decode("utf-8", errors="replace")}
            self.message_handler(message.topic, payload)

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port)
        client.loop_start()
        self.client = client

    def stop(self) -> None:
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

    def publish_json(self, topic: str, payload: dict[str, Any], qos: int = 1, retain: bool = False) -> None:
        if self.client is None:
            LOGGER.info("MQTT publish skipped because client is not connected: %s", topic)
            return
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=qos, retain=retain)
