from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class SimulatorStateStore:
    """Atomic, per-device storage for simulated NVS and panel status."""

    def __init__(self, root: Path, device_id: str):
        self.directory = root / device_id
        self.nvs_path = self.directory / "nvs.json"
        self.status_path = self.directory / "status.json"
        self.stop_path = self.directory / "stop.request"

    def load_nvs(self) -> dict[str, Any]:
        try:
            data = json.loads(self.nvs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_nvs(self, data: dict[str, Any]) -> None:
        self._write_json(self.nvs_path, data)

    def write_status(self, data: dict[str, Any]) -> None:
        self._write_json(self.status_path, data)

    def clear_nvs(self) -> None:
        try:
            self.nvs_path.unlink()
        except FileNotFoundError:
            pass

    def clear_stop_request(self) -> None:
        try:
            self.stop_path.unlink()
        except FileNotFoundError:
            pass

    def request_stop(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stop_path.write_text("stop\n", encoding="utf-8")

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
