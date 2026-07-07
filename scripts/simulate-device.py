from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from random import uniform

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:
    raise SystemExit("paho-mqtt is required. Install server/requirements.txt first.") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def telemetry(device_id: str, sequence: int, scenario: str, device_state: dict) -> dict:
    # cycle 场景：每 10 个样本中前 6 个正常、后 4 个告警，便于演示自动闭环的触发与恢复。
    alert_mode = scenario == "alert" or (scenario == "cycle" and sequence % 10 >= 6)

    if alert_mode:
        temperature = round(27.5 + uniform(-0.5, 1.5), 1)
        humidity = round(58.0 + uniform(-5.0, 5.0), 1)
        tvoc = int(760 + uniform(0, 240))
        eco2 = int(1250 + uniform(0, 350))
        hcho = int(95 + uniform(0, 40))
        air_quality = "alert"
        reason = "模拟：污染物浓度过高"
    else:
        temperature = round(24.0 + uniform(-1.5, 2.5), 1)
        humidity = round(62.0 + uniform(-8.0, 8.0), 1)
        tvoc = int(120 + uniform(-40, 80))
        eco2 = int(450 + uniform(-70, 110))
        hcho = int(30 + uniform(-10, 15))
        watch = tvoc > 170 or eco2 > 520
        air_quality = "watch" if watch else "good"
        reason = "模拟：轻度波动" if watch else "模拟：环境正常"

    return {
        "device_id": device_id,
        "sampled_at": now_iso(),
        "sensors": {
            "temperature_c": temperature,
            "humidity_percent": humidity,
            "tvoc_ppb": tvoc,
            "hcho_ug_m3": hcho,
            "eco2_ppm": eco2,
            "light_is_dark": sequence % 6 == 0,
        },
        "state": {
            "window_open": device_state["window_open"],
            "alarm_on": device_state["alarm_on"],
            "manual_override": device_state["manual_override"],
        },
        "fusion": {
            "air_quality": air_quality,
            "recommend_open_window": alert_mode and not device_state["window_open"],
            "alarm_enabled": alert_mode,
            "reason": reason,
        },
    }


def upload_image(api_base: str, device_id: str, image_path: Path) -> None:
    import httpx

    url = f"{api_base.rstrip('/')}/api/devices/{device_id}/images"
    with image_path.open("rb") as handle:
        files = {"file": (image_path.name, handle, "image/jpeg")}
        response = httpx.post(url, files=files, timeout=10.0)
    response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish simulated ESP32-S3 MQTT telemetry.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--device-id", default="esp32s3-001")
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--count", type=int, default=0, help="0 means run until interrupted")
    parser.add_argument(
        "--scenario",
        choices=["normal", "alert", "cycle"],
        default="normal",
        help="normal=平稳数据; alert=持续告警(触发自动决策闭环); cycle=正常/告警交替",
    )
    parser.add_argument("--upload-image", type=Path, default=None, help="周期性上传的 JPEG 路径（测试视觉分析链路）")
    parser.add_argument("--image-interval", type=float, default=10.0, help="图片上传间隔秒数")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="HTTP 网关地址（图片上传用）")
    args = parser.parse_args()

    if args.upload_image is not None and not args.upload_image.is_file():
        raise SystemExit(f"image not found: {args.upload_image}")

    running = True

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # 命令会改变模拟设备状态，让闭环在遥测里可见（开窗后 window_open=true 等）。
    device_state = {"window_open": False, "alarm_on": False, "manual_override": False}

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{args.device_id}")

    def on_message(client, userdata, message):
        payload = message.payload.decode("utf-8", errors="replace")
        print(f"[command] {message.topic}: {payload}")
        try:
            command = json.loads(payload)
            command_id = command.get("command_id", "")
            command_type = command.get("type", "")
        except json.JSONDecodeError:
            command_id = ""
            command_type = ""

        if command_type == "window.open":
            device_state["window_open"] = True
            device_state["manual_override"] = True
        elif command_type == "window.close":
            device_state["window_open"] = False
            device_state["manual_override"] = True
        elif command_type == "alarm.on":
            device_state["alarm_on"] = True
        elif command_type == "alarm.off":
            device_state["alarm_on"] = False

        ack = {
            "device_id": args.device_id,
            "command_id": command_id,
            "status": "executed" if command_id else "rejected",
            "message": "simulated command acknowledgement",
            "executed_at": now_iso(),
        }
        client.publish(f"devices/{args.device_id}/command_ack", json.dumps(ack), qos=1)

    client.on_message = on_message
    client.will_set(f"devices/{args.device_id}/status", json.dumps({"status": "offline"}), qos=1, retain=True)
    client.connect(args.host, args.port)
    client.subscribe(f"devices/{args.device_id}/command", qos=1)
    client.loop_start()
    client.publish(f"devices/{args.device_id}/status", json.dumps({"status": "online"}), qos=1, retain=True)

    sequence = 0
    last_upload = 0.0
    try:
        while running and (args.count == 0 or sequence < args.count):
            payload = telemetry(args.device_id, sequence, args.scenario, device_state)
            client.publish(f"devices/{args.device_id}/telemetry", json.dumps(payload), qos=0)
            print(f"[telemetry] {payload['sampled_at']} {payload['fusion']['air_quality']}")

            if args.upload_image is not None and time.monotonic() - last_upload >= args.image_interval:
                try:
                    upload_image(args.api_base, args.device_id, args.upload_image)
                    print(f"[image] uploaded {args.upload_image.name}")
                    last_upload = time.monotonic()
                except Exception as exc:
                    print(f"[image] upload failed: {exc}")
                    last_upload = time.monotonic()

            sequence += 1
            time.sleep(args.interval)
    finally:
        client.publish(f"devices/{args.device_id}/status", json.dumps({"status": "offline"}), qos=1, retain=True)
        client.loop_stop()
        client.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
