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

export type LatestState = {
  device: {
    device_id: string;
    display_name: string;
    status: string;
    last_seen_at: string | null;
  };
  telemetry: TelemetryPoint | null;
  image: { id: number; url: string; created_at: string } | null;
  command: {
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
  } | null;
  ai_result: Record<string, unknown> | null;
};

export async function fetchLatest(deviceId: string): Promise<LatestState> {
  const response = await fetch(`${API_BASE_URL}/api/devices/${deviceId}/latest`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load latest state: ${response.status}`);
  }
  return response.json();
}

export async function fetchHistory(deviceId: string): Promise<TelemetryPoint[]> {
  const response = await fetch(`${API_BASE_URL}/api/devices/${deviceId}/history?limit=60`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load history: ${response.status}`);
  }
  return response.json();
}

export async function sendCommand(deviceId: string, type: string) {
  const response = await fetch(`${API_BASE_URL}/api/devices/${deviceId}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, parameter: {}, reason: "dashboard command" })
  });
  if (!response.ok) {
    throw new Error(`Failed to send command: ${response.status}`);
  }
  return response.json();
}

export async function requestAiAnalysis(deviceId: string) {
  const response = await fetch(`${API_BASE_URL}/api/devices/${deviceId}/ai/analyze`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to analyze: ${response.status}`);
  }
  return response.json();
}
