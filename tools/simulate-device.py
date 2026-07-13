from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiomqtt
from aiomqtt.client import Will
import httpx

DEFAULT_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwc"
    "KDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAgACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcI"
    "CQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRol"
    "JicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAA"
    "AAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLR"
    "ChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaX"
    "mJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEA"
    "PwB1FFFfUHz4UUUUAFFFFABRRRQB/9k="
)


class SimulatedDevice:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.state = {
            "window_open": False,
            "alarm_on": args.scenario == "smoke",
            "manual_override": False,
            "manual_window_override": False,
            "manual_led_override": False,
            "control_priority": "manual_first",
            "smoke_silenced": False,
            "led_on": False,
        }
        self.manual_alarm_on = False
        self.smoke_silenced_until = 0.0
        self.sequence = 0

    def telemetry(self) -> dict[str, Any]:
        self.sequence += 1
        scenario = self.args.scenario
        slow = math.sin(self.sequence * 0.43)
        fast = math.sin(self.sequence * 0.91 + 0.7)
        smoke_active = scenario == "smoke"
        self.state["smoke_silenced"] = (
            smoke_active and time.monotonic() < self.smoke_silenced_until
        )
        self.state["alarm_on"] = self.manual_alarm_on or (
            smoke_active and not self.state["smoke_silenced"]
        )
        self.state["manual_override"] = bool(
            self.state["manual_window_override"] or self.state["manual_led_override"]
        )
        if scenario == "air-alert":
            sensors = {
                "temperature_c": round(31.5 + slow * 0.7, 1),
                "humidity_percent": round(77.0 + fast * 2.0, 1),
                "tvoc_ppb": round(720 + slow * 48),
                "hcho_ug_m3": round(110 + fast * 9),
                "eco2_ppm": round(1650 + slow * 95),
                "light_is_dark": True,
                "smoke_detected": False,
            }
            fusion = {
                "air_quality": "alert",
                "recommend_open_window": True,
                "alarm_enabled": False,
                "reason": "模拟空气污染告警",
            }
        elif scenario == "smoke":
            sensors = {
                "temperature_c": round(25.0 + slow * 0.4, 1),
                "humidity_percent": round(55.0 + fast * 1.5, 1),
                "tvoc_ppb": round(180 + slow * 18),
                "hcho_ug_m3": round(25 + fast * 3),
                "eco2_ppm": round(520 + slow * 32),
                "light_is_dark": False,
                "smoke_detected": True,
            }
            fusion = {
                "air_quality": "alert",
                "recommend_open_window": False,
                "alarm_enabled": True,
                "reason": "MQ-2 检测到烟雾",
            }
        else:
            sensors = {
                "temperature_c": round(24.8 + slow * 0.6, 1),
                "humidity_percent": round(52.0 + fast * 2.2, 1),
                "tvoc_ppb": round(140 + slow * 16),
                "hcho_ug_m3": round(20 + fast * 3),
                "eco2_ppm": round(480 + slow * 38),
                "light_is_dark": False,
                "smoke_detected": False,
            }
            fusion = {
                "air_quality": "good",
                "recommend_open_window": False,
                "alarm_enabled": False,
                "reason": "空气质量良好",
            }
        return {
            "device_id": self.args.device_id,
            "sampled_at": datetime.now(UTC).isoformat(),
            "sensors": sensors,
            "state": self.state,
            "fusion": fusion,
        }

    def apply_command(self, payload: dict[str, Any]) -> tuple[str, str]:
        command = str(payload.get("type") or "")
        parameter = payload.get("parameter") or {}
        source = str(payload.get("source") or "frontend")
        status, detail = "executed", f"{command} applied by simulator"
        if command in {"window.open", "window.close"}:
            automatic_blocked = (
                source != "frontend"
                and self.state["control_priority"] == "manual_first"
                and self.state["manual_window_override"]
            )
            if automatic_blocked:
                return "rejected", "manual window override is active"
            self.state["window_open"] = command == "window.open"
            if (
                source == "frontend"
                and self.state["control_priority"] == "manual_first"
            ):
                self.state["manual_window_override"] = True
        elif command in {"led.on", "led.off"}:
            automatic_blocked = (
                source != "frontend"
                and self.state["control_priority"] == "manual_first"
                and self.state["manual_led_override"]
            )
            if automatic_blocked:
                return "rejected", "manual LED override is active"
            self.state["led_on"] = command == "led.on"
            if (
                source == "frontend"
                and self.state["control_priority"] == "manual_first"
            ):
                self.state["manual_led_override"] = True
        elif command == "alarm.on":
            self.manual_alarm_on = True
        elif command == "alarm.off":
            self.manual_alarm_on = False
        elif command == "control.set_priority":
            priority = parameter.get("priority")
            if priority not in {"manual_first", "auto_first"}:
                return "rejected", "priority must be manual_first or auto_first"
            self.state["control_priority"] = priority
            if priority == "auto_first":
                self.state["manual_window_override"] = False
                self.state["manual_led_override"] = False
        elif command == "control.resume_auto":
            self.state["manual_window_override"] = False
            self.state["manual_led_override"] = False
        elif command == "alarm.silence":
            if self.args.scenario != "smoke":
                return "rejected", "no active smoke alarm"
            seconds = max(10, min(600, int(parameter.get("seconds", 60))))
            self.smoke_silenced_until = time.monotonic() + seconds
            self.state["smoke_silenced"] = True
            self.state["alarm_on"] = self.manual_alarm_on
        elif command in {"voice.speak", "display.message", "none"}:
            pass
        else:
            status, detail = "rejected", f"unsupported command: {command}"
        self.state["manual_override"] = bool(
            self.state["manual_window_override"] or self.state["manual_led_override"]
        )
        return status, detail

    async def publish_loop(self, client: aiomqtt.Client) -> None:
        prefix = f"devices/{self.args.device_id}"
        await client.publish(
            f"{prefix}/status", json.dumps({"status": "online"}), qos=1, retain=True
        )
        if self.args.scenario == "smoke":
            await client.publish(
                f"{prefix}/event",
                json.dumps(
                    {
                        "type": "smoke.detected",
                        "severity": "critical",
                        "message": "模拟设备检测到烟雾",
                    },
                    ensure_ascii=False,
                ),
                qos=1,
            )
        while True:
            await client.publish(
                f"{prefix}/telemetry",
                json.dumps(self.telemetry(), ensure_ascii=False),
                qos=0,
            )
            await asyncio.sleep(self.args.interval)

    async def command_loop(self, client: aiomqtt.Client) -> None:
        topic = f"devices/{self.args.device_id}/command"
        await client.subscribe(topic, qos=1)
        async for message in client.messages:
            payload = json.loads(bytes(message.payload))
            status, detail = self.apply_command(payload)
            if self.args.ack_delay:
                await asyncio.sleep(self.args.ack_delay)
            ack = {
                "device_id": self.args.device_id,
                "command_id": payload.get("command_id", ""),
                "status": status,
                "message": detail,
                "executed_at": datetime.now(UTC).isoformat(),
            }
            await client.publish(
                f"devices/{self.args.device_id}/command_ack", json.dumps(ack), qos=1
            )

    async def upload_image(self) -> None:
        content = (
            Path(self.args.image).read_bytes() if self.args.image else DEFAULT_JPEG
        )
        url = (
            f"{self.args.api_base.rstrip('/')}/api/devices/{self.args.device_id}/images"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            for attempt in range(1, 11):
                try:
                    response = await client.post(
                        url, files={"file": ("simulator.jpg", content, "image/jpeg")}
                    )
                    response.raise_for_status()
                    print(f"image uploaded: {response.json()['url']}")
                    return
                except httpx.HTTPError as exc:
                    if attempt == 10:
                        # 图片只是增强数据；API 暂时不可用不应让 MQTT 设备退出。
                        print(f"image upload skipped after retries: {exc}")
                        return
                    await asyncio.sleep(1)

    async def run(self) -> None:
        if not self.args.no_image:
            await self.upload_image()
        async with aiomqtt.Client(
            self.args.host,
            port=self.args.port,
            identifier=f"sim-{self.args.device_id}",
            will=Will(
                f"devices/{self.args.device_id}/status",
                json.dumps({"status": "offline"}, ensure_ascii=False),
                qos=1,
                retain=True,
            ),
        ) as client:
            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(self.publish_loop(client))
                    group.create_task(self.command_loop(client))
            finally:
                await client.publish(
                    f"devices/{self.args.device_id}/status",
                    json.dumps({"status": "offline"}),
                    qos=1,
                    retain=True,
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic MQTT/HTTP ESP32-S3 simulator"
    )
    parser.add_argument(
        "--scenario", choices=["normal", "air-alert", "smoke"], default="normal"
    )
    parser.add_argument("--device-id", default="esp32s3-001")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument(
        "--ack-delay",
        type=float,
        default=0.0,
        help="seconds to delay command_ack; useful for browser tests",
    )
    parser.add_argument(
        "--image", help="optional JPEG path; defaults to a bundled test JPEG"
    )
    parser.add_argument("--no-image", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(SimulatedDevice(parse_args()).run())
    except KeyboardInterrupt:
        pass
