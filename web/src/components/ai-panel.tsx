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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { AiDecisionPayload, LatestState } from "@/lib/api";
import { commandLabel, describeTrigger, formatDateTime } from "@/lib/utils";

const COMMAND_ICONS: Record<string, typeof DoorOpen> = {
  "window.open": DoorOpen,
  "window.close": DoorClosed,
  "alarm.on": BellRing,
  "alarm.off": BellOff,
  "led.on": Sparkles,
  "led.off": CircleSlash,
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
    <label className="inline-flex min-h-9 items-center gap-2 text-sm font-medium text-ink2">
      <Bot size={14} className={on ? "text-accent" : "text-ink3"} />
      自动决策
      <Switch checked={on} disabled={enabled === null} onCheckedChange={onChange} aria-label="自动决策开关" />
    </label>
  );
}

export function AiPanel({
  analyzing,
  decision,
  autopilot,
  onToggleAutopilot,
  onAnalyze,
  className,
}: {
  analyzing: string | null;
  decision: AiDecisionPayload | null;
  autopilot: LatestState["autopilot"];
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
      actions={<AutopilotSwitch enabled={autopilot?.enabled ?? null} onChange={onToggleAutopilot} />}
    >
      <div className="flex min-h-[15.5rem] flex-col">
        {analyzing ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 py-6 text-center">
            <BrainCircuit size={34} className="animate-pulse-soft text-accent" />
            <div>
              <p className="text-sm font-semibold text-ink">AI 正在分析</p>
              <p className="mt-1 text-sm text-ink2">{describeTrigger(analyzing)}</p>
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
                  <p className="text-sm text-ink2">{describeTrigger(decision.trigger) || "最近一次决策"}</p>
                </div>
              </div>
              <Badge
                variant="outline"
                className="rounded-full border-line px-2.5 py-1 text-xs font-medium"
                style={
                  decision.published
                    ? { color: "var(--good)", background: "var(--good-soft)" }
                    : { color: "var(--ink-3)", background: "var(--raised)" }
                }
              >
                {decision.published ? "已下发" : "仅建议"}
              </Badge>
            </div>

            <div className="flex items-center justify-between gap-2 text-sm">
              <Badge
                variant="outline"
                className="gap-1.5 rounded-full border-line px-2 py-0.5 font-medium text-ink2"
                style={{ background: risk.soft }}
              >
                <risk.Icon size={13} style={{ color: risk.color }} />
                {risk.label}
              </Badge>
              {decision.scene_summary ? <span className="text-ink3">{decision.scene_summary}</span> : null}
            </div>

            <div>
              <div className="flex items-center justify-between text-sm text-ink2">
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

            <p className="flex-1 rounded-xl border border-line bg-raised px-3.5 py-3 text-sm leading-relaxed text-ink2">
              {decision.reason || "（模型未给出理由）"}
            </p>
            {decision.speech ? (
              <p className="rounded-xl border border-accent/30 bg-accent/5 px-3.5 py-2.5 text-sm text-ink2">
                语音建议：{decision.speech}
              </p>
            ) : null}

            <p className="text-xs text-ink3">{formatDateTime(decision.command?.created_at)}</p>
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center text-ink3">
            <Sparkles size={26} />
            <p className="max-w-64 text-sm leading-relaxed">暂无决策记录，可立即发起分析</p>
          </div>
        )}

        <Button
          type="button"
          onClick={onAnalyze}
          disabled={Boolean(analyzing)}
          className="mt-4 min-h-11 w-full gap-2 rounded-xl px-4 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: "linear-gradient(135deg, var(--accent), var(--accent-strong))" }}
        >
          <Send size={15} />
          {analyzing ? "分析中…" : "立即 AI 分析"}
        </Button>
      </div>
    </Panel>
  );
}
