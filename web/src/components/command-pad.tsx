"use client";

import { BellOff, BellRing, DoorClosed, DoorOpen, Loader2, SlidersHorizontal } from "lucide-react";
import { Panel } from "@/components/panel";

const COMMANDS: { type: string; label: string; Icon: typeof DoorOpen }[] = [
  { type: "window.open", label: "开窗", Icon: DoorOpen },
  { type: "window.close", label: "关窗", Icon: DoorClosed },
  { type: "alarm.on", label: "报警开", Icon: BellRing },
  { type: "alarm.off", label: "报警关", Icon: BellOff }
];

function StateChip({ label, active }: { label: string; active: boolean | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-raised px-2 py-0.5 text-[11px] text-ink2">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: active ? "var(--accent)" : "var(--ink-3)" }}
        aria-hidden
      />
      {label}
      {active === null || active === undefined ? " --" : active ? " 开" : " 关"}
    </span>
  );
}

export function CommandPad({
  onCommand,
  pendingCommands,
  windowOpen,
  alarmOn,
  className
}: {
  onCommand: (type: string) => void;
  pendingCommands: Record<string, string>;
  windowOpen: boolean | null | undefined;
  alarmOn: boolean | null | undefined;
  className?: string;
}) {
  const pendingTypes = new Set(Object.values(pendingCommands));

  return (
    <Panel
      title="设备指令"
      icon={<SlidersHorizontal size={17} />}
      className={className}
      actions={
        <div className="flex gap-1.5">
          <StateChip label="窗户" active={windowOpen} />
          <StateChip label="报警" active={alarmOn} />
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-2.5">
        {COMMANDS.map(({ type, label, Icon }) => {
          const pending = pendingTypes.has(type);
          return (
            <button
              key={type}
              type="button"
              disabled={pending}
              onClick={() => onCommand(type)}
              className="group flex flex-col items-center gap-1.5 rounded-xl border border-line bg-raised px-3 py-3.5 text-sm font-medium text-ink2 transition-all hover:border-accent hover:text-ink hover:shadow-glow active:scale-[0.98] disabled:opacity-60"
            >
              {pending ? (
                <Loader2 size={20} className="animate-spin text-accent" />
              ) : (
                <Icon size={20} className="text-ink3 transition-colors group-hover:text-accent" />
              )}
              {pending ? "等待确认…" : label}
            </button>
          );
        })}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-ink3">
        指令经服务器持久化后经 MQTT 下发，按钮在设备回执（command_ack）前保持等待状态。
      </p>
    </Panel>
  );
}
