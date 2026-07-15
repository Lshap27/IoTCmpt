import type { QueryClient } from "@tanstack/react-query";
import type { AiRunOut, LatestState, NotificationOut, TelemetryPoint, WsMessage } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";

export type UiEvent = {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export const HISTORY_CAP = 120;
const EVENT_CAP = 30;
const TELEMETRY_EVENT_CAP = 12;
const TERMINAL_COMMAND_STATUSES = new Set(["executed", "rejected", "failed", "expired", "timed_out"]);
const COMMAND_STATUS_ORDER: Record<string, number> = {
  created: 0,
  queued: 1,
  published: 2,
  accepted: 3,
  executed: 4,
  rejected: 4,
  failed: 4,
  expired: 4,
  timed_out: 4,
};

export function reduceCommandStatus(previous: string | undefined, incoming: string): string {
  if (!previous) return incoming;
  if (TERMINAL_COMMAND_STATUSES.has(previous)) return previous;
  return (COMMAND_STATUS_ORDER[incoming] ?? -1) >= (COMMAND_STATUS_ORDER[previous] ?? -1)
    ? incoming
    : previous;
}

function patchLatest(
  queryClient: QueryClient,
  deviceId: string,
  patch: (current: LatestState) => LatestState,
) {
  queryClient.setQueryData<LatestState>(deviceKeys.latest(deviceId), (current) =>
    current ? patch(current) : current,
  );
}

export function addPendingCommand(
  queryClient: QueryClient,
  deviceId: string,
  commandId: string,
  type: string,
) {
  queryClient.setQueryData<Record<string, string>>(deviceKeys.pendingCommands(deviceId), (current = {}) => ({
    ...current,
    [commandId]: type,
  }));
}

function appendUiEvent(queryClient: QueryClient, deviceId: string, envelope: WsMessage) {
  const uiEvent: UiEvent = {
    id: envelope.event_id,
    type: envelope.type,
    payload: envelope.payload as Record<string, unknown>,
    occurred_at: envelope.occurred_at,
  };
  queryClient.setQueryData<UiEvent[]>(deviceKeys.events(deviceId), (current = []) => {
    let telemetryCount = 0;
    return [uiEvent, ...current]
      .filter((event) => event.type !== "telemetry.received" || ++telemetryCount <= TELEMETRY_EVENT_CAP)
      .slice(0, EVENT_CAP);
  });
}

/** Pure WebSocket v2 envelope reducer. No module-global ACK or connection state. */
export function applyEnvelope(queryClient: QueryClient, deviceId: string, envelope: WsMessage) {
  if (envelope.device_id !== deviceId) return;
  let duplicate = false;
  queryClient.setQueryData<string[]>(deviceKeys.processedEvents(deviceId), (current = []) => {
    if (current.includes(envelope.event_id)) {
      duplicate = true;
      return current;
    }
    return [...current, envelope.event_id].slice(-256);
  });
  if (duplicate) return;
  appendUiEvent(queryClient, deviceId, envelope);

  switch (envelope.type) {
    case "telemetry.received": {
      const point = envelope.payload;
      queryClient.setQueryData<TelemetryPoint[]>(deviceKeys.history(deviceId), (current = []) => {
        const withoutDuplicate = current.filter((item) => item.sampled_at !== point.sampled_at);
        return [...withoutDuplicate, point].slice(-HISTORY_CAP);
      });
      patchLatest(queryClient, deviceId, (current) => ({
        ...current,
        telemetry: point,
        device: { ...current.device, status: "online", last_seen_at: envelope.occurred_at },
      }));
      break;
    }
    case "device.status_changed": {
      patchLatest(queryClient, deviceId, (current) => ({
        ...current,
        device: {
          ...current.device,
          status: envelope.payload.status,
          last_seen_at: envelope.payload.last_seen_at ?? envelope.occurred_at,
        },
      }));
      break;
    }
    case "perception.updated": {
      const payload = envelope.payload as Record<string, unknown>;
      if (envelope.payload.kind === "image") {
        patchLatest(queryClient, deviceId, (current) => ({
          ...current,
          image: payload as unknown as LatestState["image"],
        }));
      } else if (envelope.payload.kind === "pose") {
        patchLatest(queryClient, deviceId, (current) => ({
          ...current,
          pose: payload as unknown as LatestState["pose"],
        }));
      } else if (envelope.payload.kind === "event") {
        void queryClient.invalidateQueries({ queryKey: deviceKeys.ledger(deviceId) });
      }
      break;
    }
    case "command.status_changed": {
      const { command_id: commandId } = envelope.payload;
      const previous = queryClient.getQueryData<Record<string, string>>(deviceKeys.commandStatuses(deviceId));
      const status = reduceCommandStatus(previous?.[commandId], envelope.payload.status);
      queryClient.setQueryData<Record<string, string>>(
        deviceKeys.commandStatuses(deviceId),
        (current = {}) => ({
          ...current,
          [commandId]: status,
        }),
      );
      if (TERMINAL_COMMAND_STATUSES.has(status)) {
        queryClient.setQueryData<Record<string, string>>(
          deviceKeys.pendingCommands(deviceId),
          (current = {}) => {
            if (!(commandId in current)) return current;
            const next = { ...current };
            delete next[commandId];
            return next;
          },
        );
      }
      patchLatest(queryClient, deviceId, (current) => {
        if (!current.command || current.command.command_id !== commandId) return current;
        const command = {
          ...current.command,
          status,
          executed_at: envelope.payload.executed_at ?? envelope.payload.completed_at,
        } as LatestState["command"];
        return { ...current, command };
      });
      if (TERMINAL_COMMAND_STATUSES.has(status)) {
        const voiceStatus = status === "expired" || status === "timed_out" ? "failed" : status;
        queryClient.setQueryData<NotificationOut[]>(deviceKeys.notifications(deviceId), (current = []) =>
          current.map((notification) =>
            notification.voice_command_id === commandId
              ? {
                  ...notification,
                  voice_status: voiceStatus as NotificationOut["voice_status"],
                }
              : notification,
          ),
        );
      }
      break;
    }
    case "ai.run.status_changed": {
      queryClient.setQueryData<AiRunOut>(deviceKeys.aiRun(deviceId, envelope.payload.run_id), (current) =>
        current
          ? {
              ...current,
              status: envelope.payload.status,
              output: envelope.payload.output,
              error_message: envelope.payload.error,
            }
          : current,
      );
      queryClient.setQueryData<AiRunOut[]>(deviceKeys.ai(deviceId), (current = []) =>
        current.map((run) =>
          run.run_id === envelope.payload.run_id
            ? {
                ...run,
                status: envelope.payload.status,
                output: envelope.payload.output ?? run.output,
                error_message: envelope.payload.error ?? run.error_message,
              }
            : run,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: deviceKeys.ai(deviceId) });
      break;
    }
    case "notification.created": {
      const notification = envelope.payload;
      queryClient.setQueryData<NotificationOut[]>(deviceKeys.notifications(deviceId), (current = []) => [
        notification,
        ...current.filter((item) => item.id !== notification.id),
      ]);
      break;
    }
    case "device.capabilities_changed": {
      void queryClient.invalidateQueries({ queryKey: deviceKeys.capabilities(deviceId) });
      break;
    }
    case "automation.policy.changed": {
      queryClient.setQueryData(deviceKeys.automationPolicy(deviceId), envelope.payload);
      break;
    }
    case "automation.plan.changed":
    case "automation.plan.event": {
      void queryClient.invalidateQueries({ queryKey: deviceKeys.automationPlans(deviceId) });
      break;
    }
    case "automation.strategy.changed": {
      void queryClient.invalidateQueries({ queryKey: deviceKeys.aiStrategies(deviceId) });
      break;
    }
    case "system.error":
      break;
  }
}
