# ADR 0001: Modular monolith and MCP tool boundary

- Status: accepted
- Date: 2026-07-14

## Context

Firmware, HTTP handlers, MQTT callbacks and LLM decisions previously shared command concepts without one versioned contract. Synchronous model calls made device control latency and failure ownership unclear. Adding another model provider or actuator risked duplicating validation in multiple transports.

## Decision

Use a modular monolith with domain/application/ports/adapters boundaries. HTTP, MQTT and MCP are peer adapters. Commands enter one application service, are persisted with an outbox record, and are executed asynchronously by firmware. Cloud AI is a persistent slow-path worker and may invoke only application tools through an in-process MCP client.

MCP is Streamable HTTP at `/mcp`. External clients authenticate with separate read and control bearer tokens. The server-side AI worker uses an internal unexported token. The model sees tool schemas and returns tool calls; it never receives broker credentials or a direct firmware connection.

## Consequences

- Real-time sensing, manual control and firmware safety remain available during LLM or MCP failure.
- A single `trace_id` and durable audit tables explain where a command stopped.
- New transports reuse use cases rather than MQTT publication code.
- The Gateway remains a simple single-process modular monolith; the AI Worker is already split into a separately scalable process while reusing the same application/MCP boundary.
- Contract generation and dependency tests become mandatory CI gates.

Durable work uses PostgreSQL claims plus per-claim lease-token fencing. `SKIP LOCKED` alone is not considered sufficient because a paused process may resume after its lease expires.
