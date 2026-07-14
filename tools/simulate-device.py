from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from firmware_simulator import FirmwareSimulator
from firmware_simulator.model import SCENARIOS, FirmwareModel


class SimulatedDevice:
    """Small compatibility facade for scripts that only use the behavior model."""

    def __init__(self, args: argparse.Namespace):
        self.model = FirmwareModel(args.device_id, args.scenario)
        self.state = self.model.state

    def telemetry(self):
        return self.model.telemetry()

    def apply_command(self, payload):
        normalized = {"source": "frontend", "parameter": {}, **payload}
        parameter = dict(normalized.get("parameter") or {})
        if normalized.get("type") == "alarm.silence" and "seconds" in parameter:
            parameter["duration_seconds"] = parameter.pop("seconds")
        normalized["parameter"] = parameter
        status, message, _error = self.model.apply_command(normalized)
        return status, message


def bounded_float(minimum: float, maximum: float):
    def parse(value: str) -> float:
        parsed = float(value)
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum:g} and {maximum:g}")
        return parsed

    return parse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the lightweight ESP32-S3 firmware behavior simulator")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--device-id", default="esp32s3-001")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=bounded_float(1, 60), default=2.0)
    parser.add_argument(
        "--ack-delay",
        type=float,
        default=0.0,
        help="extra seconds before terminal command_ack; useful for browser tests",
    )
    parser.add_argument("--image", help="optional JPEG path; defaults to a bundled test JPEG")
    parser.add_argument("--image-interval", type=bounded_float(10, 3600), default=30.0)
    parser.add_argument("--no-image", action="store_true")
    parser.add_argument("--state-dir", default=".runtime/firmware-simulator")
    parser.add_argument("--reset-state", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(FirmwareSimulator(parse_args()).run())
