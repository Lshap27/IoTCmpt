"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AiPanel } from "@/components/ai-panel";
import { CameraPanel } from "@/components/camera-panel";
import { CommandPad } from "@/components/command-pad";
import { DeviceHeader } from "@/components/device-header";
import { EventStream } from "@/components/event-stream";
import { HealthReport } from "@/components/health-report";
import { LightCard } from "@/components/light-card";
import { SafetyPanel } from "@/components/safety-panel";
import { StatCard } from "@/components/stat-card";
import { METRICS, TelemetryChart } from "@/components/telemetry-chart";
import { useDeviceLive } from "@/hooks/use-device-live";
import type { AiDecisionPayload } from "@/lib/api";
import { fetchDevices } from "@/lib/api";
import { devicesKey } from "@/lib/query-keys";

const DEFAULT_DEVICE_ID = "esp32s3-001";

export default function Dashboard() {
  const [deviceId, setDeviceId] = useState(DEFAULT_DEVICE_ID);
  const live = useDeviceLive(deviceId);
  const { data: devices = [] } = useQuery({ queryKey: devicesKey, queryFn: fetchDevices });

  const telemetry = live.latest?.telemetry ?? null;

  // WS 推送的最新决策优先；页面刚加载时从 /latest 的 ai_result + command 还原。
  const decision: AiDecisionPayload | null = useMemo(() => {
    if (live.decision) return live.decision;
    const latest = live.latest;
    if (!latest?.ai_result || !latest.command) return null;
    if (latest.ai_result.command_id !== latest.command.command_id) return null;
    return {
      command: latest.command,
      risk_level: latest.ai_result.risk_level as AiDecisionPayload["risk_level"],
      confidence: latest.ai_result.confidence ?? latest.command.confidence,
      reason: latest.ai_result.reason || latest.command.reason,
      model: latest.ai_result.model ?? "",
      trigger: "restored",
      published: latest.command.status !== "pending",
      image_attached: false,
    };
  }, [live.decision, live.latest]);

  const stats = useMemo(
    () =>
      METRICS.map((metric) => ({
        metric,
        value: telemetry?.sensors[metric.key] ?? null,
        points: live.history.map((row) => row.sensors[metric.key] ?? null),
      })),
    [telemetry, live.history],
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

      <div className="mt-4 rounded-lg border border-line bg-raised px-3 py-2 text-[11px] text-ink3">
        室外温湿度与除湿器：未接入硬件，本页面不会用固定值或随机数据代替。
      </div>

      {/* Bento 网格：12 列不等跨度，入场错峰上浮（见 globals.css .bento-grid） */}
      <section className="bento-grid mt-5 grid grid-cols-12 gap-4">
        {stats.map(({ metric, value, points }) => (
          <StatCard
            key={metric.key}
            label={metric.label}
            unit={metric.unit}
            digits={metric.digits}
            color={`var(${metric.cssVar})`}
            value={value}
            points={points}
            className="col-span-12 sm:col-span-6 xl:col-span-3"
          />
        ))}
        <LightCard
          isDark={telemetry?.sensors.light_is_dark}
          history={live.history}
          className="col-span-12 sm:col-span-6 xl:col-span-3"
        />

        <TelemetryChart history={live.history} className="col-span-12 xl:col-span-8" />
        <AiPanel
          analyzing={live.analyzing}
          decision={decision}
          autopilotEnabled={live.autopilotEnabled}
          onToggleAutopilot={live.toggleAutopilot}
          onAnalyze={live.triggerAnalysis}
          className="col-span-12 xl:col-span-4"
        />

        <CameraPanel
          image={live.latest?.image}
          pose={live.latest?.pose}
          onAnalyze={live.requestPose}
          className="col-span-12 md:col-span-6 xl:col-span-4"
        />
        <CommandPad
          onCommand={live.dispatchCommand}
          pendingCommands={live.pendingCommands}
          windowOpen={telemetry?.state.window_open}
          alarmOn={telemetry?.state.alarm_on}
          ledOn={telemetry?.state.led_on}
          className="col-span-12 md:col-span-6 xl:col-span-4"
        />
        <EventStream events={live.events} className="col-span-12 xl:col-span-4" />
        <SafetyPanel
          smokeDetected={telemetry?.sensors.smoke_detected}
          events={live.ledger}
          history={live.history}
          onAcknowledge={live.acknowledgeEvent}
          className="col-span-12"
        />
        <HealthReport history={live.reportHistory} events={live.ledger} className="col-span-12" />
      </section>

      <footer className="mt-6 pb-4 text-center text-[11px] text-ink3">
        宿智云 AIoT · MQTT + FastAPI + LLM 多模态自动决策闭环 · {deviceId}
      </footer>
    </main>
  );
}
