import { MoonStar, Sun } from "lucide-react";
import type { TelemetryPoint } from "@/lib/api";
import { cn } from "@/lib/utils";

export function LightCard({
  isDark,
  history,
  className,
}: {
  isDark: boolean | null | undefined;
  history: TelemetryPoint[];
  className?: string;
}) {
  const recent = history.slice(-24);
  const available = typeof isDark === "boolean";
  const label = !available ? "未接入" : isDark ? "环境偏暗" : "环境明亮";
  const Icon = isDark ? MoonStar : Sun;

  return (
    <div className={cn("glass-panel min-w-0 p-4", className)}>
      <div className="flex items-center gap-2 text-sm font-medium text-ink2">
        <span className="h-2 w-2 rounded-full bg-warn" aria-hidden />
        环境光照
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div
          className="flex size-10 items-center justify-center rounded-xl"
          style={{
            background: !available ? "var(--surface)" : isDark ? "var(--accent-soft)" : "var(--warn-soft)",
            color: !available ? "var(--ink-3)" : isDark ? "var(--accent)" : "var(--warn)",
          }}
        >
          <Icon size={20} aria-hidden />
        </div>
        <div>
          <p className="text-xl font-semibold tracking-tight text-ink">{label}</p>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex h-7 items-end gap-1" aria-label="LM393 最近明暗历史">
          {recent.length ? (
            recent.map((point) => {
              const dark = point.sensors.light_is_dark;
              return (
                <span
                  key={point.sampled_at}
                  className="min-w-1 flex-1 rounded-sm"
                  style={{
                    height: typeof dark !== "boolean" ? "30%" : dark ? "55%" : "100%",
                    background:
                      typeof dark !== "boolean" ? "var(--line)" : dark ? "var(--accent)" : "var(--warn)",
                  }}
                  title={`${new Date(point.sampled_at).toLocaleString("zh-CN")} · ${typeof dark !== "boolean" ? "未知" : dark ? "偏暗" : "明亮"}`}
                />
              );
            })
          ) : (
            <div className="h-px w-full bg-line" />
          )}
        </div>
      </div>
    </div>
  );
}
