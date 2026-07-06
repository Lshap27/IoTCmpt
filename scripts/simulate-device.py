from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from random import uniform

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:
    raise SystemExit("paho-mqtt is required. Install server/requirements.txt first.") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def telemetry(device_id: str, sequence: int) -> dict:
    temperature = round(24.0 + uniform(-1.5, 2.5), 1)
    humidity = round(62.0 + uniform(-8.0, 8.0), 1)
    tvoc = int(120 + uniform(-40, 80))
    eco2 = int(450 + uniform(-70, 110))
    alert = tvoc > 170 or eco2 > 520
    return {
        "device_id": device_id,
        "sampled_at": now_iso(),
        "sensors": {
            "temperature_c": temperature,
            "humidity_percent": humidity,
            "tvoc_ppb": tvoc,
            "hcho_ug_m3": int(30 + uniform(-10, 15)),
            "eco2_ppm": eco2,
            "light_is_dark": sequence % 6 == 0,
        },
        "state": {
            "window_open": alert,
            "alarm_on": False,
            "manual_override": False,
        },
        "fusion": {
            "air_quality": "watch" if alert else "good",
            "recommend_open_window": alert,
            "alarm_enabled": alert,
            "reason": "simulated elevated air readings" if alert else "simulated normal readings",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish simulated ESP32-S3 MQTT telemetry.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--device-id", default="esp32s3-001")
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--count", type=int, default=0, help="0 means run until interrupted")
    args = parser.parse_args()

    running = True

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{args.device_id}")

    def on_message(client, userdata, message):
        payload = message.payload.decode("utf-8", errors="replace")
        print(f"[command] {message.topic}: {payload}")
        try:
            command = json.loads(payload)
            command_id = command.get("command_id", "")
        except json.JSONDecodeError:
            command_id = ""
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
    try:
        while running and (args.count == 0 or sequence < args.count):
            payload = telemetry(args.device_id, sequence)
            client.publish(f"devices/{args.device_id}/telemetry", json.dumps(payload), qos=0)
            print(f"[telemetry] {payload['sampled_at']} {payload['fusion']['air_quality']}")
            sequence += 1
            time.sleep(args.interval)
    finally:
        client.publish(f"devices/{args.device_id}/status", json.dumps({"status": "offline"}), qos=1, retain=True)
        client.loop_stop()
        client.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
