"use client";

import { useMemo, useState } from "react";
import { FileText, Printer } from "lucide-react";
import { Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import type { EventOut, TelemetryBucketPoint } from "@/lib/api";

type Period = "day" | "week";

function weightedAverage(samples: TelemetryBucketPoint[], field: keyof TelemetryBucketPoint) {
  const values = samples.flatMap((sample) => {
    const value = sample[field];
    return typeof value === "number" ? [{ value, weight: sample.sample_count }] : [];
  });
  const weight = values.reduce((sum, item) => sum + item.weight, 0);
  return weight ? values.reduce((sum, item) => sum + item.value * item.weight, 0) / weight : null;
}

export function HealthReport({
  history,
  events,
  className,
}: {
  history: TelemetryBucketPoint[];
  events: EventOut[];
  className?: string;
}) {
  const [period, setPeriod] = useState<Period>("day");
  const report = useMemo(() => {
    const cutoff = Date.now() - (period === "day" ? 24 : 24 * 7) * 60 * 60 * 1000;
    const samples = history.filter((point) => new Date(point.bucket).getTime() >= cutoff);
    const smokeEvents = events.filter(
      (event) => event.type === "smoke.detected" && new Date(event.created_at).getTime() >= cutoff,
    );
    const sampleCount = samples.reduce((sum, point) => sum + point.sample_count, 0);
    const temperatureMins = samples.flatMap((point) =>
      typeof point.temperature_min_c === "number" ? [point.temperature_min_c] : [],
    );
    const temperatureMaxes = samples.flatMap((point) =>
      typeof point.temperature_max_c === "number" ? [point.temperature_max_c] : [],
    );
    const eco2Maxes = samples.flatMap((point) =>
      typeof point.eco2_max_ppm === "number" ? [point.eco2_max_ppm] : [],
    );
    const highHumidityHours = samples.filter(
      (point) => typeof point.humidity_percent === "number" && point.humidity_percent > 75,
    ).length;
    const lowHumidityHours = samples.filter(
      (point) => typeof point.humidity_percent === "number" && point.humidity_percent < 30,
    ).length;
    const nightEco2ExceedHours = samples.filter((point) => {
      const hour = new Date(point.bucket).getHours();
      return (hour >= 23 || hour < 7) && typeof point.eco2_max_ppm === "number" && point.eco2_max_ppm > 1000;
    }).length;
    const insights: string[] = [];
    if (highHumidityHours) insights.push(`高湿小时桶 ${highHumidityHours} 个，建议加强通风并排查持续湿源。`);
    if (lowHumidityHours) insights.push(`低湿小时桶 ${lowHumidityHours} 个，建议关注长期干燥问题。`);
    if (nightEco2ExceedHours)
      insights.push(`夜间 eCO₂ 超过 1000 ppm 的小时桶共 ${nightEco2ExceedHours} 个，建议优化睡眠时段通风。`);
    if (samples.some((point) => typeof point.tvoc_ppb === "number" && point.tvoc_ppb > 300))
      insights.push("TVOC 曾处于观察或告警区间，请排查污染源。");
    if (samples.some((point) => typeof point.hcho_ug_m3 === "number" && point.hcho_ug_m3 > 60))
      insights.push("HCHO 曾超过 60 μg/m³，建议排查装修材料或挥发源。");
    if (smokeEvents.length)
      insights.push(`记录到 ${smokeEvents.length} 次独立烟雾告警，请核对台账处理情况。`);
    if (samples.length && !insights.length) insights.push("采样范围内未发现明显环境告警。");
    return {
      samples,
      sampleCount,
      smokeEvents,
      temperature: weightedAverage(samples, "temperature_c"),
      minTemperature: temperatureMins.length ? Math.min(...temperatureMins) : null,
      maxTemperature: temperatureMaxes.length ? Math.max(...temperatureMaxes) : null,
      humidity: weightedAverage(samples, "humidity_percent"),
      highHumidityHours,
      eco2: weightedAverage(samples, "eco2_ppm"),
      maxEco2: eco2Maxes.length ? Math.max(...eco2Maxes) : null,
      nightEco2ExceedHours,
      insights,
      start: new Date(cutoff),
      end: new Date(),
    };
  }, [events, history, period]);

  return (
    <Panel
      title="宿舍环境健康报告"
      icon={<FileText size={17} />}
      className={className}
      actions={
        <div className="flex gap-1.5">
          <div className="flex rounded-lg border border-line bg-raised p-0.5">
            {(["day", "week"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setPeriod(value)}
                className={`rounded-md px-2 py-1 text-[11px] ${period === value ? "bg-surface text-ink" : "text-ink3"}`}
              >
                {value === "day" ? "日报" : "周报"}
              </button>
            ))}
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => window.print()}
            className="h-7 gap-1 px-2 text-[11px]"
          >
            <Printer size={12} /> 打印
          </Button>
        </div>
      }
    >
      {report.samples.length ? (
        <div className="space-y-4">
          <p className="text-[11px] text-ink3">
            报告周期：{report.start.toLocaleString("zh-CN")} — {report.end.toLocaleString("zh-CN")}
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            {[
              ["有效采样", report.sampleCount, "条"],
              ["平均温度", report.temperature?.toFixed(1) ?? "--", "°C"],
              [
                "温度范围",
                report.minTemperature !== null && report.maxTemperature !== null
                  ? `${report.minTemperature.toFixed(1)}~${report.maxTemperature.toFixed(1)}`
                  : "--",
                "°C",
              ],
              ["平均湿度", report.humidity?.toFixed(1) ?? "--", "%"],
              ["高湿时长", report.highHumidityHours, "小时桶"],
              ["平均 eCO₂", report.eco2?.toFixed(0) ?? "--", "ppm"],
              ["最高 eCO₂", report.maxEco2?.toFixed(0) ?? "--", "ppm"],
              ["夜间 eCO₂ 超标", report.nightEco2ExceedHours, "小时桶"],
              ["烟雾告警", report.smokeEvents.length, "次"],
            ].map(([label, value, unit]) => (
              <div key={label} className="rounded-lg border border-line bg-raised p-3">
                <p className="text-[11px] text-ink3">{label}</p>
                <p className="mt-1 text-lg font-semibold text-ink">
                  {value}
                  <span className="ml-1 text-[11px] font-normal text-ink3">{unit}</span>
                </p>
              </div>
            ))}
          </div>
          <ul className="space-y-1.5 text-xs leading-relaxed text-ink2">
            {report.insights.map((insight) => (
              <li key={insight}>• {insight}</li>
            ))}
          </ul>
          <p className="text-[11px] text-ink3">
            本报告只统计数据库中该时段的真实采样；数据不足时不会补造缺失时段。
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-line py-10 text-center text-xs text-ink3">
          当前时段没有真实遥测，无法生成报告
        </div>
      )}
    </Panel>
  );
}
