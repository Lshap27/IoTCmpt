"use client";

import { useMemo, useState } from "react";
import { Activity } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel } from "@/components/panel";
import type { TelemetryPoint } from "@/lib/api";
import { cn, formatValue } from "@/lib/utils";

export type MetricKey = "temperature_c" | "humidity_percent" | "tvoc_ppb" | "eco2_ppm";

export const METRICS: { key: MetricKey; label: string; unit: string; cssVar: string; digits: number }[] = [
  { key: "temperature_c", label: "温度", unit: "°C", cssVar: "--m-temp", digits: 1 },
  { key: "humidity_percent", label: "湿度", unit: "%", cssVar: "--m-hum", digits: 1 },
  { key: "tvoc_ppb", label: "TVOC", unit: "ppb", cssVar: "--m-tvoc", digits: 0 },
  { key: "eco2_ppm", label: "eCO₂", unit: "ppm", cssVar: "--m-eco2", digits: 0 }
];

type ChartTooltipProps = {
  active?: boolean;
  label?: string;
  payload?: { value?: number | string }[];
  unit: string;
  color: string;
  digits: number;
  metricLabel: string;
};

function ChartTooltip({ active, label, payload, unit, color, digits, metricLabel }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const raw = payload[0]?.value;
  const value = typeof raw === "number" ? raw.toFixed(digits) : String(raw ?? "--");
  return (
    <div
      className="rounded-lg border border-line px-3 py-2 text-xs shadow-panel"
      style={{ background: "var(--surface-solid)" }}
    >
      {/* 数值为主、标签为辅；短线段作为系列识别键 */}
      <div className="flex items-center gap-2">
        <span className="inline-block h-0.5 w-3 rounded-full" style={{ background: color }} aria-hidden />
        <span className="text-base font-semibold text-ink">
          {value}
          <span className="ml-0.5 text-xs font-normal text-ink3">{unit}</span>
        </span>
      </div>
      <div className="mt-0.5 text-ink3">
        {metricLabel} · {label}
      </div>
    </div>
  );
}

export function TelemetryChart({ history, className }: { history: TelemetryPoint[]; className?: string }) {
  const [metricKey, setMetricKey] = useState<MetricKey>("tvoc_ppb");
  const metric = METRICS.find((item) => item.key === metricKey) ?? METRICS[2];
  const color = `var(${metric.cssVar})`;

  const data = useMemo(
    () =>
      history.map((item) => ({
        time: new Date(item.sampled_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        value: item.sensors[metric.key]
      })),
    [history, metric.key]
  );
  const current = history.length > 0 ? history[history.length - 1].sensors[metric.key] : null;

  return (
    <Panel
      title="实时遥测"
      icon={<Activity size={17} />}
      className={className}
      actions={
        <div className="flex items-center gap-3">
          <span className="hidden items-center gap-1.5 text-sm sm:inline-flex">
            <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
            <span className="font-semibold text-ink">{formatValue(current, metric.digits)}</span>
            <span className="text-xs text-ink3">{metric.unit}</span>
          </span>
          <div className="flex rounded-lg border border-line bg-raised p-0.5">
            {METRICS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setMetricKey(item.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  item.key === metric.key ? "bg-surface text-ink shadow-panel" : "text-ink3 hover:text-ink2"
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      }
    >
      <div className="h-64">
        {data.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={`metric-fill-${metric.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={color} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 11, fill: "var(--ink-3)" }}
                tickLine={false}
                axisLine={{ stroke: "var(--grid)" }}
                minTickGap={40}
              />
              <YAxis
                width={44}
                tick={{ fontSize: 11, fill: "var(--ink-3)" }}
                tickLine={false}
                axisLine={false}
                domain={["auto", "auto"]}
              />
              <Tooltip
                cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
                content={
                  <ChartTooltip unit={metric.unit} color={color} digits={metric.digits} metricLabel={metric.label} />
                }
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={color}
                strokeWidth={2}
                fill={`url(#metric-fill-${metric.key})`}
                dot={false}
                activeDot={{ r: 4.5, strokeWidth: 2, stroke: "var(--surface-solid)", fill: color }}
                isAnimationActive={false}
                connectNulls
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-line text-sm text-ink3">
            等待遥测数据…
          </div>
        )}
      </div>
    </Panel>
  );
}
