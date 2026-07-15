"use client";

import { useState } from "react";
import Link from "next/link";
import { Bot, BrainCircuit, CircleSlash, Send, Sparkles } from "lucide-react";

import { AiTextPreview } from "@/components/ai-markdown";
import { Panel } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { AiRunOut, AutomationPolicyIn, AutomationPolicyOut } from "@/lib/api";
import { commandLabel, describeTrigger, formatDateTime } from "@/lib/utils";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "skipped"]);

function AutomationSwitch({
  enabled,
  onChange,
}: {
  enabled: boolean | null;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="inline-flex min-h-9 items-center gap-2 text-sm font-medium text-ink2">
      <Bot size={14} className={enabled ? "text-accent" : "text-ink3"} />
      自动决策
      <Switch
        checked={enabled === true}
        disabled={enabled === null}
        onCheckedChange={onChange}
        aria-label="自动决策开关"
      />
    </label>
  );
}

function NumberSetting({
  label,
  value,
  disabled,
  max,
  onChange,
}: {
  label: string;
  value: number;
  disabled: boolean;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="text-xs text-ink3">
      {label}
      <input
        key={`${label}-${value}`}
        type="number"
        min={5}
        max={max}
        defaultValue={value}
        disabled={disabled}
        onBlur={(event) => onChange(Number(event.currentTarget.value))}
        className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink"
      />
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
  const commandType = typeof action?.data?.type === "string" ? action.data.type : "";
  const summary = String(output.summary || "分析完成，未生成设备控制动作。");

  return (
    <Panel
      title="AI 决策"
      icon={<BrainCircuit size={17} />}
      className={className}
      actions={<AutomationSwitch enabled={policy?.enabled ?? null} onChange={onToggleAutomation} />}
    >
      <div className="flex min-h-[21rem] flex-col xl:h-[21rem] xl:min-h-0">
        <div
          className="mb-3 grid grid-cols-3 rounded-lg border border-line bg-raised p-1 text-xs"
          role="tablist"
        >
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
              role="tab"
              aria-selected={tab === value}
              onClick={() => setTab(value)}
              className={`rounded-md px-2 py-1.5 ${tab === value ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "history" ? (
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1" role="tabpanel">
            {runs.length ? (
              runs.slice(0, 20).map((item) => {
                const error = item.error_message || item.error_code;
                return (
                  <div key={item.run_id} className="rounded-lg border border-line bg-raised p-3 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-ink">
                        {item.kind} · {item.trigger}
                      </span>
                      <Badge variant={item.status === "failed" ? "destructive" : "outline"}>
                        {item.status}
                      </Badge>
                    </div>
                    {error ? (
                      <AiTextPreview
                        content={error}
                        title={`AI 任务错误 · ${item.run_id}`}
                        description={`${item.error_code || "failed"} · ${formatDateTime(item.completed_at)}`}
                        className="mt-2"
                      />
                    ) : null}
                    <div className="mt-1 flex items-center justify-between gap-2 text-ink3">
                      <span>{formatDateTime(item.created_at)}</span>
                      {!TERMINAL.has(item.status) ? (
                        <button type="button" className="text-alert" onClick={() => onCancelRun(item.run_id)}>
                          取消
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="py-8 text-center text-sm text-ink3">暂无 AI 任务</p>
            )}
          </div>
        ) : null}

        {tab === "recent" ? (
          <div className="flex min-h-0 flex-1 flex-col" role="tabpanel">
            {analyzing ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                <BrainCircuit size={34} className="animate-pulse-soft text-accent" />
                <p className="text-sm font-semibold text-ink">AI 正在分析</p>
                <p className="text-sm text-ink2">{describeTrigger(analyzing)}</p>
              </div>
            ) : run?.status === "failed" ? (
              <div className="min-h-0 flex-1 overflow-y-auto">
                <Badge variant="destructive">分析失败</Badge>
                <AiTextPreview
                  content={run.error_message || run.error_code || "模型任务执行失败，未返回详细原因。"}
                  title="AI 决策失败详情"
                  className="mt-3"
                />
              </div>
            ) : run ? (
              <div className="flex min-h-0 flex-1 flex-col gap-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="flex size-9 items-center justify-center rounded-xl bg-accent/10 text-accent">
                      {commandType ? <Sparkles size={18} /> : <CircleSlash size={18} />}
                    </span>
                    <div>
                      <p className="font-semibold text-ink">
                        {commandType ? commandLabel(commandType) : "无需设备动作"}
                      </p>
                      <p className="text-xs text-ink3">{describeTrigger(run.trigger) || "最近一次决策"}</p>
                    </div>
                  </div>
                  <Badge variant="outline">{commandType ? "已提交命令" : "分析完成"}</Badge>
                </div>
                <AiTextPreview content={summary} title="完整 AI 决策分析" className="min-h-0 flex-1" />
                <p className="text-xs text-ink3">
                  {formatDateTime(run.completed_at ?? run.created_at)} ·{" "}
                  <Link className="text-accent hover:underline" href={`/diagnostics?trace=${run.trace_id}`}>
                    trace {run.trace_id}
                  </Link>
                </p>
              </div>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center text-ink3">
                <Sparkles size={26} />
                <p className="text-sm">暂无决策记录，可立即发起分析</p>
              </div>
            )}
            <Button type="button" onClick={onAnalyze} disabled={Boolean(analyzing)} className="mt-3 w-full">
              <Send /> {analyzing ? "分析中…" : "立即 AI 分析"}
            </Button>
          </div>
        ) : null}

        {tab === "policy" ? (
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1" role="tabpanel">
            <div className="rounded-xl border border-line bg-raised p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-ink">变化后周期巡检</p>
                  <p className="text-xs text-ink3">无有效变化时跳过模型调用</p>
                </div>
                <Switch
                  checked={policy?.patrol_enabled ?? false}
                  disabled={!policy}
                  onCheckedChange={(value) => onUpdatePolicy({ patrol_enabled: value })}
                />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <NumberSetting
                  label="巡检周期（秒）"
                  value={policy?.patrol_interval_seconds ?? 300}
                  disabled={!policy}
                  max={86400}
                  onChange={(value) => onUpdatePolicy({ patrol_interval_seconds: value })}
                />
                <NumberSetting
                  label="强制分析（秒）"
                  value={policy?.patrol_force_interval_seconds ?? 3600}
                  disabled={!policy}
                  max={604800}
                  onChange={(value) => onUpdatePolicy({ patrol_force_interval_seconds: value })}
                />
              </div>
            </div>
            <div className="rounded-xl border border-line bg-raised p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-ink">AI 计划策略复盘</p>
                  <p className="text-xs text-ink3">只生成待批准候选</p>
                </div>
                <Switch
                  checked={policy?.strategy_enabled ?? false}
                  disabled={!policy}
                  onCheckedChange={(value) => onUpdatePolicy({ strategy_enabled: value })}
                />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <NumberSetting
                  label="合并窗口（秒）"
                  value={policy?.strategy_min_interval_seconds ?? 300}
                  disabled={!policy}
                  max={86400}
                  onChange={(value) => onUpdatePolicy({ strategy_min_interval_seconds: value })}
                />
                <NumberSetting
                  label="强制复盘（秒）"
                  value={policy?.strategy_force_interval_seconds ?? 3600}
                  disabled={!policy}
                  max={604800}
                  onChange={(value) => onUpdatePolicy({ strategy_force_interval_seconds: value })}
                />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
