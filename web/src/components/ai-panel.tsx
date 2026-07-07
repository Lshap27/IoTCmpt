"use client";

import {
  BellOff,
  BellRing,
  Bot,
  BrainCircuit,
  CircleSlash,
  DoorClosed,
  DoorOpen,
  MessageSquare,
  Send,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
} from "lucide-react";
import { Panel } from "@/components/panel";
import type { AiDecisionPayload } from "@/lib/api";
import { cn, commandLabel, describeTrigger, formatDateTime } from "@/lib/utils";

const COMMAND_ICONS: Record<string, typeof DoorOpen> = {
  "window.open": DoorOpen,
  "window.close": DoorClosed,
  "alarm.on": BellRing,
  "alarm.off": BellOff,
  "display.message": MessageSquare,
  none: CircleSlash,
};

const RISK: Record<string, { label: string; color: string; soft: string; Icon: typeof ShieldCheck }> = {
  low: { label: "低风险", color: "var(--good)", soft: "var(--good-soft)", Icon: ShieldCheck },
  medium: { label: "中风险", color: "var(--warn)", soft: "var(--warn-soft)", Icon: ShieldAlert },
  high: { label: "高风险", color: "var(--alert)", soft: "var(--alert-soft)", Icon: ShieldAlert },
  unknown: { label: "风险未知", color: "var(--ink-3)", soft: "transparent", Icon: ShieldQuestion },
};

function AutopilotSwitch({
  enabled,
  onChange,
}: {
  enabled: boolean | null;
  onChange: (enabled: boolean) => void;
}) {
  const on = enabled === true;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label="自动决策开关"
      disabled={enabled === null}
      onClick={() => onChange(!on)}
      className="inline-flex items-center gap-2 text-xs font-medium text-ink2 disabled:opacity-50"
    >
      <Bot size={14} className={on ? "text-accent" : "text-ink3"} />
      自动决策
      <span
        className={cn(
          "relative h-5 w-9 rounded-full border transition-colors",
          on ? "border-accent" : "border-line bg-raised",
        )}
        style={on ? { background: "var(--accent-soft)" } : undefined}
      >
        <span
          className={cn(
            "absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all",
            on ? "left-[18px]" : "left-0.5",
          )}
          style={{ background: on ? "var(--accent)" : "var(--ink-3)" }}
        />
      </span>
    </button>
  );
}

export function AiPanel({
  analyzing,
  decision,
  autopilotEnabled,
  onToggleAutopilot,
  onAnalyze,
  className,
}: {
  analyzing: string | null;
  decision: AiDecisionPayload | null;
  autopilotEnabled: boolean | null;
  onToggleAutopilot: (enabled: boolean) => void;
  onAnalyze: () => void;
  className?: string;
}) {
  const risk = decision ? (RISK[decision.risk_level] ?? RISK.unknown) : RISK.unknown;
  const CommandIcon = decision ? (COMMAND_ICONS[decision.command?.type] ?? CircleSlash) : CircleSlash;
  const confidencePercent = decision ? Math.round((decision.confidence ?? 0) * 100) : 0;

  return (
    <Panel
      title="AI 决策"
      icon={<BrainCircuit size={17} />}
      className={className}
      actions={<AutopilotSwitch enabled={autopilotEnabled} onChange={onToggleAutopilot} />}
    >
      <div className="flex min-h-[15.5rem] flex-col">
        {analyzing ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 py-6 text-center">
            <BrainCircuit size={34} className="animate-pulse-soft text-accent" />
            <div>
              <p className="text-sm font-semibold text-ink">AI 正在分析</p>
              <p className="mt-1 text-xs text-ink3">{describeTrigger(analyzing)}</p>
            </div>
            <div className="shimmer-bar h-1.5 w-40 animate-shimmer rounded-full" />
          </div>
        ) : decision ? (
          <div className="flex flex-1 flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span
                  className="flex h-10 w-10 items-center justify-center rounded-xl text-accent"
                  style={{ background: "var(--accent-soft)" }}
                >
                  <CommandIcon size={20} />
                </span>
                <div>
                  <p className="text-base font-semibold text-ink">{commandLabel(decision.command?.type)}</p>
                  <p className="text-xs text-ink3">{describeTrigger(decision.trigger) || "最近一次决策"}</p>
                </div>
              </div>
              <span
                className="rounded-full border border-line px-2 py-0.5 text-[11px] font-medium"
                style={
                  decision.published
                    ? { color: "var(--good)", background: "var(--good-soft)" }
                    : { color: "var(--ink-3)", background: "var(--raised)" }
                }
              >
                {decision.published ? "已下发" : "仅建议"}
              </span>
            </div>

            <div className="flex items-center justify-between gap-2 text-xs">
              <span
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 font-medium text-ink2"
                style={{ background: risk.soft }}
              >
                <risk.Icon size={13} style={{ color: risk.color }} />
                {risk.label}
              </span>
              {decision.image_attached ? <span className="text-ink3">已结合摄像头画面</span> : null}
            </div>

            <div>
              <div className="flex items-center justify-between text-xs text-ink3">
                <span>置信度</span>
                <span className="tnum font-medium text-ink2">{confidencePercent}%</span>
              </div>
              <div
                className="mt-1 h-1.5 overflow-hidden rounded-full"
                style={{ background: "var(--accent-soft)" }}
              >
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${confidencePercent}%`, background: "var(--accent)" }}
                />
              </div>
            </div>

            <p className="flex-1 rounded-lg border border-line bg-raised px-3 py-2 text-xs leading-relaxed text-ink2">
              {decision.reason || "（模型未给出理由）"}
            </p>

            <p className="text-[11px] text-ink3">
              模型 {decision.model || "--"} · {formatDateTime(decision.command?.created_at)}
            </p>
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center text-ink3">
            <Sparkles size={26} />
            <p className="text-xs">暂无决策记录：等待自动触发，或立即发起一次分析</p>
          </div>
        )}

        <button
          type="button"
          onClick={onAnalyze}
          disabled={Boolean(analyzing)}
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-white transition-all hover:opacity-90 disabled:opacity-50"
          style={{ background: "linear-gradient(135deg, var(--accent), var(--m-eco2))" }}
        >
          <Send size={15} />
          {analyzing ? "分析中…" : "立即 AI 分析"}
        </button>
      </div>
    </Panel>
  );
}
