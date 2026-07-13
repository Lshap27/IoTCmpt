import { client } from "./api-client/client.gen";
import {
  analyzeDevice,
  analyzeDeviceImage,
  ackDeviceEvent,
  analyzeLatestPose,
  deviceEvents,
  deviceNotifications,
  getAutopilotState,
  latestDeviceState,
  listDevices,
  sendCommand as sendCommandSdk,
  sendNotification as sendNotificationSdk,
  telemetryHistory,
  telemetryHistoryBucketed,
  updateAutopilotState,
  createAiHealthReport,
} from "./api-client/sdk.gen";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

client.setConfig({ baseUrl: API_BASE_URL });

// 所有类型均由 `pnpm codegen` 从 server/openapi.json 生成——不要手写协议类型。
export type {
  AiDecisionOut as AiDecisionPayload,
  AiHealthReport,
  AiResultInfo,
  AutopilotState,
  CommandOut as CommandInfo,
  DeviceSummary,
  LatestState,
  EventOut,
  NotificationOut,
  TelemetryBucketPoint,
  TelemetryPoint,
  WsMessage,
} from "./api-client/types.gen";

import type {
  AiDecisionOut,
  AiHealthReport as AiHealthReportT,
  AiReportIn as AiReportInT,
  AutopilotState as AutopilotStateT,
  CommandOut,
  DeviceSummary as DeviceSummaryT,
  LatestState as LatestStateT,
  EventOut as EventOutT,
  NotificationOut as NotificationOutT,
  TelemetryBucketPoint as TelemetryBucketPointT,
  TelemetryPoint as TelemetryPointT,
} from "./api-client/types.gen";

export type ReportPeriod = AiReportInT["period"];

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
  // 保留原 base 的路径前缀（如反向代理 /aiot），并追加设备 WebSocket 路由
  const prefix = base.pathname.replace(/\/+$/, "");
  base.pathname = `${prefix}/ws/devices/${encodeURIComponent(deviceId)}`;
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

export async function sendCommand(
  deviceId: string,
  type: string,
  parameter: Record<string, unknown> = {},
): Promise<CommandOut> {
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
        | "control.set_priority"
        | "control.resume_auto"
        | "alarm.silence"
        | "voice.speak"
        | "display.message",
      parameter,
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

export async function fetchNotifications(deviceId: string, limit = 50): Promise<NotificationOutT[]> {
  const { data } = await deviceNotifications({
    path: { device_id: deviceId },
    query: { limit },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function sendDormNotification(
  deviceId: string,
  content: string,
  voiceBroadcast: boolean,
): Promise<NotificationOutT> {
  const { data } = await sendNotificationSdk({
    path: { device_id: deviceId },
    body: { content, voice_broadcast: voiceBroadcast },
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

export async function requestAiImageAnalysis(deviceId: string): Promise<AiDecisionOut> {
  const { data } = await analyzeDeviceImage({ path: { device_id: deviceId }, throwOnError: true });
  return data;
}

export async function requestAiReport(deviceId: string, period: ReportPeriod): Promise<AiHealthReportT> {
  const { data } = await createAiHealthReport({
    path: { device_id: deviceId },
    body: { period },
    throwOnError: true,
  });
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

export async function updateAutopilot(
  deviceId: string,
  values: {
    enabled?: boolean;
    vision_interval_enabled?: boolean;
    vision_interval_seconds?: number;
    sedentary_threshold_seconds?: number;
    smoke_silence_seconds?: number;
  },
): Promise<AutopilotStateT> {
  const { data } = await updateAutopilotState({
    path: { device_id: deviceId },
    body: values,
    throwOnError: true,
  });
  return data;
}
