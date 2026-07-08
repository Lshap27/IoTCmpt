import type { QueryClient } from "@tanstack/react-query";
import type { AiDecisionPayload, LatestState, TelemetryPoint, WsMessage } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";

export type UiEvent = {
  id: number;
  type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type AiPanelState = {
  analyzing: string | null;
  decision: AiDecisionPayload | null;
};

export const EMPTY_AI: AiPanelState = { analyzing: null, decision: null };

const HISTORY_CAP = 120;
const EVENT_CAP = 30;

let eventSeq = 0;

function patchLatest(
  queryClient: QueryClient,
  deviceId: string,
  patch: (current: LatestState) => LatestState,
) {
  queryClient.setQueryData<LatestState>(deviceKeys.latest(deviceId), (current) =>
    current ? patch(current) : current,
  );
}

function setAi(queryClient: QueryClient, deviceId: string, patch: (current: AiPanelState) => AiPanelState) {
  queryClient.setQueryData<AiPanelState>(deviceKeys.ai(deviceId), (current = EMPTY_AI) => patch(current));
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

/** WebSocket envelope → query cache 的纯分发器；envelope 类型由 codegen 的判别联合窄化。 */
export function applyEnvelope(queryClient: QueryClient, deviceId: string, envelope: WsMessage) {
  eventSeq += 1;
  queryClient.setQueryData<UiEvent[]>(deviceKeys.events(deviceId), (current = []) =>
    [
      {
        id: eventSeq,
        type: envelope.type,
        payload: envelope.payload as Record<string, unknown>,
        occurred_at: envelope.occurred_at,
      },
      ...current,
    ].slice(0, EVENT_CAP),
  );

  switch (envelope.type) {
    case "telemetry": {
      const point = envelope.payload;
      queryClient.setQueryData<TelemetryPoint[]>(deviceKeys.history(deviceId), (current = []) => [
        ...current.slice(-(HISTORY_CAP - 1)),
        point,
      ]);
      patchLatest(queryClient, deviceId, (current) => ({
        ...current,
        telemetry: point,
        device: { ...current.device, status: "online", last_seen_at: envelope.occurred_at },
      }));
      break;
    }
    case "status": {
      const { status } = envelope.payload;
      patchLatest(queryClient, deviceId, (current) => ({
        ...current,
        device: { ...current.device, status, last_seen_at: envelope.occurred_at },
      }));
      break;
    }
    case "image": {
      patchLatest(queryClient, deviceId, (current) => ({ ...current, image: envelope.payload }));
      break;
    }
    case "ai_analyzing": {
      setAi(queryClient, deviceId, (current) => ({ ...current, analyzing: envelope.payload.trigger }));
      break;
    }
    case "ai_result": {
      const result = envelope.payload;
      setAi(queryClient, deviceId, () => ({ analyzing: null, decision: result }));
      patchLatest(queryClient, deviceId, (current) => ({ ...current, command: result.command }));
      break;
    }
    case "command": {
      patchLatest(queryClient, deviceId, (current) => ({ ...current, command: envelope.payload }));
      break;
    }
    case "command_ack": {
      const { command_id: commandId, status, executed_at } = envelope.payload;
      if (!commandId) break;
      queryClient.setQueryData<Record<string, string>>(
        deviceKeys.pendingCommands(deviceId),
        (current = {}) => {
          if (!(commandId in current)) return current;
          const next = { ...current };
          delete next[commandId];
          return next;
        },
      );
      patchLatest(queryClient, deviceId, (current) =>
        current.command && current.command.command_id === commandId
          ? {
              ...current,
              command: {
                ...current.command,
                status: status || current.command.status,
                executed_at: executed_at ?? current.command.executed_at,
              },
            }
          : current,
      );
      break;
    }
    case "autopilot": {
      patchLatest(queryClient, deviceId, (current) => ({
        ...current,
        autopilot: { enabled: envelope.payload.enabled },
      }));
      break;
    }
    default:
      break;
  }
}
