"use client";

import {
  BellOff,
  BellRing,
  DoorClosed,
  DoorOpen,
  Lightbulb,
  LightbulbOff,
  Loader2,
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
      className="gap-1.5 rounded-full border-line bg-raised px-2 py-0.5 text-[11px] text-ink2"
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
  className,
}: {
  onCommand: (type: string) => void;
  pendingCommands: Record<string, string>;
  windowOpen: boolean | null | undefined;
  alarmOn: boolean | null | undefined;
  ledOn: boolean | null | undefined;
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
          <StateChip label="LED" active={ledOn} />
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        {COMMANDS.map(({ type, label, Icon }) => {
          const pending = pendingTypes.has(type);
          return (
            <Button
              key={type}
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => onCommand(type)}
              className="group h-auto flex-col gap-1.5 rounded-xl border-line bg-raised px-3 py-3.5 text-sm font-medium text-ink2 transition-all hover:border-accent hover:bg-raised hover:text-ink hover:shadow-glow active:scale-[0.98] disabled:opacity-60"
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
      <p className="mt-3 text-[11px] leading-relaxed text-ink3">
        指令经服务器持久化后经 MQTT 下发，按钮在设备回执（command_ack）前保持等待状态。
      </p>
    </Panel>
  );
}
