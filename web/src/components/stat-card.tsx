"use client";

import { AnimatedNumber } from "@/components/animated-number";
import { cn } from "@/lib/utils";

function Sparkline({ points, color }: { points: number[]; color: string }) {
  if (points.length < 2) {
    return <div className="h-7" />;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = 100 / (points.length - 1);
  const coords = points.map((value, index) => {
    const x = index * step;
    const y = 24 - ((value - min) / span) * 20;
    return { x, y };
  });
  const path = coords.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const last = coords[coords.length - 1];

  return (
    <svg viewBox="0 0 100 28" className="h-7 w-full" preserveAspectRatio="none" aria-hidden>
      {/* 趋势线用弱化色，只有端点戴系列色 + 表面色描边环 */}
      <polyline
        points={path}
        fill="none"
        stroke="var(--spark)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={last.x} cy={last.y} r="3" fill={color} stroke="var(--surface-solid)" strokeWidth="2" />
    </svg>
  );
}

export function StatCard({
  label,
  unit,
  value,
  digits,
  color,
  points,
  className,
}: {
  label: string;
  unit: string;
  value: number | null | undefined;
  digits: number;
  color: string;
  points: (number | null)[];
  className?: string;
}) {
  const series = points.filter((point): point is number => typeof point === "number").slice(-20);

  return (
    <div className={cn("glass-panel min-w-0 p-4", className)}>
      <div className="flex items-center gap-2 text-sm font-medium text-ink2">
        <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
        {label}
      </div>
      <div className="mt-3 flex items-baseline gap-1.5">
        <AnimatedNumber
          value={value}
          digits={digits}
          className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl"
        />
        <span className="text-sm text-ink3">{unit}</span>
      </div>
      <div className="mt-2">
        <Sparkline points={series} color={color} />
      </div>
    </div>
  );
}
