from __future__ import annotations

import argparse
import json
from pathlib import Path
from pprint import pformat

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "contracts" / "commands.json"
BEHAVIOR_PATH = ROOT / "contracts" / "firmware-behavior.json"
PYTHON_OUTPUT = ROOT / "server" / "app" / "generated" / "command_catalog.py"
C_OUTPUT = ROOT / "firmware" / "esp32s3" / "main" / "include" / "command_catalog.generated.h"
BEHAVIOR_PYTHON_OUTPUT = ROOT / "tools" / "firmware_simulator" / "generated_behavior.py"
BEHAVIOR_C_OUTPUT = ROOT / "firmware" / "esp32s3" / "main" / "include" / "firmware_behavior.generated.h"


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def load_behavior() -> dict:
    return json.loads(BEHAVIOR_PATH.read_text(encoding="utf-8"))


def render_python(catalog: dict) -> str:
    defaults = catalog.get("defaults", {})
    commands = [{**defaults, **item} for item in catalog["commands"]]
    names = [item["name"] for item in commands]
    ai_names = [item["name"] for item in commands if item["ai_allowed"]]
    by_name = {item["name"]: item for item in commands}
    return (
        '"""Generated from contracts/commands.json. Do not edit by hand."""\n\n'
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        f"SCHEMA_VERSION = {catalog['schema_version']!r}\n"
        f"COMMAND_DEFAULTS: dict[str, Any] = {pformat(defaults, width=100, sort_dicts=False)}\n"
        f"COMMAND_NAMES: tuple[str, ...] = {pformat(tuple(names), width=100)}\n"
        f"AI_COMMAND_NAMES: frozenset[str] = frozenset({pformat(ai_names, width=100)})\n"
        f"COMMAND_CATALOG: dict[str, dict[str, Any]] = {pformat(by_name, width=100, sort_dicts=False)}\n"
    )


def render_c(catalog: dict) -> str:
    commands = catalog["commands"]
    source_bits = {"frontend": 1, "ai": 2, "external_mcp": 4, "rule": 8}
    rows_list = []
    for item in commands:
        schema = json.dumps(item["parameter_schema"], ensure_ascii=True, separators=(",", ":"))
        c_schema = schema.replace("\\", "\\\\").replace('"', '\\"')
        source_mask = sum(source_bits[source] for source in item["allowed_sources"])
        rows_list.append(
            f'    X({item["c_enum"]}, "{item["name"]}", {str(item["ai_allowed"]).lower()}, '
            f'"{item["safety_class"]}", "{c_schema}", {source_mask}U)'
        )
    rows = " \\\n".join(rows_list)
    return (
        "/* Generated from contracts/commands.json. Do not edit by hand. */\n"
        "#pragma once\n\n"
        f'#define AIOT_PROTOCOL_VERSION "{catalog["schema_version"]}"\n\n'
        "#define AIOT_COMMAND_CATALOG(X) \\\n"
        f"{rows}\n"
    )


def render_behavior_python(behavior: dict) -> str:
    return (
        '"""Generated from contracts/firmware-behavior.json. Do not edit by hand."""\n\n'
        "from __future__ import annotations\n\n"
        f"SCHEMA_VERSION = {behavior['schema_version']!r}\n"
        f"FUSION_THRESHOLDS = {pformat(behavior['fusion'], width=100, sort_dicts=False)}\n"
        f"COMMAND_QUEUE_LENGTH = {behavior['command_queue_length']}\n"
        f"TERMINAL_ACK_CACHE_SIZE = {behavior['terminal_ack_cache_size']}\n"
        f"SMOKE_SILENCE_MIN_SECONDS = {behavior['smoke_silence_seconds']['minimum']}\n"
        f"SMOKE_SILENCE_MAX_SECONDS = {behavior['smoke_silence_seconds']['maximum']}\n"
        f"COMMAND_EXECUTION_PERIOD_MS = {behavior['command_execution_period_ms']}\n"
    )


def render_behavior_c(behavior: dict) -> str:
    fusion = behavior["fusion"]
    return (
        "/* Generated from contracts/firmware-behavior.json. Do not edit by hand. */\n"
        "#pragma once\n\n"
        f'#define AIOT_FIRMWARE_BEHAVIOR_VERSION "{behavior["schema_version"]}"\n'
        f"#define AIOT_FUSION_TEMPERATURE_WATCH_C {fusion['temperature_c']['watch_above']:.1f}f\n"
        f"#define AIOT_FUSION_TEMPERATURE_ALERT_C {fusion['temperature_c']['alert_above']:.1f}f\n"
        f"#define AIOT_FUSION_HUMIDITY_LOW_PERCENT {fusion['humidity_percent']['watch_below']:.1f}f\n"
        f"#define AIOT_FUSION_HUMIDITY_HIGH_PERCENT {fusion['humidity_percent']['watch_above']:.1f}f\n"
        f"#define AIOT_FUSION_TVOC_WATCH_PPB {fusion['tvoc_ppb']['watch_above']}U\n"
        f"#define AIOT_FUSION_TVOC_ALERT_PPB {fusion['tvoc_ppb']['alert_above']}U\n"
        f"#define AIOT_FUSION_HCHO_WATCH_UG_M3 {fusion['hcho_ug_m3']['watch_above']}U\n"
        f"#define AIOT_FUSION_HCHO_ALERT_UG_M3 {fusion['hcho_ug_m3']['alert_above']}U\n"
        f"#define AIOT_FUSION_ECO2_WATCH_PPM {fusion['eco2_ppm']['watch_above']}U\n"
        f"#define AIOT_FUSION_ECO2_ALERT_PPM {fusion['eco2_ppm']['alert_above']}U\n"
        f"#define AIOT_COMMAND_QUEUE_LENGTH {behavior['command_queue_length']}U\n"
        f"#define AIOT_TERMINAL_ACK_CACHE_SIZE {behavior['terminal_ack_cache_size']}U\n"
        f"#define AIOT_SMOKE_SILENCE_MIN_SECONDS {behavior['smoke_silence_seconds']['minimum']}U\n"
        f"#define AIOT_SMOKE_SILENCE_MAX_SECONDS {behavior['smoke_silence_seconds']['maximum']}U\n"
        f"#define AIOT_COMMAND_EXECUTION_PERIOD_MS {behavior['command_execution_period_ms']}U\n"
    )


def sync_file(path: Path, content: str, *, check: bool) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == content:
        return True
    if check:
        print(f"out of date: {path.relative_to(ROOT)}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"generated: {path.relative_to(ROOT)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = load_catalog()
    behavior = load_behavior()
    ok = all(
        [
            sync_file(PYTHON_OUTPUT, render_python(catalog), check=args.check),
            sync_file(C_OUTPUT, render_c(catalog), check=args.check),
            sync_file(
                BEHAVIOR_PYTHON_OUTPUT,
                render_behavior_python(behavior),
                check=args.check,
            ),
            sync_file(BEHAVIOR_C_OUTPUT, render_behavior_c(behavior), check=args.check),
        ]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
