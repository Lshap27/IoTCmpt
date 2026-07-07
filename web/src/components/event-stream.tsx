"use client";

import {
  Activity,
  AlertTriangle,
  Bot,
  BrainCircuit,
  Camera,
  CheckCircle2,
  Radio,
  Send,
  Sparkles,
  Terminal,
  Wifi,
  WifiOff,
  XCircle,
  type LucideIcon
} from "lucide-react";
import { Panel } from "@/components/panel";
import type { UiEvent } from "@/hooks/use-device-live";
import { commandLabel, describeTrigger, formatClock } from "@/lib/utils";

type EventView = { Icon: LucideIcon; color: string; title: string; detail: string };

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function num(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function describeEvent(event: UiEvent): EventView {
  const payload = event.payload ?? {};
  switch (event.type) {
    case "telemetry": {
      const sensors = (payload.sensors ?? {}) as Record<string, unknown>;
      const fusion = (payload.fusion ?? {}) as Record<string, unknown>;
      const parts = [
        num(sensors.temperature_c) !== null ? `${(sensors.temperature_c as number).toFixed(1)}°C` : null,
        num(sensors.humidity_percent) !== null ? `${(sensors.humidity_percent as number).toFixed(0)}%RH` : null,
        num(sensors.tvoc_ppb) !== null ? `TVOC ${(sensors.tvoc_ppb as number).toFixed(0)}` : null,
        num(sensors.eco2_ppm) !== null ? `eCO₂ ${(sensors.eco2_ppm as number).toFixed(0)}` : null
      ].filter(Boolean);
      return {
        Icon: Activity,
        color: "var(--accent)",
        title: "遥测更新",
        detail: parts.join(" · ") || str(fusion.reason)
      };
    }
    case "status": {
      const online = str(payload.status) === "online";
      return {
        Icon: online ? Wifi : WifiOff,
        color: online ? "var(--good)" : "var(--ink-3)",
        title: online ? "设备上线" : "设备离线",
        detail: ""
      };
    }
    case "image":
      return { Icon: Camera, color: "var(--m-hum)", title: "新画面已上传", detail: "" };
    case "ai_analyzing":
      return {
        Icon: BrainCircuit,
        color: "var(--m-eco2)",
        title: "AI 分析开始",
        detail: describeTrigger(str(payload.trigger))
      };
    case "ai_result": {
      const command = (payload.command ?? {}) as Record<string, unknown>;
      const confidence = num(payload.confidence) ?? 0;
      return {
        Icon: Sparkles,
        color: "var(--m-eco2)",
        title: `AI 决策：${commandLabel(str(command.type) || "none")}`,
        detail: `置信 ${Math.round(confidence * 100)}% · ${payload.published ? "已下发" : "仅建议"}`
      };
    }
    case "command": {
      const source = str(payload.source);
      const sourceLabel = source === "llm" ? "AI" : source === "rule" ? "规则" : "手动";
      return {
        Icon: Send,
        color: "var(--accent)",
        title: `下发指令：${commandLabel(str(payload.type))}`,
        detail: `来源 ${sourceLabel}`
      };
    }
    case "command_ack": {
      const status = str(payload.status);
      const view =
        status === "executed"
          ? { Icon: CheckCircle2, color: "var(--good)", title: "指令执行成功" }
          : status === "rejected"
            ? { Icon: XCircle, color: "var(--warn)", title: "指令被设备拒绝" }
            : { Icon: XCircle, color: "var(--alert)", title: "指令执行失败" };
      return { ...view, detail: str(payload.message) };
    }
    case "autopilot":
      return {
        Icon: Bot,
        color: payload.enabled ? "var(--good)" : "var(--warn)",
        title: `自动决策已${payload.enabled ? "开启" : "暂停"}`,
        detail: ""
      };
    case "event":
      return {
        Icon: str(payload.type) === "autopilot" ? Bot : Radio,
        color: "var(--warn)",
        title: str(payload.type) === "autopilot" ? "自动决策触发" : "设备事件",
        detail: str(payload.message)
      };
    case "log":
      return { Icon: Terminal, color: "var(--ink-3)", title: "设备日志", detail: str(payload.message ?? payload.raw) };
    case "error":
      return {
        Icon: AlertTriangle,
        color: "var(--alert)",
        title: "异常",
        detail: str(payload.error ?? payload.reason ?? payload.topic)
      };
    default:
      return { Icon: Radio, color: "var(--ink-3)", title: event.type, detail: "" };
  }
}

export function EventStream({ events, className }: { events: UiEvent[]; className?: string }) {
  return (
    <Panel title="实时事件流" icon={<Radio size={17} />} className={className}>
      <div className="scroll-thin max-h-72 space-y-1.5 overflow-y-auto pr-1">
        {events.length === 0 ? (
          <p className="py-8 text-center text-xs text-ink3">等待实时事件…</p>
        ) : (
          events.map((event) => {
            const view = describeEvent(event);
            return (
              <div
                key={event.id}
                className="flex animate-fade-slide items-start gap-2.5 rounded-lg border border-line bg-raised px-2.5 py-2"
              >
                <span
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
                  style={{ color: view.color, background: "var(--surface-solid)" }}
                >
                  <view.Icon size={13} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="truncate text-xs font-medium text-ink">{view.title}</p>
                    <span className="tnum shrink-0 text-[10px] text-ink3">{formatClock(event.occurred_at)}</span>
                  </div>
                  {view.detail ? <p className="mt-0.5 truncate text-[11px] text-ink3">{view.detail}</p> : null}
                </div>
              </div>
            );
          })
        )}
      </div>
    </Panel>
  );
}
