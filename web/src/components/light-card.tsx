import { MoonStar, Sun } from "lucide-react";
import { Panel } from "@/components/panel";
import type { TelemetryPoint } from "@/lib/api";

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
    <Panel title="LM393 环境光照" icon={<Sun size={17} />} className={className}>
      <div className="flex items-center gap-3 rounded-xl border border-line bg-raised p-3">
        <div
          className="flex size-11 items-center justify-center rounded-full"
          style={{
            background: !available ? "var(--surface)" : isDark ? "var(--accent-soft)" : "var(--warn-soft)",
            color: !available ? "var(--ink3)" : isDark ? "var(--accent)" : "var(--warn)",
          }}
        >
          <Icon size={22} aria-hidden />
        </div>
        <div>
          <p className="text-lg font-semibold text-ink">{label}</p>
          <p className="text-[11px] text-ink3">数字量明暗判断，不伪造 lux 数值</p>
        </div>
      </div>

      <div className="mt-3">
        <div className="mb-1.5 flex justify-between text-[10px] text-ink3">
          <span>最近状态</span>
          <span>{recent.length ? `${recent.length} 条` : "暂无遥测"}</span>
        </div>
        <div className="flex h-6 items-end gap-1" aria-label="LM393 最近明暗历史">
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
    </Panel>
  );
}
