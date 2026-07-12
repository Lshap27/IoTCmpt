"use client";

import { useMemo, useState } from "react";
import { BrainCircuit, FileText, Printer, Sparkles } from "lucide-react";
import { Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import type { AiHealthReport, EventOut, ReportPeriod, TelemetryBucketPoint } from "@/lib/api";

type Period = ReportPeriod;

function weightedAverage(samples: TelemetryBucketPoint[], field: keyof TelemetryBucketPoint) {
  const values = samples.flatMap((sample) => {
    const value = sample[field];
    return typeof value === "number" ? [{ value, weight: sample.sample_count }] : [];
  });
  const weight = values.reduce((sum, item) => sum + item.weight, 0);
  return weight ? values.reduce((sum, item) => sum + item.value * item.weight, 0) / weight : null;
}

export function HealthReport({
  deviceId,
  history,
  events,
  aiReport,
  generating,
  onGenerate,
  className,
}: {
  deviceId: string;
  history: TelemetryBucketPoint[];
  events: EventOut[];
  aiReport: AiHealthReport | null;
  generating: boolean;
  onGenerate: (period: ReportPeriod) => void;
  className?: string;
}) {
  const [period, setPeriod] = useState<Period>("day");
  const report = useMemo(() => {
    const hours = period === "hour" ? 1 : period === "day" ? 24 : 24 * 7;
    const cutoff = Date.now() - hours * 60 * 60 * 1000;
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
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-xl border border-line bg-raised p-1">
            {(["hour", "day", "week"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setPeriod(value)}
                className={`min-h-8 rounded-lg px-3 text-xs font-medium transition-colors ${period === value ? "bg-surface text-ink shadow-sm" : "text-ink3 hover:text-ink2"}`}
              >
                {value === "hour" ? "小时" : value === "day" ? "日报" : "周报"}
              </button>
            ))}
          </div>
          <Button
            type="button"
            onClick={() => onGenerate(period)}
            disabled={generating || !report.samples.length}
            className="h-10 gap-1.5 rounded-xl px-3 text-sm"
          >
            <Sparkles size={12} /> {generating ? "生成中…" : "AI 解读"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => window.print()}
            className="h-10 gap-1.5 rounded-xl px-3 text-sm"
          >
            <Printer size={12} /> 打印
          </Button>
        </div>
      }
    >
      {report.samples.length ? (
        <div className="space-y-4">
          <p className="text-sm text-ink2">
            报告周期：{report.start.toLocaleString("zh-CN")} — {report.end.toLocaleString("zh-CN")}
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
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
              <div key={label} className="rounded-xl border border-line bg-raised p-3.5">
                <p className="text-xs font-medium text-ink2">{label}</p>
                <p className="mt-1.5 text-xl font-semibold tracking-tight text-ink">
                  {value}
                  <span className="ml-1 text-xs font-normal text-ink3">{unit}</span>
                </p>
              </div>
            ))}
          </div>
          <ul className="space-y-2 text-sm leading-relaxed text-ink2">
            {report.insights.map((insight) => (
              <li key={insight}>• {insight}</li>
            ))}
          </ul>
          {aiReport && aiReport.device_id === deviceId && aiReport.period === period ? (
            <div className="rounded-2xl border border-accent/20 bg-accent/5 p-4 sm:p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <BrainCircuit size={16} className="text-accent" />
                  <p className="text-sm font-semibold text-ink">{aiReport.headline}</p>
                </div>
                <span className="text-sm font-medium text-ink2">
                  风险 {aiReport.risk_score}/100 · {aiReport.model}
                </span>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-ink2">{aiReport.summary}</p>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                {[
                  ["异常发现", aiReport.anomalies],
                  ["优先建议", aiReport.recommendations],
                  ["后续检查", aiReport.next_checks],
                ].map(([title, items]) => (
                  <div key={title as string}>
                    <p className="text-sm font-semibold text-ink">{title as string}</p>
                    <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-ink2">
                      {(items as string[]).map((item) => (
                        <li key={item}>• {item}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-xs text-ink3">
                数据完整度 {aiReport.coverage.completeness_percent.toFixed(1)}% · 共{" "}
                {aiReport.coverage.sample_count} 条采样
              </p>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-line py-12 text-center text-sm text-ink3">
          当前时段没有真实遥测，无法生成报告
        </div>
      )}
    </Panel>
  );
}
