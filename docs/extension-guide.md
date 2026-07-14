# Extension guide

## Add a sensor

1. Add the firmware driver and sample field without placing runtime override state in the sensor sample.
2. Extend the telemetry contract and server schema/model serialization.
3. Add an Alembic column only if the value must be queryable historically; otherwise keep it in structured payload state.
4. Regenerate OpenAPI and the web client, then add reducer/chart coverage.
5. Add the field to patrol fingerprinting only when a meaningful change should incur an LLM call.

## Add an actuator command

1. Add one entry to `contracts/commands.json`, including JSON parameter schema, safety class and `ai_allowed`.
2. Run `python tools/generate-contracts.py`.
3. Implement the generated C enum handler in the firmware command registry and publish it only when the module initialized successfully.
4. Add domain validation that JSON Schema alone cannot express, plus safety-interlock behavior and ACK tests.
5. Let the web read the command from `/capabilities`; do not hard-code availability.
6. If exposed to MCP, call `CommandApplicationService`; never publish MQTT inside the tool.

Adding a command to the catalog does not automatically make it safe for AI. Alarm suppression and control-priority changes remain unavailable to AI even if humans can invoke them.

## Add an MCP tool

1. Define a small resource-oriented tool in `app/adapters/mcp_server.py`.
2. Route it to an application use case or read port.
3. Return `{ok, trace_id, data, error}` and persist side-effect audit before returning success.
4. Assign read/control scope and decide separately whether the AI worker may see it.
5. Test external token scope and the internal AI-host loop.

## Add an LLM provider

Implement the OpenAI-compatible chat/tool-call behavior in the LLM adapter. Keep provider request quirks there; domain and MCP tools must not import the provider SDK. Verify ordinary text analysis, function calls, timeout handling and explicit vision separately. `AIOT_LLM_ENDPOINT=mock` must continue to exercise the same persistent run and MCP command path offline.

## Add another protocol or worker type

Create a new adapter against existing application ports. AI workers already run out of process: reuse the PostgreSQL run lease, heartbeat, realtime event and trace event mechanisms instead of adding a second queue system. Every durable claimant needs a new random `lease_token` per claim, and every renew/side-effect/terminal update must match owner plus token; `SKIP LOCKED` alone is not a fencing guarantee.

## Add a new board profile

1. Start from the safe default, not `configs/full-hardware.defaults`.
2. Document module, flash, PSRAM and USB mode, then enter an explicit pin map.
3. Extend configuration preflight when the board introduces a reserved-pin rule.
4. Build in an isolated directory and record partition margin.
5. Flash with peripherals disabled, then enable and test modules incrementally.
6. Update the physical validation matrix. A simulator or successful compile is never recorded as a board pass.
