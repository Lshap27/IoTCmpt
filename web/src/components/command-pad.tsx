"use client";

import { useEffect, useState } from "react";
import {
  BellOff,
  BellRing,
  DoorClosed,
  DoorOpen,
  Lightbulb,
  LightbulbOff,
  Loader2,
  Check,
  LockKeyholeOpen,
  SlidersHorizontal,
} from "lucide-react";
import { Panel } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const COMMANDS: { type: string; label: string; Icon: typeof DoorOpen }[] = [
  { type: "window.open", label: "开窗", Icon: DoorOpen },
  { type: "window.close", label: "关窗", Icon: DoorClosed },
  { type: "alarm.on", label: "报警开", Icon: BellRing },
  { type: "alarm.off", label: "报警关", Icon: BellOff },
  { type: "led.on", label: "LED 开", Icon: Lightbulb },
  { type: "led.off", label: "LED 关", Icon: LightbulbOff },
];

function StateChip({ label, active }: { label: string; active: boolean | null | undefined }) {
  return (
    <Badge
      variant="outline"
      className="gap-1.5 rounded-full border-line bg-raised px-2.5 py-1 text-xs text-ink2"
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: active ? "var(--accent)" : "var(--ink-3)" }}
        aria-hidden
      />
      {label}
      {active === null || active === undefined ? " --" : active ? " 开" : " 关"}
    </Badge>
  );
}

export function CommandPad({
  onCommand,
  pendingCommands,
  windowOpen,
  alarmOn,
  ledOn,
  controlPriority,
  manualWindowOverride,
  manualLedOverride,
  availableCommands,
  className,
}: {
  onCommand: (type: string, parameter?: Record<string, unknown>) => void;
  pendingCommands: Record<string, string>;
  windowOpen: boolean | null | undefined;
  alarmOn: boolean | null | undefined;
  ledOn: boolean | null | undefined;
  controlPriority: "manual_first" | "auto_first" | null | undefined;
  manualWindowOverride: boolean | null | undefined;
  manualLedOverride: boolean | null | undefined;
  availableCommands?: string[];
  className?: string;
}) {
  const pendingTypes = new Set(Object.values(pendingCommands));
  const supported = availableCommands ? new Set(availableCommands) : null;
  const priorityPending = pendingTypes.has("control.set_priority");
  const resumePending = pendingTypes.has("control.resume_auto");
  const [pendingPriority, setPendingPriority] = useState<"manual_first" | "auto_first" | null>(null);
  const hasManualLock = Boolean(
    controlPriority === "manual_first" && (manualWindowOverride || manualLedOverride),
  );

  useEffect(() => {
    if (!priorityPending) setPendingPriority(null);
  }, [priorityPending]);

  return (
    <Panel
      title="设备指令"
      icon={<SlidersHorizontal size={17} />}
      className={className}
      actions={
        <div className="flex gap-1.5">
          <StateChip label="窗户" active={windowOpen} />
          <StateChip label="报警" active={alarmOn} />
          <StateChip label="LED" active={ledOn} />
        </div>
      }
    >
      <div className="mb-3 rounded-xl border border-line bg-raised p-3">
        <div>
          <p className="text-sm font-medium text-ink">控制优先级</p>
          <p className="mt-0.5 text-xs leading-relaxed text-ink3">
            手动优先会保留人工操作；自动优先允许环境策略覆盖人工状态。
          </p>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2" role="radiogroup" aria-label="控制优先级">
          {(
            [
              ["manual_first", "手动优先"],
              ["auto_first", "自动优先"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={controlPriority === value}
              disabled={
                priorityPending ||
                controlPriority === value ||
                supported?.has("control.set_priority") === false
              }
              onClick={() => {
                setPendingPriority(value);
                onCommand("control.set_priority", { priority: value });
              }}
              className={`flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-medium transition-all ${
                controlPriority === value
                  ? "border-accent bg-accent text-white shadow-sm"
                  : pendingPriority === value
                    ? "border-accent/60 bg-accent/10 text-accent"
                    : "border-line bg-surface text-ink2 hover:border-accent/60 hover:text-ink"
              }`}
            >
              {pendingPriority === value && priorityPending ? (
                <Loader2 size={15} className="animate-spin" />
              ) : controlPriority === value ? (
                <Check size={15} />
              ) : null}
              {pendingPriority === value && priorityPending ? "等待设备确认" : label}
            </button>
          ))}
        </div>
        <div className="mt-2 flex min-h-6 items-center justify-between gap-2 text-xs text-ink3">
          <span>
            当前：
            {controlPriority === "auto_first"
              ? "自动优先"
              : controlPriority === "manual_first"
                ? "手动优先"
                : "等待设备回显"}
          </span>
          {hasManualLock ? (
            <button
              type="button"
              disabled={resumePending || supported?.has("control.resume_auto") === false}
              onClick={() => onCommand("control.resume_auto")}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-accent hover:bg-accent/10 disabled:opacity-50"
            >
              {resumePending ? <Loader2 size={13} className="animate-spin" /> : <LockKeyholeOpen size={13} />}
              {resumePending ? "正在释放…" : "释放手动锁定"}
            </button>
          ) : (
            <span className="text-good">无手动锁定</span>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        {COMMANDS.filter(({ type }) => !supported || supported.has(type)).map(({ type, label, Icon }) => {
          const pending = pendingTypes.has(type);
          return (
            <Button
              key={type}
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => onCommand(type)}
              className="group min-h-20 flex-col gap-2 rounded-xl border-line bg-raised px-3 py-3 text-sm font-medium text-ink2 transition-colors hover:border-accent hover:bg-accent/5 hover:text-ink active:bg-accent/10 disabled:opacity-60"
            >
              {pending ? (
                <Loader2 size={20} className="animate-spin text-accent" />
              ) : (
                <Icon size={20} className="text-ink3 transition-colors group-hover:text-accent" />
              )}
              {pending ? "等待确认…" : label}
            </Button>
          );
        })}
      </div>
    </Panel>
  );
}
