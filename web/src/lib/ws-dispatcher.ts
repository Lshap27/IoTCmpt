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

// 首次拉取与实时追加共用的历史窗口大小（use-device-live 的 fetchHistory 也用它）
export const HISTORY_CAP = 120;
const EVENT_CAP = 30;

let eventSeq = 0;

// 已经收到过 ack 的 command_id 集合（即使 ack 在 onSuccess 添加 pending 之前到达），避免指令按钮永远卡死
const ackedCommands = new Set<string>();

function rememberAcked(id: string) {
  ackedCommands.add(id);
  if (ackedCommands.size > 200) {
    // 仅保留最近 100 个防止无限增长
    const values = [...ackedCommands];
    ackedCommands.clear();
    for (const v of values.slice(-100)) ackedCommands.add(v);
  }
}

export function isAckedCommand(id: string): boolean {
  return ackedCommands.has(id);
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
  // 设备切换时旧连接残留在途消息可能命中新设备缓存，必须按 device_id 过滤
  if (envelope.device_id !== deviceId) return;

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
      queryClient.setQueryData<TelemetryPoint[]>(deviceKeys.history(deviceId), (current = []) => {
        // 重连后的 HTTP 拉取和 WS 实时推送可能包含同一点，去重避免重复 React key
        const tail = current.length && current[current.length - 1].sampled_at === point.sampled_at
          ? current.slice(-(HISTORY_CAP - 1))
          : current.slice(-(HISTORY_CAP - 2));
        return [...tail, point];
      });
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
    case "pose_result": {
      patchLatest(queryClient, deviceId, (current) => ({ ...current, pose: envelope.payload }));
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
      rememberAcked(commandId);
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
    case "event": {
      void queryClient.invalidateQueries({ queryKey: deviceKeys.ledger(deviceId) });
      break;
    }
    default:
      break;
  }
}
