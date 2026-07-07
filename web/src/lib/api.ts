export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function wsUrl(deviceId: string) {
  const base = new URL(API_BASE_URL);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = `/ws/devices/${deviceId}`;
  base.search = "";
  return base.toString();
}

export type TelemetryPoint = {
  sampled_at: string;
  sensors: {
    temperature_c: number | null;
    humidity_percent: number | null;
    tvoc_ppb: number | null;
    hcho_ug_m3: number | null;
    eco2_ppm: number | null;
    light_is_dark: boolean | null;
  };
  state: {
    window_open: boolean | null;
    alarm_on: boolean | null;
    manual_override: boolean | null;
  };
  fusion: {
    air_quality: string | null;
    recommend_open_window: boolean | null;
    alarm_enabled: boolean | null;
    reason: string | null;
  };
};

export type CommandInfo = {
  command_id: string;
  type: string;
  parameter: Record<string, unknown>;
  source: string;
  confidence: number;
  reason: string;
  status: string;
  created_at: string;
  published_at: string | null;
  executed_at: string | null;
};

export type AiResultInfo = {
  command_id: string;
  risk_level: string;
  confidence: number;
  reason: string;
  summary?: string;
  model?: string;
};

export type AiDecisionPayload = {
  command: CommandInfo;
  risk_level: string;
  confidence: number;
  reason: string;
  model: string;
  trigger?: string;
  published: boolean;
  image_attached?: boolean;
};

export type DeviceSummary = {
  device_id: string;
  display_name: string;
  status: string;
  last_seen_at: string | null;
};

export type AutopilotState = {
  device_id: string;
  enabled: boolean;
  cooldown_seconds: number;
  min_confidence: number;
  trigger_levels: string[];
};

export type LatestState = {
  device: {
    device_id: string;
    display_name: string;
    status: string;
    last_seen_at: string | null;
  };
  telemetry: TelemetryPoint | null;
  image: { id: number; url: string; created_at: string } | null;
  command: CommandInfo | null;
  ai_result: AiResultInfo | null;
  autopilot?: { enabled: boolean } | null;
};

export type Envelope = {
  type: string;
  device_id: string;
  occurred_at: string;
  payload: Record<string, unknown>;
};

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(`${init?.method ?? "GET"} ${input} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchDevices(): Promise<DeviceSummary[]> {
  return requestJson(`${API_BASE_URL}/api/devices`, { cache: "no-store" });
}

export function fetchLatest(deviceId: string): Promise<LatestState> {
  return requestJson(`${API_BASE_URL}/api/devices/${deviceId}/latest`, { cache: "no-store" });
}

export function fetchHistory(deviceId: string, limit = 120): Promise<TelemetryPoint[]> {
  return requestJson(`${API_BASE_URL}/api/devices/${deviceId}/history?limit=${limit}`, { cache: "no-store" });
}

export function sendCommand(deviceId: string, type: string): Promise<CommandInfo> {
  return requestJson(`${API_BASE_URL}/api/devices/${deviceId}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, parameter: {}, reason: "dashboard command" })
  });
}

export function requestAiAnalysis(deviceId: string): Promise<AiDecisionPayload> {
  return requestJson(`${API_BASE_URL}/api/devices/${deviceId}/ai/analyze`, { method: "POST" });
}

export function fetchAutopilot(deviceId: string): Promise<AutopilotState> {
  return requestJson(`${API_BASE_URL}/api/devices/${deviceId}/autopilot`, { cache: "no-store" });
}

export function updateAutopilot(deviceId: string, enabled: boolean): Promise<AutopilotState> {
  return requestJson(`${API_BASE_URL}/api/devices/${deviceId}/autopilot`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled })
  });
}
