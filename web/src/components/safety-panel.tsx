"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Flame, ShieldCheck } from "lucide-react";
import { Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import type { EventOut, TelemetryPoint } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

function exportEvents(events: EventOut[]) {
  const escape = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = [
    ["时间", "事件", "级别", "消息", "确认时间"],
    ...events.map((event) => [
      event.created_at,
      event.type,
      event.severity,
      event.message,
      event.acknowledged_at ?? "",
    ]),
  ];
  const blob = new Blob(["\uFEFF" + rows.map((row) => row.map(escape).join(",")).join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `smoke-events-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function SafetyPanel({
  smokeDetected,
  events,
  history,
  onAcknowledge,
  className,
}: {
  smokeDetected: boolean | null | undefined;
  events: EventOut[];
  history: TelemetryPoint[];
  onAcknowledge: (eventId: number) => void;
  className?: string;
}) {
  const smokeEvents = useMemo(() => events.filter((event) => event.type.startsWith("smoke.")), [events]);
  const activeEvent = smokeEvents.find((event) => event.type === "smoke.detected" && !event.acknowledged_at);
  const [dismissedEventId, setDismissedEventId] = useState<number | null>(null);
  const showEmergency = Boolean(smokeDetected && activeEvent && dismissedEventId !== activeEvent.id);
  const recent = history.slice(-60);

  useEffect(() => {
    if (!smokeDetected) setDismissedEventId(null);
  }, [smokeDetected]);

  return (
    <>
      <Panel
        title="MQ-2 烟雾安全"
        icon={<Flame size={17} />}
        className={className}
        actions={
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium"
            style={
              smokeDetected
                ? { color: "var(--alert)", background: "var(--alert-soft)" }
                : { color: "var(--good)", background: "var(--good-soft)" }
            }
          >
            {smokeDetected ? <AlertTriangle size={13} /> : <ShieldCheck size={13} />}
            {smokeDetected === null || smokeDetected === undefined
              ? "未接入"
              : smokeDetected
                ? "检测到烟雾"
                : "状态正常"}
          </span>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <p className="text-xs leading-relaxed text-ink3">
              烟雾上升沿由设备本地立即触发蜂鸣器与语音，云服务不可用时安全链路仍保持工作。
            </p>
            <div
              className="mt-4 flex h-14 items-end gap-0.5 rounded-lg border border-line bg-raised p-2"
              aria-label="最近烟雾遥测"
            >
              {recent.length ? (
                recent.map((point) => (
                  <span
                    key={point.sampled_at}
                    className="min-w-0 flex-1 rounded-sm"
                    style={{
                      height: point.sensors.smoke_detected ? "100%" : "18%",
                      background: point.sensors.smoke_detected ? "var(--alert)" : "var(--good)",
                    }}
                    title={`${formatDateTime(point.sampled_at)} · ${point.sensors.smoke_detected ? "烟雾" : "正常"}`}
                  />
                ))
              ) : (
                <span className="m-auto text-[11px] text-ink3">暂无烟雾遥测</span>
              )}
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-ink">告警台账 · {smokeEvents.length} 条</p>
              <div className="flex gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => exportEvents(smokeEvents)}
                  className="h-7 gap-1 px-2 text-[11px]"
                >
                  <Download size={12} /> CSV
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    smokeEvents
                      .filter((event) => !event.acknowledged_at)
                      .forEach((event) => onAcknowledge(event.id))
                  }
                  className="h-7 gap-1 px-2 text-[11px]"
                >
                  <CheckCircle2 size={12} /> 全部确认
                </Button>
              </div>
            </div>
            <div className="scroll-thin max-h-40 space-y-1.5 overflow-y-auto pr-1">
              {smokeEvents.length ? (
                smokeEvents.map((event) => (
                  <div
                    key={event.id}
                    className="flex items-center gap-2 rounded-lg border border-line bg-raised px-2.5 py-2 text-[11px]"
                  >
                    <span
                      className="shrink-0"
                      style={{ color: event.type === "smoke.detected" ? "var(--alert)" : "var(--good)" }}
                    >
                      {event.type === "smoke.detected" ? "告警" : "解除"}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-ink2">{event.message}</span>
                    <span className="tnum shrink-0 text-ink3">{formatDateTime(event.created_at)}</span>
                    {event.acknowledged_at ? (
                      <CheckCircle2 size={13} className="shrink-0" style={{ color: "var(--good)" }} />
                    ) : (
                      <button
                        type="button"
                        onClick={() => onAcknowledge(event.id)}
                        className="shrink-0 text-accent hover:underline"
                      >
                        确认
                      </button>
                    )}
                  </div>
                ))
              ) : (
                <p className="py-6 text-center text-xs text-ink3">暂无烟雾事件</p>
              )}
            </div>
          </div>
        </div>
      </Panel>

      {showEmergency && activeEvent ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="smoke-alert-title"
        >
          <div
            className="w-full max-w-md rounded-2xl border p-5 shadow-2xl"
            style={{ borderColor: "var(--alert)", background: "var(--surface-solid)" }}
          >
            <AlertTriangle size={38} style={{ color: "var(--alert)" }} />
            <h2 id="smoke-alert-title" className="mt-3 text-xl font-semibold text-ink">
              检测到烟雾
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-ink2">
              MQ-2
              已触发本地蜂鸣器和语音报警。请立即检查现场并按消防流程处理；确认界面不会关闭仍在持续的硬件报警。
            </p>
            <p className="mt-3 text-xs text-ink3">发生于 {formatDateTime(activeEvent.created_at)}</p>
            <div className="mt-5 flex gap-2">
              <Button
                type="button"
                onClick={() => {
                  onAcknowledge(activeEvent.id);
                  setDismissedEventId(activeEvent.id);
                }}
                className="flex-1"
              >
                确认已处理
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDismissedEventId(activeEvent.id)}
                className="flex-1"
              >
                暂时忽略
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
