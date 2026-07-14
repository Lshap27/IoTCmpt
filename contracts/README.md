# IoTCmpt Contracts

This directory is the versioned source of truth shared by firmware, server,
simulator, and web code generation.

- `commands.json` defines the command catalog, parameter schemas, safety class,
  and whether the AI/MCP control surface may execute a command.
- `mqtt-envelope.schema.json` defines the common MQTT v2 envelope.
- `device-capabilities.schema.json` defines the retained capability document.
- `websocket-events.json` lists the WebSocket v2 domain event names.

Regenerate committed artifacts from the repository root:

```powershell
server\.venv\Scripts\python.exe tools\generate-contracts.py
```

CI uses `--check` and fails when generated artifacts drift.
