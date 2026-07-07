"use client";

import { useEffect, useMemo, useState } from "react";
import { AiPanel } from "@/components/ai-panel";
import { CameraPanel } from "@/components/camera-panel";
import { CommandPad } from "@/components/command-pad";
import { DeviceHeader } from "@/components/device-header";
import { EventStream } from "@/components/event-stream";
import { StatCard } from "@/components/stat-card";
import { METRICS, TelemetryChart } from "@/components/telemetry-chart";
import { useDeviceLive } from "@/hooks/use-device-live";
import { AiDecisionPayload, DeviceSummary, fetchDevices } from "@/lib/api";

const DEFAULT_DEVICE_ID = "esp32s3-001";

export default function Dashboard() {
  const [devices, setDevices] = useState<DeviceSummary[]>([]);
  const [deviceId, setDeviceId] = useState(DEFAULT_DEVICE_ID);
  const live = useDeviceLive(deviceId);

  useEffect(() => {
    fetchDevices()
      .then(setDevices)
      .catch(() => undefined);
  }, []);

  const telemetry = live.latest?.telemetry ?? null;

  // WS 推送的最新决策优先；页面刚加载时从 /latest 的 ai_result + command 还原。
  const decision: AiDecisionPayload | null = useMemo(() => {
    if (live.decision) return live.decision;
    const latest = live.latest;
    if (!latest?.ai_result || !latest.command) return null;
    if (latest.ai_result.command_id !== latest.command.command_id) return null;
    return {
      command: latest.command,
      risk_level: latest.ai_result.risk_level,
      confidence: latest.ai_result.confidence ?? latest.command.confidence,
      reason: latest.ai_result.reason || latest.command.reason,
      model: latest.ai_result.model ?? "",
      published: latest.command.status !== "pending"
    };
  }, [live.decision, live.latest]);

  const stats = useMemo(
    () =>
      METRICS.map((metric) => ({
        metric,
        value: telemetry?.sensors[metric.key] ?? null,
        points: live.history.map((row) => row.sensors[metric.key])
      })),
    [telemetry, live.history]
  );

  return (
    <main className="mx-auto min-h-screen max-w-[1400px] px-4 py-5 lg:px-8">
      <DeviceHeader
        devices={devices}
        deviceId={deviceId}
        onDeviceChange={setDeviceId}
        deviceStatus={live.latest?.device.status ?? "unknown"}
        airQuality={telemetry?.fusion.air_quality}
        socketState={live.socketState}
      />

      {live.error ? (
        <div
          className="mt-4 rounded-lg border px-3 py-2 text-xs font-medium"
          style={{ borderColor: "var(--alert)", background: "var(--alert-soft)", color: "var(--alert)" }}
        >
          {live.error}
        </div>
      ) : null}
      {live.socketState !== "live" ? (
        <div
          className="mt-4 rounded-lg border px-3 py-2 text-xs font-medium"
          style={{ borderColor: "var(--warn)", background: "var(--warn-soft)", color: "var(--warn)" }}
        >
          {live.socketState === "connecting" ? "正在连接实时通道…" : "实时通道已断开，正在自动重连"}
          ，页面展示最近一次同步的数据
        </div>
      ) : null}

      <section className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map(({ metric, value, points }) => (
          <StatCard
            key={metric.key}
            label={metric.label}
            unit={metric.unit}
            digits={metric.digits}
            color={`var(${metric.cssVar})`}
            value={value}
            points={points}
          />
        ))}
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-3">
        <TelemetryChart history={live.history} className="xl:col-span-2" />
        <AiPanel
          analyzing={live.analyzing}
          decision={decision}
          autopilotEnabled={live.autopilotEnabled}
          onToggleAutopilot={live.toggleAutopilot}
          onAnalyze={live.triggerAnalysis}
        />
      </section>

      <section className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <CameraPanel image={live.latest?.image} />
        <CommandPad
          onCommand={live.dispatchCommand}
          pendingCommands={live.pendingCommands}
          windowOpen={telemetry?.state.window_open}
          alarmOn={telemetry?.state.alarm_on}
        />
        <EventStream events={live.events} className="lg:col-span-2 xl:col-span-1" />
      </section>

      <footer className="mt-6 pb-4 text-center text-[11px] text-ink3">
        宿智云 AIoT · MQTT + FastAPI + LLM 多模态自动决策闭环 · {deviceId}
      </footer>
    </main>
  );
}
