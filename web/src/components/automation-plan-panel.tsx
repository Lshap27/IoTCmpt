"use client";

import { useMemo, useState } from "react";
import { Bot, Check, Clock3, Pause, Play, RefreshCw, Send, Sparkles, Square, X } from "lucide-react";
import { Panel } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAutomationPlans } from "@/hooks/use-automation-plans";
import type { AiStrategyOut, AutomationPlanOut } from "@/lib/api";

const STATUS: Record<string, string> = {
  draft: "草案",
  active: "运行中",
  paused: "已暂停",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
  superseded: "已被替换",
  proposed: "待批准",
  approved: "已批准",
  rejected: "已拒绝",
  skipped: "无变化",
};

const COMMAND: Record<string, string> = {
  "window.open": "打开窗户",
  "window.close": "关闭窗户",
  "led.on": "打开照明",
  "led.off": "关闭照明",
  "voice.speak": "语音提醒",
  "display.message": "屏幕消息",
};

function specOf(plan: AutomationPlanOut) {
  return plan.spec as {
    duration_seconds?: number;
    timezone?: string;
    manual_override_policy?: string;
    end_behavior?: string;
    rules?: Array<{
      id: string;
      description: string;
      trigger: { type: string; every_seconds?: number; stability_samples?: number };
      action: { command: string; text?: string };
      cooldown_seconds?: number;
    }>;
  };
}

function remaining(endsAt?: string | null) {
  if (!endsAt) return "—";
  const seconds = Math.max(0, Math.floor((new Date(endsAt).getTime() - Date.now()) / 1000));
  const minutes = Math.ceil(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟` : `${minutes} 分钟`;
}

function PlanSummary({ plan }: { plan: AutomationPlanOut }) {
  const spec = specOf(plan);
  const nextFire = plan.rule_states
    .map((state) => state.next_fire_at)
    .filter((value): value is string => Boolean(value))
    .sort()[0];
  const lastFire = plan.rule_states
    .map((state) => state.last_fired_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
  const blocked = plan.rule_states.find((state) => state.blocked_reason);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-ink">{plan.title}</span>
        <Badge variant={plan.status === "active" ? "default" : "outline"}>{STATUS[plan.status]}</Badge>
        <span className="text-xs text-ink3">v{plan.current_version}</span>
      </div>
      <div className="grid gap-2 text-sm sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border border-line bg-surface/60 p-3">
          <div className="text-xs text-ink3">持续时间</div>
          <div className="mt-1 font-medium text-ink">
            {Math.round((spec.duration_seconds ?? 0) / 60)} 分钟
          </div>
        </div>
        <div className="rounded-lg border border-line bg-surface/60 p-3">
          <div className="text-xs text-ink3">剩余时间</div>
          <div className="mt-1 font-medium text-ink">{remaining(plan.ends_at)}</div>
        </div>
        <div className="rounded-lg border border-line bg-surface/60 p-3">
          <div className="text-xs text-ink3">下一次提醒</div>
          <div className="mt-1 font-medium text-ink">
            {nextFire ? new Date(nextFire).toLocaleString() : "—"}
          </div>
        </div>
        <div className="rounded-lg border border-line bg-surface/60 p-3">
          <div className="text-xs text-ink3">最近执行</div>
          <div className="mt-1 font-medium text-ink">
            {lastFire ? new Date(lastFire).toLocaleString() : "尚未执行"}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink3">
        <span>尊重手动操作 · 会话结束保持设备状态</span>
        {blocked ? <Badge variant="outline">{blocked.blocked_reason} · 已阻止重复发送</Badge> : null}
      </div>
      <ul className="space-y-2" aria-label="计划规则">
        {(spec.rules ?? []).map((rule) => (
          <li key={rule.id} className="rounded-lg border border-line px-3 py-2.5 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-ink">{rule.description}</span>
              <Badge variant="secondary">{COMMAND[rule.action.command] ?? rule.action.command}</Badge>
            </div>
            <div className="mt-1 text-xs leading-5 text-ink3">
              {rule.trigger.type === "interval"
                ? `每 ${Math.round((rule.trigger.every_seconds ?? 0) / 60)} 分钟触发`
                : `连续 ${rule.trigger.stability_samples ?? 1} 个稳定样本后触发`}
              {rule.cooldown_seconds ? ` · 冷却 ${rule.cooldown_seconds} 秒` : ""}
              {rule.action.text ? ` · “${rule.action.text}”` : ""}
            </div>
          </li>
        ))}
      </ul>
      {plan.activation_blockers.length ? (
        <div className="rounded-lg border border-[var(--warn)] bg-[var(--warn-soft)] px-3 py-2 text-sm text-ink2">
          暂未自动激活：{plan.activation_blockers.join("；")}
        </div>
      ) : null}
    </div>
  );
}

function StrategyCard({
  strategy,
  onResolve,
  busy,
}: {
  strategy: AiStrategyOut;
  onResolve: (action: "approve" | "reject") => void;
  busy: boolean;
}) {
  return (
    <article className="rounded-xl border border-line p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium text-ink">{strategy.summary || "AI 策略建议"}</div>
          <div className="mt-1 text-xs text-ink3">
            基础版本 {strategy.base_version ? `v${strategy.base_version}` : "新计划"} · {strategy.diff.length}{" "}
            项变化
          </div>
        </div>
        <Badge variant={strategy.status === "proposed" ? "default" : "outline"}>
          {STATUS[strategy.status] ?? strategy.status}
        </Badge>
      </div>
      {strategy.diff.length ? (
        <ul className="mt-3 max-h-36 space-y-1 overflow-auto rounded-lg bg-surface/70 p-2 text-xs text-ink2">
          {strategy.diff.slice(0, 12).map((item, index) => (
            <li key={`${String(item.path)}-${index}`} className="font-mono">
              {String(item.path)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-ink3">服务器比较后确认与当前版本没有差异。</p>
      )}
      {strategy.status === "proposed" ? (
        <div className="mt-3 flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => onResolve("approve")}>
            <Check />
            批准
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onResolve("reject")}>
            <X />
            拒绝
          </Button>
        </div>
      ) : null}
    </article>
  );
}

export function AutomationPlanPanel({ deviceId, className }: { deviceId: string; className?: string }) {
  const automation = useAutomationPlans(deviceId);
  const [goal, setGoal] = useState(
    "我要学习 90 分钟。光线暗就开灯，空气不好就通风，每 30 分钟提醒我起来活动，但不要覆盖我的手动操作。",
  );
  const selected = automation.selectedPlan;
  const latestEvent = automation.events[0];
  const canSubmit = goal.trim().length > 0 && !automation.compiling;
  const draftNotice = useMemo(
    () => automation.plans.find((plan) => plan.status === "draft" && plan.plan_id !== selected?.plan_id),
    [automation.plans, selected?.plan_id],
  );

  return (
    <>
      <Panel title="AI 自动化计划" icon={<Bot size={18} />} className={className}>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmit) automation.compile(goal.trim());
          }}
        >
          <label htmlFor="automation-goal" className="text-sm font-medium text-ink2">
            用自然语言描述目标、持续时间、条件和提醒
          </label>
          <textarea
            id="automation-goal"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            maxLength={1000}
            rows={4}
            className="w-full resize-y rounded-xl border border-line bg-surface/70 px-3 py-2.5 text-sm leading-6 text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={!canSubmit}>
              {automation.compiling ? <RefreshCw className="animate-spin" /> : <Send />}
              {automation.compiling ? "正在编译并校验" : "编译安全计划"}
            </Button>
            {automation.compileRun?.status === "succeeded" ? (
              <span className="text-sm text-[var(--good)]">已完成编译，安全范围满足时会自动生效</span>
            ) : null}
          </div>
        </form>

        <div className="my-5 h-px bg-line" />
        {selected ? (
          <>
            <PlanSummary plan={selected} />
            <div className="mt-4 flex flex-wrap gap-2">
              {selected.status === "active" ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={automation.busy}
                  onClick={() => automation.transition(selected.plan_id, "pause")}
                >
                  <Pause />
                  暂停
                </Button>
              ) : null}
              {selected.status === "paused" ? (
                <Button
                  size="sm"
                  disabled={automation.busy}
                  onClick={() => automation.transition(selected.plan_id, "resume")}
                >
                  <Play />
                  恢复
                </Button>
              ) : null}
              {selected.status === "draft" ? (
                <Button
                  size="sm"
                  disabled={automation.busy}
                  onClick={() => automation.transition(selected.plan_id, "activate")}
                >
                  <Play />
                  重新校验并激活
                </Button>
              ) : null}
              {(["draft", "active", "paused"] as string[]).includes(selected.status) ? (
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={automation.busy}
                  onClick={() => automation.transition(selected.plan_id, "cancel")}
                >
                  <Square />
                  取消计划
                </Button>
              ) : null}
            </div>
            <div className="mt-3 rounded-lg bg-surface/60 px-3 py-2 text-xs text-ink3">
              <Clock3 className="mr-1 inline size-3.5" />
              最近事件：
              {latestEvent
                ? `${latestEvent.event_type} · ${new Date(latestEvent.occurred_at).toLocaleString()}`
                : "暂无"}
            </div>
          </>
        ) : (
          <p className="text-sm text-ink3">还没有用户计划。系统默认计划仍会按自动化总开关独立运行。</p>
        )}
        {draftNotice ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm text-ink2">
            <span>新草案“{draftNotice.title}”已保留为替换预览，不会中断当前计划。</span>
            <Button
              size="sm"
              variant="outline"
              disabled={automation.busy}
              onClick={() => automation.transition(draftNotice.plan_id, "activate", true)}
            >
              确认替换
            </Button>
          </div>
        ) : null}
        {automation.error ? (
          <p role="alert" className="mt-3 text-sm text-[var(--alert)]">
            {automation.error}
          </p>
        ) : null}
      </Panel>

      <Panel
        title="AI 策略"
        icon={<Sparkles size={18} />}
        className={className}
        actions={
          <Button
            size="sm"
            variant="outline"
            disabled={automation.generatingStrategy}
            onClick={() => automation.generateStrategy(selected?.plan_id)}
          >
            <RefreshCw className={automation.generatingStrategy ? "animate-spin" : ""} />
            立即复盘
          </Button>
        }
      >
        <p className="mb-4 text-sm leading-6 text-ink3">
          策略只生成候选版本，永远不会自动替换活动计划。批准时服务器会重新校验能力、安全约束和基础版本。
        </p>
        <div className="space-y-3">
          {automation.strategies.length ? (
            automation.strategies
              .slice(0, 5)
              .map((strategy) => (
                <StrategyCard
                  key={strategy.strategy_id}
                  strategy={strategy}
                  busy={automation.busy}
                  onResolve={(action) => automation.resolveStrategy(strategy.strategy_id, action)}
                />
              ))
          ) : (
            <p className="text-sm text-ink3">
              尚无策略建议。开启策略开关后，显著变化和每小时复盘会自动生成候选。
            </p>
          )}
        </div>
      </Panel>
    </>
  );
}
