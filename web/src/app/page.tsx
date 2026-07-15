"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AiPanel } from "@/components/ai-panel";
import { AutomationPlanPanel } from "@/components/automation-plan-panel";
import { CameraPanel } from "@/components/camera-panel";
import { CommandPad } from "@/components/command-pad";
import { DeviceHeader } from "@/components/device-header";
import { EventStream } from "@/components/event-stream";
import { HealthReport } from "@/components/health-report";
import { LightCard } from "@/components/light-card";
import { NotificationCenter } from "@/components/notification-center";
import { SafetyPanel } from "@/components/safety-panel";
import { StatCard } from "@/components/stat-card";
import { METRICS, TelemetryChart } from "@/components/telemetry-chart";
import { useDeviceLive } from "@/hooks/use-device-live";
import { fetchDevices } from "@/lib/api";
import { devicesKey } from "@/lib/query-keys";

const DEFAULT_DEVICE_ID = "esp32s3-001";

export default function Dashboard() {
  const [deviceId, setDeviceId] = useState(DEFAULT_DEVICE_ID);
  const [smokeSilenceSeconds, setSmokeSilenceSeconds] = useState(60);
  const live = useDeviceLive(deviceId);
  const { data: devices = [] } = useQuery({ queryKey: devicesKey, queryFn: fetchDevices });

  const telemetry = live.latest?.telemetry ?? null;

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
    <main className="mx-auto min-h-dvh max-w-[1480px] px-4 py-5 sm:px-6 lg:px-10 lg:py-8">
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
          className="mt-5 rounded-xl border px-4 py-3 text-sm font-medium"
          style={{ borderColor: "var(--alert)", background: "var(--alert-soft)", color: "var(--alert)" }}
        >
          {live.error}
        </div>
      ) : null}
      {live.socketState !== "live" ? (
        <div
          className="mt-5 rounded-xl border px-4 py-3 text-sm font-medium"
          style={{ borderColor: "var(--warn)", background: "var(--warn-soft)", color: "var(--warn)" }}
        >
          {live.socketState === "connecting" ? "正在连接实时通道…" : "实时通道已断开，正在自动重连"}
          ，页面展示最近一次同步的数据
        </div>
      ) : null}

      <NotificationCenter notifications={live.notifications} />

      <section className="mt-8" aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="mb-4 text-lg font-semibold tracking-tight text-ink">
          环境概览
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
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
          <LightCard isDark={telemetry?.sensors.light_is_dark} history={live.history} />
        </div>
      </section>

      <section className="bento-grid mt-5 grid grid-cols-12 gap-4 lg:gap-5">
        <TelemetryChart
          history={live.history}
          className="col-span-12 xl:col-span-8 xl:h-[25rem] xl:overflow-hidden"
        />
        <AiPanel
          analyzing={live.analyzing}
          run={live.decisionRun}
          runs={live.aiRuns}
          policy={live.automationPolicy}
          onToggleAutomation={live.toggleAutomationPolicy}
          onUpdatePolicy={live.updatePolicy}
          onAnalyze={live.triggerAnalysis}
          onCancelRun={live.cancelAiRun}
          className="col-span-12 xl:col-span-4 xl:h-[25rem] xl:overflow-hidden"
        />
        <AutomationPlanPanel deviceId={deviceId} className="col-span-12 xl:col-span-6" />

        <CameraPanel
          image={live.latest?.image}
          pose={live.latest?.pose}
          onAnalyze={live.requestPose}
          onAiAnalyze={live.triggerImageAnalysis}
          aiAnalyzing={live.imageAnalyzing}
          policy={live.automationPolicy}
          onUpdateAutomation={live.updateAutomation}
          className="col-span-12 md:col-span-6 xl:col-span-4"
        />
        <CommandPad
          onCommand={live.dispatchCommand}
          pendingCommands={live.pendingCommands}
          windowOpen={telemetry?.state.window_open}
          alarmOn={telemetry?.state.alarm_on}
          ledOn={telemetry?.state.led_on}
          controlPriority={telemetry?.state.control_priority}
          manualWindowOverride={telemetry?.state.manual_window_override}
          manualLedOverride={telemetry?.state.manual_led_override}
          availableCommands={live.capabilities?.commands.map((command) => command.name)}
          className="col-span-12 md:col-span-6 xl:col-span-4"
        />
        <EventStream events={live.events} className="col-span-12 xl:col-span-4" />
        <SafetyPanel
          smokeDetected={telemetry?.sensors.smoke_detected}
          events={live.ledger}
          history={live.history}
          onAcknowledge={live.acknowledgeEvent}
          onSilence={() =>
            live.dispatchCommand("alarm.silence", {
              duration_seconds: smokeSilenceSeconds,
            })
          }
          silenceSeconds={smokeSilenceSeconds}
          smokeSilenced={telemetry?.state.smoke_silenced}
          onUpdateSilenceSeconds={setSmokeSilenceSeconds}
          className="col-span-12"
        />
        <HealthReport
          deviceId={deviceId}
          history={live.reportHistory}
          events={live.ledger}
          aiReport={live.healthReport}
          generating={live.reportGenerating}
          onGenerate={live.generateReport}
          className="col-span-12"
        />
      </section>
    </main>
  );
}
