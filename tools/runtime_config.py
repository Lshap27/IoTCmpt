from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO / "config" / "runtime-config.json"
ENV_PATHS = {
    "compose": REPO / ".env",
    "gateway": REPO / "server" / ".env",
    "worker": REPO / "server" / ".env",
    "shared": REPO / "server" / ".env",
    "web": REPO / "web" / ".env.local",
}
REMOVED_KEYS = {
    "AIOT_AUTOPILOT_ENABLED",
    "AIOT_AUTOPILOT_COOLDOWN_SECONDS",
    "AIOT_AUTOPILOT_MIN_CONFIDENCE",
    "AIOT_AUTOPILOT_TRIGGER_LEVELS",
    "AIOT_VISION_INTERVAL_ENABLED",
    "AIOT_VISION_INTERVAL_SECONDS",
    "AIOT_SEDENTARY_THRESHOLD_SECONDS",
    "AIOT_SMOKE_SILENCE_SECONDS",
}


def catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def validate_value(key: str, value: Any, field: dict[str, Any]) -> str:
    text = str(value).strip()
    choices = field.get("choices")
    if choices and text not in choices:
        raise ValueError(f"{key} must be one of {', '.join(choices)}")
    if field.get("type") == "boolean":
        lowered = text.lower()
        if lowered not in {"true", "false"}:
            raise ValueError(f"{key} must be true or false")
        return lowered
    if field.get("type") == "number":
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError(f"{key} must be a number") from exc
        minimum = field.get("minimum")
        maximum = field.get("maximum")
        if minimum is not None and number < minimum:
            raise ValueError(f"{key} must be at least {minimum}")
        if maximum is not None and number > maximum:
            raise ValueError(f"{key} must be at most {maximum}")
    return text


def build_values(
    changes: dict[str, Any],
) -> tuple[dict[Path, dict[str, str]], list[dict[str, Any]], list[str]]:
    spec = catalog()["fields"]
    files = {path: parse_env(path) for path in set(ENV_PATHS.values())}
    for values in files.values():
        for key in REMOVED_KEYS:
            values.pop(key, None)
    for key, field in spec.items():
        owner = field["owner"]
        paths = [ENV_PATHS["compose"], ENV_PATHS["shared"]] if owner == "shared" else [ENV_PATHS[owner]]
        # Shared values are resolved once and copied verbatim to both files.
        # In particular, Gateway and Worker must receive the same MCP token.
        current = next((files[path].get(key, "") for path in paths if files[path].get(key)), "")
        value = changes.get(key)
        if value is None:
            value = current or field["default"]
        if value == "generated":
            value = current or secrets.token_urlsafe(32)
        value = validate_value(key, value, field)
        for path in paths:
            files[path][key] = value
    diff: list[dict[str, Any]] = []
    affected: set[str] = set()
    for path, values in files.items():
        previous = parse_env(path)
        for key in sorted(set(previous) | set(values)):
            before = previous.get(key)
            after = values.get(key)
            if before == after:
                continue
            field = spec.get(key, {})
            secret = bool(field.get("secret"))
            diff.append(
                {
                    "file": str(path.relative_to(REPO)),
                    "key": key,
                    "before": "已配置" if secret and before else before,
                    "after": "已配置" if secret and after else after,
                    "secret": secret,
                }
            )
            affected.update(field.get("restart", []))
    return files, diff, sorted(affected)


def apply_config(changes: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    files, diff, affected = build_values(changes)
    if not dry_run:
        for path, values in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            content = "\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n"
            path.write_text(content, encoding="utf-8")
    return {"ok": True, "dryRun": dry_run, "diff": diff, "affectedServices": affected}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="JSON file containing AIOT_* values")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input else json.load(sys.stdin)
    print(json.dumps(apply_config(payload, dry_run=args.dry_run), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
