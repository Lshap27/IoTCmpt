"""Export the OpenAPI schema (plus WebSocket envelope types) to server/openapi.json.

The WebSocket envelope discriminated union is not part of any HTTP route, so it is
injected into components.schemas here to make openapi.json the single source of
truth for frontend codegen (pnpm codegen in web/).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AIOT_MQTT_ENABLED", "false")
os.environ.setdefault("AIOT_AUTO_CREATE_TABLES", "false")
os.environ.setdefault("AIOT_DATABASE_URL", "sqlite://")

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from pydantic import TypeAdapter  # noqa: E402

from app.main import create_app  # noqa: E402
from app.schemas import WsMessage  # noqa: E402


def main() -> None:
    schema = create_app().openapi()
    ws_schema = TypeAdapter(WsMessage).json_schema(ref_template="#/components/schemas/{model}")
    defs = ws_schema.pop("$defs", {})
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.update(defs)
    components["WsMessage"] = ws_schema

    out = SERVER_ROOT / "openapi.json"
    out.write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
