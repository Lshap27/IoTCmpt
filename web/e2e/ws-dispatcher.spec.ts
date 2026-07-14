import { QueryClient } from "@tanstack/react-query";
import { expect, test } from "@playwright/test";
import type { WsMessage } from "../src/lib/api";
import { deviceKeys } from "../src/lib/query-keys";
import { addPendingCommand, applyEnvelope, reduceCommandStatus } from "../src/lib/ws-dispatcher";

const deviceId = "device-test";

function commandEvent(status: string): WsMessage {
  return {
    schema_version: "2.0",
    event_id: `evt-${status}`,
    trace_id: "trace-test",
    device_id: deviceId,
    occurred_at: "2026-07-14T00:00:00Z",
    type: "command.status_changed",
    payload: { command_id: "cmd-1", status, message: "" },
  } as WsMessage;
}

test("duplicate terminal ACKs clear pending state idempotently", () => {
  const client = new QueryClient();
  addPendingCommand(client, deviceId, "cmd-1", "window.open");
  applyEnvelope(client, deviceId, commandEvent("executed"));
  applyEnvelope(client, deviceId, commandEvent("executed"));
  expect(client.getQueryData(deviceKeys.pendingCommands(deviceId))).toEqual({});
  expect(client.getQueryData(deviceKeys.commandStatuses(deviceId))).toEqual({ "cmd-1": "executed" });
});

test("an out-of-order accepted event cannot regress a terminal state", () => {
  expect(reduceCommandStatus("executed", "accepted")).toBe("executed");
  const client = new QueryClient();
  applyEnvelope(client, deviceId, commandEvent("executed"));
  applyEnvelope(client, deviceId, commandEvent("accepted"));
  expect(client.getQueryData(deviceKeys.commandStatuses(deviceId))).toEqual({ "cmd-1": "executed" });
});

test("events from a stale device connection are ignored", () => {
  const client = new QueryClient();
  applyEnvelope(client, "another-device", commandEvent("executed"));
  expect(client.getQueryData(deviceKeys.commandStatuses("another-device"))).toBeUndefined();
});
