import { client } from "./api-client/client.gen";
import {
  analyzeDevice,
  ackDeviceEvent,
  analyzeLatestPose,
  deviceEvents,
  getAutopilotState,
  latestDeviceState,
  listDevices,
  sendCommand as sendCommandSdk,
  telemetryHistory,
  telemetryHistoryBucketed,
  updateAutopilotState,
} from "./api-client/sdk.gen";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

client.setConfig({ baseUrl: API_BASE_URL });

// 所有类型均由 `pnpm codegen` 从 server/openapi.json 生成——不要手写协议类型。
export type {
  AiDecisionOut as AiDecisionPayload,
  AiResultInfo,
  AutopilotState,
  CommandOut as CommandInfo,
  DeviceSummary,
  LatestState,
  EventOut,
  TelemetryBucketPoint,
  TelemetryPoint,
  WsMessage,
} from "./api-client/types.gen";

import type {
  AiDecisionOut,
  AutopilotState as AutopilotStateT,
  CommandOut,
  DeviceSummary as DeviceSummaryT,
  LatestState as LatestStateT,
  EventOut as EventOutT,
  TelemetryBucketPoint as TelemetryBucketPointT,
  TelemetryPoint as TelemetryPointT,
} from "./api-client/types.gen";

/** WebSocket 信封的宽松视图；WF5 将切换到判别联合 WsMessage。 */
export type Envelope = {
  type: string;
  device_id: string;
  occurred_at: string;
  payload: Record<string, unknown>;
};

export function wsUrl(deviceId: string) {
  const base = new URL(API_BASE_URL);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = `/ws/devices/${deviceId}`;
  base.search = "";
  return base.toString();
}

export async function fetchDevices(): Promise<DeviceSummaryT[]> {
  const { data } = await listDevices({ cache: "no-store", throwOnError: true });
  return data;
}

export async function fetchLatest(deviceId: string): Promise<LatestStateT> {
  const { data } = await latestDeviceState({
    path: { device_id: deviceId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function fetchHistory(deviceId: string, limit = 120): Promise<TelemetryPointT[]> {
  const { data } = await telemetryHistory({
    path: { device_id: deviceId },
    query: { limit },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function fetchHistoryBucketed(
  deviceId: string,
  bucket = 60,
  limit = 200,
): Promise<TelemetryBucketPointT[]> {
  const { data } = await telemetryHistoryBucketed({
    path: { device_id: deviceId },
    query: { bucket, limit },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function sendCommand(deviceId: string, type: string): Promise<CommandOut> {
  const { data } = await sendCommandSdk({
    path: { device_id: deviceId },
    body: {
      type: type as
        | "none"
        | "window.open"
        | "window.close"
        | "alarm.on"
        | "alarm.off"
        | "led.on"
        | "led.off"
        | "display.message",
      parameter: {},
      reason: "dashboard command",
    },
    throwOnError: true,
  });
  return data;
}

export async function fetchDeviceEvents(deviceId: string, type?: string): Promise<EventOutT[]> {
  const { data } = await deviceEvents({
    path: { device_id: deviceId },
    query: { type, limit: 500 },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function acknowledgeDeviceEvent(deviceId: string, eventId: number): Promise<EventOutT> {
  const { data } = await ackDeviceEvent({
    path: { device_id: deviceId, event_id: eventId },
    throwOnError: true,
  });
  return data;
}

export async function requestPoseAnalysis(deviceId: string) {
  const { data } = await analyzeLatestPose({ path: { device_id: deviceId }, throwOnError: true });
  return data;
}

export async function requestAiAnalysis(deviceId: string): Promise<AiDecisionOut> {
  const { data } = await analyzeDevice({ path: { device_id: deviceId }, throwOnError: true });
  return data;
}

export async function fetchAutopilot(deviceId: string): Promise<AutopilotStateT> {
  const { data } = await getAutopilotState({
    path: { device_id: deviceId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function updateAutopilot(deviceId: string, enabled: boolean): Promise<AutopilotStateT> {
  const { data } = await updateAutopilotState({
    path: { device_id: deviceId },
    body: { enabled },
    throwOnError: true,
  });
  return data;
}
