"use client";

import { useState } from "react";
import Link from "next/link";
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
import type { AiRunOut, AutomationPolicyIn, AutomationPolicyOut } from "@/lib/api";
import { commandLabel, describeTrigger, formatDateTime } from "@/lib/utils";

const COMMAND_ICONS: Record<string, typeof DoorOpen> = {
  "window.open": DoorOpen,
  "window.close": DoorClosed,
  "alarm.on": BellRing,
  "alarm.off": BellOff,
  "led.on": Sparkles,
  "led.off": CircleSlash,
  "display.message": MessageSquare,
};

const RISK: Record<string, { label: string; color: string; soft: string; Icon: typeof ShieldCheck }> = {
  low: { label: "低风险", color: "var(--good)", soft: "var(--good-soft)", Icon: ShieldCheck },
  medium: { label: "中风险", color: "var(--warn)", soft: "var(--warn-soft)", Icon: ShieldAlert },
  high: { label: "高风险", color: "var(--alert)", soft: "var(--alert-soft)", Icon: ShieldAlert },
  unknown: { label: "风险未知", color: "var(--ink-3)", soft: "transparent", Icon: ShieldQuestion },
};

function AutomationSwitch({
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
  run,
  runs,
  policy,
  onToggleAutomation,
  onUpdatePolicy,
  onAnalyze,
  onCancelRun,
  className,
}: {
  analyzing: string | null;
  run: AiRunOut | null;
  runs: AiRunOut[];
  policy: AutomationPolicyOut | null;
  onToggleAutomation: (enabled: boolean) => void;
  onUpdatePolicy: (values: AutomationPolicyIn) => void;
  onAnalyze: () => void;
  onCancelRun: (runId: string) => void;
  className?: string;
}) {
  const [tab, setTab] = useState<"recent" | "history" | "policy">("recent");
  const output = (run?.output ?? {}) as Record<string, unknown>;
  const action = (output.action ?? null) as { data?: Record<string, unknown> } | null;
  const command = action?.data ?? null;
  const commandType = typeof command?.type === "string" ? command.type : "";
  const riskLevel = typeof output.risk_level === "string" ? output.risk_level : "unknown";
  const risk = RISK[riskLevel] ?? RISK.unknown;
  const CommandIcon = COMMAND_ICONS[commandType] ?? CircleSlash;

  return (
    <Panel
      title="AI 决策"
      icon={<BrainCircuit size={17} />}
      className={className}
      actions={<AutomationSwitch enabled={policy?.enabled ?? null} onChange={onToggleAutomation} />}
    >
      <div className="flex min-h-[15.5rem] flex-col">
        <div className="mb-4 grid grid-cols-3 rounded-lg border border-line bg-raised p-1 text-xs">
          {(
            [
              ["recent", "最近任务"],
              ["history", "任务历史"],
              ["policy", "自动化策略"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setTab(value)}
              className={`rounded-md px-2 py-1.5 ${tab === value ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "history" ? (
          <div className="space-y-2">
            {runs.length ? (
              runs.slice(0, 20).map((item) => (
                <div key={item.run_id} className="rounded-lg border border-line bg-raised p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-ink">
                      {item.kind} · {item.trigger}
                    </span>
                    <span className="text-ink3">{item.status}</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-ink3">
                    <span>{formatDateTime(item.created_at)}</span>
                    {!["succeeded", "failed", "cancelled", "skipped"].includes(item.status) ? (
                      <button type="button" className="text-alert" onClick={() => onCancelRun(item.run_id)}>
                        取消
                      </button>
                    ) : null}
                  </div>
                </div>
              ))
            ) : (
              <p className="py-8 text-center text-sm text-ink3">暂无 AI 任务</p>
            )}
          </div>
        ) : null}
        <div className={tab === "history" ? "hidden" : "contents"}>
          {analyzing ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 py-6 text-center">
              <BrainCircuit size={34} className="animate-pulse-soft text-accent" />
              <div>
                <p className="text-sm font-semibold text-ink">AI 正在分析</p>
                <p className="mt-1 text-sm text-ink2">{describeTrigger(analyzing)}</p>
              </div>
              <div className="shimmer-bar h-1.5 w-40 animate-shimmer rounded-full" />
            </div>
          ) : run ? (
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
                    <p className="text-base font-semibold text-ink">
                      {commandType ? commandLabel(commandType) : "无需设备动作"}
                    </p>
                    <p className="text-sm text-ink2">{describeTrigger(run.trigger) || "最近一次决策"}</p>
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className="rounded-full border-line px-2.5 py-1 text-xs font-medium"
                  style={
                    command
                      ? { color: "var(--good)", background: "var(--good-soft)" }
                      : { color: "var(--ink-3)", background: "var(--raised)" }
                  }
                >
                  {command ? "已提交命令" : "分析完成"}
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
                <span className="text-ink3">{run.model || String(output.model || "")}</span>
              </div>

              <p className="flex-1 rounded-xl border border-line bg-raised px-3.5 py-3 text-sm leading-relaxed text-ink2">
                {String(output.summary || "分析完成，未生成设备控制动作。")}
              </p>
              <p className="text-xs text-ink3">
                {formatDateTime(run.completed_at ?? run.created_at)} ·{" "}
                <Link className="text-accent hover:underline" href={`/diagnostics?trace=${run.trace_id}`}>
                  trace {run.trace_id}
                </Link>
              </p>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center text-ink3">
              <Sparkles size={26} />
              <p className="max-w-64 text-sm leading-relaxed">暂无决策记录，可立即发起分析</p>
            </div>
          )}

          <div className="mt-4 rounded-xl border border-line bg-raised p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-ink">变化后周期巡检</p>
                <p className="mt-0.5 text-xs text-ink3">无有效变化时跳过模型调用</p>
              </div>
              <Switch
                checked={policy?.patrol_enabled ?? false}
                disabled={!policy}
                onCheckedChange={(patrol_enabled) => onUpdatePolicy({ patrol_enabled })}
                aria-label="周期巡检开关"
              />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <label className="text-xs text-ink3">
                巡检周期（秒）
                <input
                  key={`patrol-${policy?.patrol_interval_seconds}`}
                  type="number"
                  min={5}
                  max={86400}
                  defaultValue={policy?.patrol_interval_seconds ?? 300}
                  disabled={!policy}
                  onBlur={(event) =>
                    onUpdatePolicy({ patrol_interval_seconds: Number(event.currentTarget.value) })
                  }
                  className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink"
                />
              </label>
              <label className="text-xs text-ink3">
                强制分析（秒）
                <input
                  key={`force-${policy?.patrol_force_interval_seconds}`}
                  type="number"
                  min={5}
                  max={604800}
                  defaultValue={policy?.patrol_force_interval_seconds ?? 3600}
                  disabled={!policy}
                  onBlur={(event) =>
                    onUpdatePolicy({ patrol_force_interval_seconds: Number(event.currentTarget.value) })
                  }
                  className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink"
                />
              </label>
            </div>
          </div>

          <div className="mt-3 rounded-xl border border-line bg-raised p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-ink">AI 计划策略复盘</p>
                <p className="mt-0.5 text-xs text-ink3">只生成待批准候选，不自动替换计划</p>
              </div>
              <Switch
                checked={policy?.strategy_enabled ?? false}
                disabled={!policy}
                onCheckedChange={(strategy_enabled) => onUpdatePolicy({ strategy_enabled })}
                aria-label="AI 计划策略复盘开关"
              />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <label className="text-xs text-ink3">
                合并窗口（秒）
                <input
                  key={`strategy-min-${policy?.strategy_min_interval_seconds}`}
                  type="number"
                  min={5}
                  max={86400}
                  defaultValue={policy?.strategy_min_interval_seconds ?? 300}
                  disabled={!policy}
                  onBlur={(event) =>
                    onUpdatePolicy({ strategy_min_interval_seconds: Number(event.currentTarget.value) })
                  }
                  className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink"
                />
              </label>
              <label className="text-xs text-ink3">
                强制复盘（秒）
                <input
                  key={`strategy-force-${policy?.strategy_force_interval_seconds}`}
                  type="number"
                  min={5}
                  max={604800}
                  defaultValue={policy?.strategy_force_interval_seconds ?? 3600}
                  disabled={!policy}
                  onBlur={(event) =>
                    onUpdatePolicy({ strategy_force_interval_seconds: Number(event.currentTarget.value) })
                  }
                  className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink"
                />
              </label>
            </div>
          </div>

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
      </div>
    </Panel>
  );
}
