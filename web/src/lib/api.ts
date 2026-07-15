import { client } from "./api-client/client.gen";
import {
  ackDeviceEvent,
  analyzeLatestPose,
  createAiRun,
  cancelAiRun,
  getAiRun,
  getTraceTimeline,
  getAutomationPolicy,
  getDeviceCapabilities,
  deviceEvents,
  deviceNotifications,
  latestDeviceState,
  listAiRuns,
  listDevices,
  sendCommand as sendCommandSdk,
  sendNotification as sendNotificationSdk,
  telemetryHistory,
  telemetryHistoryBucketed,
  updateAutomationPolicy,
  listAutomationPlans,
  listAutomationPlanEvents,
  activateAutomationPlan,
  pauseAutomationPlan,
  resumeAutomationPlan,
  cancelAutomationPlan,
  listAiStrategies,
  approveAiStrategy,
  rejectAiStrategy,
} from "./api-client/sdk.gen";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

client.setConfig({ baseUrl: API_BASE_URL });

// 所有类型均由 `pnpm codegen` 从 server/openapi.json 生成——不要手写协议类型。
export type {
  AiRunOut,
  AutomationPolicyIn,
  AutomationPolicyOut,
  DeviceCapabilitiesOut,
  CommandOut as CommandInfo,
  DeviceSummary,
  LatestState,
  EventOut,
  NotificationOut,
  TelemetryBucketPoint,
  TelemetryPoint,
  TraceTimelineOut,
  WsMessage,
  AutomationPlanOut,
  AutomationPlanEventOut,
  AiStrategyOut,
} from "./api-client/types.gen";

import type {
  AiRunCreate,
  AiRunOut as AiRunOutT,
  AutomationPolicyIn as AutomationPolicyInT,
  AutomationPolicyOut as AutomationPolicyOutT,
  CommandV1Out,
  DeviceCapabilitiesOut as DeviceCapabilitiesOutT,
  DeviceSummary as DeviceSummaryT,
  LatestState as LatestStateT,
  EventOut as EventOutT,
  NotificationOut as NotificationOutT,
  TelemetryBucketPoint as TelemetryBucketPointT,
  TelemetryPoint as TelemetryPointT,
  AutomationPlanOut as AutomationPlanOutT,
  AutomationPlanEventOut as AutomationPlanEventOutT,
  AiStrategyOut as AiStrategyOutT,
} from "./api-client/types.gen";

export type ReportPeriod = "hour" | "day" | "week";
export type AiHealthReport = {
  device_id: string;
  period: ReportPeriod;
  generated_at: string;
  model: string;
  headline: string;
  summary: string;
  risk_score: number;
  anomalies: string[];
  recommendations: string[];
  next_checks: string[];
  coverage: { completeness_percent: number; sample_count: number };
};

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
): Promise<CommandV1Out> {
  const { data } = await sendCommandSdk({
    path: { device_id: deviceId },
    body: {
      type,
      parameter,
      reason: "dashboard command",
    },
    throwOnError: true,
  });
  return data;
}

export async function fetchDeviceEvents(deviceId: string): Promise<EventOutT[]> {
  const { data } = await deviceEvents({
    path: { device_id: deviceId },
    query: { limit: 500 },
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

export async function startAiRun(deviceId: string, body: AiRunCreate): Promise<AiRunOutT> {
  const { data } = await createAiRun({
    path: { device_id: deviceId },
    body,
    throwOnError: true,
  });
  return data;
}

export async function fetchAiRun(deviceId: string, runId: string): Promise<AiRunOutT> {
  const { data } = await getAiRun({
    path: { device_id: deviceId, run_id: runId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function fetchAiRuns(deviceId: string, limit = 50): Promise<AiRunOutT[]> {
  const { data } = await listAiRuns({
    path: { device_id: deviceId },
    query: { limit },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function cancelDeviceAiRun(deviceId: string, runId: string): Promise<AiRunOutT> {
  const { data } = await cancelAiRun({
    path: { device_id: deviceId, run_id: runId },
    throwOnError: true,
  });
  return data;
}

export async function fetchTrace(traceId: string) {
  const { data } = await getTraceTimeline({
    path: { trace_id: traceId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function fetchReadiness(): Promise<{
  status: string;
  dependencies: Record<string, string>;
}> {
  const response = await fetch(`${API_BASE_URL}/health/ready`, { cache: "no-store" });
  if (!response.ok) throw new Error("无法读取网关健康状态");
  return response.json();
}

export type DiagnosticsOverview = {
  ai_runs: Record<string, number>;
  outbox: Record<string, number>;
  realtime: Record<string, number>;
  workers: Array<{
    instance_id: string;
    role: string;
    heartbeat_at: string;
    healthy: boolean;
    age_seconds: number;
  }>;
  capabilities: Array<{
    device_id: string;
    firmware_version: string;
    hardware_model: string;
    command_count: number;
    seen_at: string;
  }>;
  mcp: { external_enabled: boolean; internal_configured: boolean };
};

export async function fetchDiagnosticsOverview(): Promise<DiagnosticsOverview> {
  const response = await fetch(`${API_BASE_URL}/api/v1/diagnostics/overview`, { cache: "no-store" });
  if (!response.ok) throw new Error("无法读取诊断概览");
  return response.json();
}

export async function fetchAutomationPolicy(deviceId: string): Promise<AutomationPolicyOutT> {
  const { data } = await getAutomationPolicy({
    path: { device_id: deviceId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function saveAutomationPolicy(
  deviceId: string,
  values: AutomationPolicyInT,
): Promise<AutomationPolicyOutT> {
  const { data } = await updateAutomationPolicy({
    path: { device_id: deviceId },
    body: values,
    throwOnError: true,
  });
  return data;
}

export async function fetchCapabilities(deviceId: string): Promise<DeviceCapabilitiesOutT> {
  const { data } = await getDeviceCapabilities({
    path: { device_id: deviceId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function fetchAutomationPlans(deviceId: string): Promise<AutomationPlanOutT[]> {
  const { data } = await listAutomationPlans({
    path: { device_id: deviceId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function fetchAutomationPlanEvents(
  deviceId: string,
  planId: string,
): Promise<AutomationPlanEventOutT[]> {
  const { data } = await listAutomationPlanEvents({
    path: { device_id: deviceId, plan_id: planId },
    query: { limit: 100 },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function changeAutomationPlan(
  deviceId: string,
  planId: string,
  action: "activate" | "pause" | "resume" | "cancel",
  replaceActive = false,
): Promise<AutomationPlanOutT> {
  const options = { path: { device_id: deviceId, plan_id: planId }, throwOnError: true } as const;
  if (action === "activate") {
    const { data } = await activateAutomationPlan({ ...options, body: { replace_active: replaceActive } });
    return data;
  }
  if (action === "pause") return (await pauseAutomationPlan(options)).data;
  if (action === "resume") return (await resumeAutomationPlan(options)).data;
  return (await cancelAutomationPlan(options)).data;
}

export async function fetchAiStrategies(deviceId: string): Promise<AiStrategyOutT[]> {
  const { data } = await listAiStrategies({
    path: { device_id: deviceId },
    cache: "no-store",
    throwOnError: true,
  });
  return data;
}

export async function resolveAiStrategy(
  deviceId: string,
  strategyId: string,
  action: "approve" | "reject",
): Promise<AiStrategyOutT> {
  const options = { path: { device_id: deviceId, strategy_id: strategyId }, throwOnError: true } as const;
  return action === "approve"
    ? (await approveAiStrategy(options)).data
    : (await rejectAiStrategy(options)).data;
}
