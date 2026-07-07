"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Bell, BrainCircuit, Camera, Cloud, PanelRightOpen, Radio, Wind } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fetchHistory, fetchLatest, requestAiAnalysis, sendCommand, TelemetryPoint, wsUrl } from "@/lib/api";

const DEVICE_ID = "esp32s3-001";

type EventRow = {
  type: string;
  text: string;
  occurred_at: string;
};

export default function Dashboard() {
  const [latest, setLatest] = useState<Awaited<ReturnType<typeof fetchLatest>> | null>(null);
  const [history, setHistory] = useState<TelemetryPoint[]>([]);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [socketState, setSocketState] = useState("connecting");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [latestState, historyState] = await Promise.all([fetchLatest(DEVICE_ID), fetchHistory(DEVICE_ID)]);
        if (!cancelled) {
          setLatest(latestState);
          setHistory(historyState.reverse());
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载失败");
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const socket = new WebSocket(wsUrl(DEVICE_ID));
    socket.onopen = () => setSocketState("live");
    socket.onclose = () => setSocketState("offline");
    socket.onerror = () => setSocketState("error");
    socket.onmessage = (message) => {
      let envelope;
      try {
        envelope = JSON.parse(message.data);
      } catch {
        setEvents((current) =>
          [
            {
              type: "error",
              text: "WebSocket message is not valid JSON",
              occurred_at: new Date().toISOString()
            },
            ...current
          ].slice(0, 12)
        );
        return;
      }
      setEvents((current) =>
        [
          {
            type: envelope.type,
            text: JSON.stringify(envelope.payload),
            occurred_at: envelope.occurred_at
          },
          ...current
        ].slice(0, 12)
      );
      if (envelope.type === "telemetry") {
        setHistory((current) => [...current.slice(-59), envelope.payload]);
      }
      if (["telemetry", "status", "image", "ai_result", "command", "command_ack"].includes(envelope.type)) {
        fetchLatest(DEVICE_ID).then(setLatest).catch(() => undefined);
      }
    };
    return () => socket.close();
  }, []);

  const chartData = useMemo(
    () =>
      history.map((item) => ({
        time: new Date(item.sampled_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
        temperature: item.sensors.temperature_c,
        humidity: item.sensors.humidity_percent,
        tvoc: item.sensors.tvoc_ppb
      })),
    [history]
  );

  const telemetry = latest?.telemetry;
  const hasTelemetry = Boolean(telemetry);
  const deviceStatus = latest?.device.status ?? "unknown";
  const latestCommand = latest?.command;
  const latestImageAt = latest?.image?.created_at ? new Date(latest.image.created_at).toLocaleString() : "--";
  const liveStatusText =
    socketState === "live"
      ? "实时通道已连接"
      : socketState === "connecting"
        ? "正在连接实时通道"
        : "实时通道不可用，页面保留最后一次 HTTP 数据";

  async function command(type: string) {
    setError("");
    try {
      await sendCommand(DEVICE_ID, type);
    } catch (err) {
      setError(err instanceof Error ? err.message : "指令下发失败");
    }
  }

  async function analyze() {
    setError("");
    try {
      await requestAiAnalysis(DEVICE_ID);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 分析失败");
    }
  }

  return (
    <main className="min-h-screen px-5 py-5 lg:px-8">
      <header className="mb-5 flex flex-col gap-3 border-b border-line pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold text-accent">ESP32-S3 AIoT 控制中心</p>
          <h1 className="text-2xl font-semibold text-ink">宿智云实时设备台</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge icon={<Radio size={16} />} label={`WS ${socketState}`} />
          <Badge icon={<Cloud size={16} />} label={latest?.device.status ?? "unknown"} />
          <Badge icon={<Activity size={16} />} label={DEVICE_ID} />
        </div>
      </header>

      {error ? <div className="mb-4 border border-danger bg-white px-3 py-2 text-sm text-danger">{error}</div> : null}
      {socketState !== "live" ? (
        <div className="mb-4 border border-warn bg-white px-3 py-2 text-sm text-warn">{liveStatusText}</div>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_340px]">
        <aside className="space-y-4">
          <Panel title="设备状态" icon={<PanelRightOpen size={18} />}>
            <Metric label="在线状态" value={deviceStatus} />
            <Metric label="最近上报" value={latest?.device.last_seen_at ? new Date(latest.device.last_seen_at).toLocaleString() : "--"} />
            <Metric label="空气质量" value={telemetry?.fusion.air_quality ?? "--"} />
            <Metric label="开窗建议" value={hasTelemetry ? (telemetry?.fusion.recommend_open_window ? "建议开窗" : "无需开窗") : "--"} />
          </Panel>

          <Panel title="硬件验收" icon={<Cloud size={18} />}>
            <Metric label="Telemetry" value={hasTelemetry ? "已接入" : "等待上报"} />
            <Metric label="命令状态" value={latestCommand?.status ?? "--"} />
            <Metric
              label="执行时间"
              value={latestCommand?.executed_at ? new Date(latestCommand.executed_at).toLocaleString() : "--"}
            />
            <Metric label="图片时间" value={latestImageAt} />
          </Panel>

          <Panel title="传感器" icon={<Wind size={18} />}>
            <Metric label="温度" value={formatValue(telemetry?.sensors.temperature_c, "C")} />
            <Metric label="湿度" value={formatValue(telemetry?.sensors.humidity_percent, "%")} />
            <Metric label="TVOC" value={formatValue(telemetry?.sensors.tvoc_ppb, "ppb")} />
            <Metric label="eCO2" value={formatValue(telemetry?.sensors.eco2_ppm, "ppm")} />
          </Panel>
        </aside>

        <section className="space-y-4">
          <Panel title="实时图像" icon={<Camera size={18} />}>
            <div className="aspect-video overflow-hidden border border-line bg-panel">
              {latest?.image?.url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={latest.image.url} alt="latest device capture" className="h-full w-full object-contain" />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-slate-500">等待设备上传图片</div>
              )}
            </div>
          </Panel>

          <Panel title="传感器曲线" icon={<Activity size={18} />}>
            <div className="h-64">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <CartesianGrid stroke="#D9E2EC" />
                    <XAxis dataKey="time" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Line type="monotone" dataKey="temperature" stroke="#0E7C86" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="humidity" stroke="#5B8DEF" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="tvoc" stroke="#C77D12" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center border border-line bg-panel text-sm text-slate-500">
                  等待 telemetry 数据
                </div>
              )}
            </div>
          </Panel>
        </section>

        <aside className="space-y-4">
          <Panel title="AI 决策" icon={<BrainCircuit size={18} />}>
            <Metric label="最新指令" value={latestCommand?.type ?? "--"} />
            <Metric label="发布状态" value={latestCommand?.status ?? "--"} />
            <Metric
              label="发布时间"
              value={latestCommand?.published_at ? new Date(latestCommand.published_at).toLocaleString() : "--"}
            />
            <Metric label="置信度" value={String(latestCommand?.confidence ?? "--")} />
            <Metric label="原因" value={latestCommand?.reason ?? telemetry?.fusion.reason ?? "--"} />
            <button className="mt-3 w-full border border-accent bg-accent px-3 py-2 text-sm font-semibold text-white" onClick={analyze}>
              触发 AI 分析
            </button>
          </Panel>

          <Panel title="设备指令" icon={<Bell size={18} />}>
            <div className="grid grid-cols-2 gap-2">
              <Action label="开窗" onClick={() => command("window.open")} />
              <Action label="关窗" onClick={() => command("window.close")} />
              <Action label="报警开" onClick={() => command("alarm.on")} />
              <Action label="报警关" onClick={() => command("alarm.off")} />
            </div>
          </Panel>

          <Panel title="事件流" icon={<Radio size={18} />}>
            <div className="space-y-2">
              {events.length === 0 ? <p className="text-sm text-slate-500">等待实时事件</p> : null}
              {events.map((event, index) => (
                <div key={`${event.occurred_at}-${index}`} className="border border-line bg-panel px-2 py-2 text-xs">
                  <div className="mb-1 flex justify-between gap-2 font-semibold">
                    <span>{event.type}</span>
                    <span>{new Date(event.occurred_at).toLocaleTimeString()}</span>
                  </div>
                  <p className="line-clamp-2 break-all text-slate-600">{event.text}</p>
                </div>
              ))}
            </div>
          </Panel>
        </aside>
      </section>
    </main>
  );
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border border-line bg-white p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
        {icon}
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line py-2 last:border-b-0">
      <span className="shrink-0 text-sm text-slate-500">{label}</span>
      <span className="min-w-0 max-w-[170px] break-words text-right text-sm font-semibold text-ink">{value}</span>
    </div>
  );
}

function Badge({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 border border-line bg-white px-2 py-1 text-ink">
      {icon}
      {label}
    </span>
  );
}

function Action({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button className="border border-line bg-panel px-3 py-2 text-sm font-semibold text-ink hover:border-accent" onClick={onClick}>
      {label}
    </button>
  );
}

function formatValue(value: number | null | undefined, unit: string) {
  return typeof value === "number" ? `${value.toFixed(1)} ${unit}` : "--";
}
