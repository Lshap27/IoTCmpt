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
  type LucideIcon,
} from "lucide-react";
import { Panel } from "@/components/panel";
import type { UiEvent } from "@/hooks/use-device-live";
import { cn, commandLabel, describeTrigger, formatClock } from "@/lib/utils";

type EventView = {
  Icon: LucideIcon;
  color: string;
  category: string;
  title: string;
  detail: string;
};

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function num(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function readableAckMessage(message: string, status: string): string {
  if (!message) return status === "executed" ? "设备已完成执行并回传确认" : "设备未提供详细原因";
  if (message.includes("applied by simulator")) return "虚拟设备已完成执行并回传确认";
  if (message.includes("manual window override")) return "窗户处于手动锁定，自动指令未执行";
  if (message.includes("manual LED override")) return "LED 处于手动锁定，自动指令未执行";
  if (message.includes("no active smoke alarm")) return "当前没有需要静音的烟雾报警";
  if (message.includes("unsupported command")) return "设备固件不支持该指令";
  return message;
}

function describeEvent(event: UiEvent): EventView {
  const payload = event.payload ?? {};
  switch (event.type) {
    case "telemetry": {
      const sensors = (payload.sensors ?? {}) as Record<string, unknown>;
      const fusion = (payload.fusion ?? {}) as Record<string, unknown>;
      const parts = [
        num(sensors.temperature_c) !== null ? `温度 ${(sensors.temperature_c as number).toFixed(1)}°C` : null,
        num(sensors.humidity_percent) !== null
          ? `湿度 ${(sensors.humidity_percent as number).toFixed(0)}%`
          : null,
        num(sensors.tvoc_ppb) !== null ? `TVOC ${(sensors.tvoc_ppb as number).toFixed(0)} ppb` : null,
        num(sensors.eco2_ppm) !== null ? `eCO₂ ${(sensors.eco2_ppm as number).toFixed(0)} ppm` : null,
      ].filter(Boolean);
      const airQuality = str(fusion.air_quality);
      const view =
        airQuality === "alert"
          ? { title: "环境指标达到告警级别", color: "var(--alert)" }
          : airQuality === "watch"
            ? { title: "环境指标需要关注", color: "var(--warn)" }
            : airQuality === "good"
              ? { title: "环境数据正常", color: "var(--good)" }
              : { title: "传感器数据已更新", color: "var(--accent)" };
      return {
        Icon: Activity,
        color: view.color,
        category: "传感器",
        title: view.title,
        detail: parts.join(" · ") || str(fusion.reason),
      };
    }
    case "status": {
      const online = str(payload.status) === "online";
      return {
        Icon: online ? Wifi : WifiOff,
        color: online ? "var(--good)" : "var(--ink-3)",
        category: "设备",
        title: online ? "设备上线" : "设备离线",
        detail: online ? "设备已连接 MQTT，开始接收实时数据" : "实时数据已中断，页面保留最后一次状态",
      };
    }
    case "image":
      return {
        Icon: Camera,
        color: "var(--m-hum)",
        category: "视觉",
        title: "摄像头上传了新画面",
        detail: "画面已保存，可进行姿态识别或 AI 精准分析",
      };
    case "pose_result":
      return {
        Icon: Camera,
        color: "var(--m-hum)",
        category: "视觉",
        title: payload.human_present
          ? `检测到人体：${str(payload.label) || "姿态未知"}`
          : "画面中未检测到人体",
        detail: `识别置信度 ${Math.round((num(payload.confidence) ?? 0) * 100)}%`,
      };
    case "ai_analyzing":
      return {
        Icon: BrainCircuit,
        color: "var(--m-eco2)",
        category: "AI",
        title: "AI 开始分析",
        detail: describeTrigger(str(payload.trigger)),
      };
    case "ai_result": {
      const command = (payload.command ?? {}) as Record<string, unknown>;
      const confidence = num(payload.confidence) ?? 0;
      return {
        Icon: Sparkles,
        color: "var(--m-eco2)",
        category: "AI",
        title: `AI 建议：${commandLabel(str(command.type) || "none")}`,
        detail: `置信度 ${Math.round(confidence * 100)}% · ${payload.published ? "指令已下发" : "仅生成建议"}${str(payload.reason) ? ` · ${str(payload.reason)}` : ""}`,
      };
    }
    case "command": {
      const source = str(payload.source);
      const sourceLabel = source === "llm" ? "AI" : source === "rule" ? "规则" : "手动";
      return {
        Icon: Send,
        color: "var(--accent)",
        category: "控制",
        title: `准备执行：${commandLabel(str(payload.type))}`,
        detail: `${sourceLabel}指令已发送，正在等待设备确认`,
      };
    }
    case "command_ack": {
      const status = str(payload.status);
      const action = commandLabel(str(payload.command_type));
      const suffix = action === "--" ? "指令" : action;
      const view =
        status === "executed"
          ? { Icon: CheckCircle2, color: "var(--good)", title: `已执行：${suffix}` }
          : status === "rejected"
            ? { Icon: XCircle, color: "var(--warn)", title: `设备拒绝：${suffix}` }
            : { Icon: XCircle, color: "var(--alert)", title: `执行失败：${suffix}` };
      return {
        ...view,
        category: "控制",
        detail: readableAckMessage(str(payload.message), status),
      };
    }
    case "autopilot":
      return {
        Icon: Bot,
        color: payload.enabled ? "var(--good)" : "var(--warn)",
        category: "自动控制",
        title: `自动决策已${payload.enabled ? "开启" : "暂停"}`,
        detail: payload.enabled ? "环境变化将自动触发 AI 分析和设备控制" : "仅保留手动分析与手动控制",
      };
    case "event":
      if (str(payload.type) === "smoke.detected" || str(payload.type) === "smoke.cleared") {
        const detected = str(payload.type) === "smoke.detected";
        return {
          Icon: detected ? AlertTriangle : CheckCircle2,
          color: detected ? "var(--alert)" : "var(--good)",
          category: "安全",
          title: detected ? "检测到烟雾" : "烟雾状态已解除",
          detail: str(payload.message),
        };
      }
      return {
        Icon: str(payload.type) === "autopilot" ? Bot : Radio,
        color: "var(--warn)",
        category: str(payload.type) === "autopilot" ? "自动控制" : "设备",
        title: str(payload.type) === "autopilot" ? "自动决策被触发" : "设备报告了新事件",
        detail: str(payload.message),
      };
    case "log":
      return {
        Icon: Terminal,
        color: "var(--ink-3)",
        category: "日志",
        title: "设备运行日志",
        detail: str(payload.message ?? payload.raw),
      };
    case "error":
      return {
        Icon: AlertTriangle,
        color: "var(--alert)",
        category: "系统",
        title: "处理事件时发生异常",
        detail: str(payload.error ?? payload.reason ?? payload.topic),
      };
    default:
      return {
        Icon: Radio,
        color: "var(--ink-3)",
        category: "系统",
        title: "收到新的系统事件",
        detail: `事件类型：${event.type}`,
      };
  }
}

type EventGroup = "environment" | "control" | "intelligence" | "safety";

const GROUPS: Array<{
  key: EventGroup;
  label: string;
  description: string;
  Icon: LucideIcon;
  color: string;
  className: string;
}> = [
  {
    key: "environment",
    label: "环境与设备",
    description: "高频状态",
    Icon: Activity,
    color: "var(--good)",
    className: "col-span-2 min-h-36 xl:min-h-0",
  },
  {
    key: "control",
    label: "控制与自动化",
    description: "指令和回执",
    Icon: Send,
    color: "var(--accent)",
    className: "min-h-32 xl:min-h-0",
  },
  {
    key: "intelligence",
    label: "AI 与视觉",
    description: "分析和识别",
    Icon: BrainCircuit,
    color: "var(--m-eco2)",
    className: "min-h-32 xl:min-h-0",
  },
  {
    key: "safety",
    label: "安全与系统",
    description: "告警和异常",
    Icon: AlertTriangle,
    color: "var(--alert)",
    className: "col-span-2 min-h-24 xl:min-h-0",
  },
];

function eventGroup(event: UiEvent): EventGroup {
  if (event.type === "telemetry" || event.type === "status") return "environment";
  if (event.type === "command" || event.type === "command_ack" || event.type === "autopilot") {
    return "control";
  }
  if (
    event.type === "ai_analyzing" ||
    event.type === "ai_result" ||
    event.type === "image" ||
    event.type === "pose_result"
  ) {
    return "intelligence";
  }
  if (event.type === "event" && str(event.payload.type) === "autopilot") return "control";
  if (event.type === "event" && !str(event.payload.type).startsWith("smoke.")) return "environment";
  return "safety";
}

function CompactEvent({ event }: { event: UiEvent }) {
  const view = describeEvent(event);
  return (
    <article
      className="group flex animate-fade-slide items-start gap-2 rounded-lg border border-transparent px-2 py-1.5 transition-colors hover:border-line hover:bg-surface"
      aria-label={`${view.category}：${view.title}`}
    >
      <span
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md"
        style={{ color: view.color, background: "var(--surface-solid)" }}
        aria-hidden
      >
        <view.Icon size={11} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-1.5">
          <p className="truncate text-xs font-medium leading-5 text-ink" title={view.title}>
            {view.title}
          </p>
          <time className="tnum shrink-0 text-[10px] text-ink3" dateTime={event.occurred_at}>
            {formatClock(event.occurred_at)}
          </time>
        </div>
        {view.detail ? (
          <p className="truncate text-[11px] leading-4 text-ink2" title={view.detail}>
            {view.detail}
          </p>
        ) : null}
      </div>
    </article>
  );
}

export function EventStream({ events, className }: { events: UiEvent[]; className?: string }) {
  const grouped = Object.fromEntries(
    GROUPS.map((group) => [group.key, events.filter((event) => eventGroup(event) === group.key)]),
  ) as Record<EventGroup, UiEvent[]>;

  return (
    <Panel
      title="实时事件流"
      icon={<Radio size={17} />}
      className={cn(
        "flex h-[38rem] min-h-0 max-h-[38rem] flex-col overflow-hidden xl:h-[42rem] xl:max-h-[42rem]",
        className,
      )}
    >
      <div
        className="grid min-h-0 flex-1 grid-cols-2 grid-rows-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,0.72fr)] gap-2.5 overflow-hidden"
        aria-label="按类型划分的设备实时事件"
      >
        {GROUPS.map((group) => {
          const groupEvents = grouped[group.key];
          return (
            <section
              key={group.key}
              className={cn(
                "flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-raised",
                group.className,
              )}
              aria-labelledby={`event-group-${group.key}`}
            >
              <div className="flex items-center justify-between gap-2 border-b border-line px-2.5 py-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="flex size-6 shrink-0 items-center justify-center rounded-md"
                    style={{ color: group.color, background: "var(--surface-solid)" }}
                    aria-hidden
                  >
                    <group.Icon size={12} />
                  </span>
                  <div className="min-w-0">
                    <h3 id={`event-group-${group.key}`} className="truncate text-xs font-semibold text-ink">
                      {group.label}
                    </h3>
                    <p className="text-[10px] text-ink3">{group.description}</p>
                  </div>
                </div>
                <span className="tnum rounded-full bg-surface px-1.5 py-0.5 text-[10px] text-ink3">
                  {groupEvents.length}
                </span>
              </div>
              <div
                className="scroll-thin min-h-0 flex-1 overscroll-contain overflow-y-auto p-1"
                aria-label={`${group.label}事件列表`}
                aria-live="off"
                tabIndex={0}
              >
                {groupEvents.length ? (
                  groupEvents.map((event) => <CompactEvent key={event.id} event={event} />)
                ) : (
                  <p className="flex h-full min-h-10 items-center justify-center px-2 text-center text-[11px] text-ink3">
                    暂无{group.label}事件
                  </p>
                )}
              </div>
            </section>
          );
        })}
      </div>
    </Panel>
  );
}
