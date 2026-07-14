# IoTCmpt Contracts

This directory is the versioned source of truth shared by firmware, server,
simulator, and web code generation.

- `commands.json` defines the command catalog, parameter schemas, safety class,
  allowed sources, default TTL, minimum AI interval, and AI/MCP exposure.
- `mqtt-envelope.schema.json` defines the common MQTT v2 envelope.
- `device-capabilities.schema.json` defines the retained capability document.
- `websocket-events.json` lists the WebSocket v2 domain event names.
- `firmware-behavior.json` defines shared fusion thresholds, queue/cache sizes,
  smoke-silence bounds, and executor timing for firmware and simulator.

Generated artifacts include the server Python catalog, firmware C headers, and
simulator behavior constants. Do not patch generated output to hide drift.

Regenerate committed artifacts from the repository root:

```powershell
server\.venv\Scripts\python.exe tools\generate-contracts.py
```

CI uses `--check` and fails when generated artifacts drift.

Changing a command is a cross-component change: implement its firmware handler,
capability dependency, application validation, MCP scope, frontend display, and
regression tests together. A catalog entry does not automatically make a
command safe for AI.
