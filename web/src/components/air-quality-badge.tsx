import { AlertOctagon, AlertTriangle, CheckCircle2, HelpCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const LEVELS: Record<string, { label: string; color: string; soft: string; Icon: typeof CheckCircle2 }> = {
  good: { label: "空气优良", color: "var(--good)", soft: "var(--good-soft)", Icon: CheckCircle2 },
  watch: { label: "空气观察", color: "var(--warn)", soft: "var(--warn-soft)", Icon: AlertTriangle },
  alert: { label: "空气告警", color: "var(--alert)", soft: "var(--alert-soft)", Icon: AlertOctagon },
  unknown: { label: "空气未知", color: "var(--ink-3)", soft: "transparent", Icon: HelpCircle },
};

/** 状态色永远伴随图标 + 文字出现，不用颜色单独传达含义。 */
export function AirQualityBadge({
  level,
  className,
}: {
  level: string | null | undefined;
  className?: string;
}) {
  const entry = LEVELS[level ?? "unknown"] ?? LEVELS.unknown;
  const { Icon } = entry;
  return (
    <Badge
      variant="outline"
      className={cn("gap-1.5 rounded-full border-line px-2.5 py-1 text-xs font-medium text-ink2", className)}
      style={{ background: entry.soft }}
    >
      <Icon size={14} style={{ color: entry.color }} />
      {entry.label}
    </Badge>
  );
}
