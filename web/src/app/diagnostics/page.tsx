"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowLeft, Search, ServerCog, Workflow } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { fetchDiagnosticsOverview, fetchReadiness, fetchTrace } from "@/lib/api";

export default function DiagnosticsPage() {
  const [input, setInput] = useState("");
  const [traceId, setTraceId] = useState("");
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("trace") ?? "";
    setInput(initial);
    setTraceId(initial);
  }, []);
  const health = useQuery({
    queryKey: ["diagnostics", "health"],
    queryFn: fetchReadiness,
    refetchInterval: 5000,
  });
  const trace = useQuery({
    queryKey: ["diagnostics", "trace", traceId],
    queryFn: () => fetchTrace(traceId),
    enabled: Boolean(traceId),
  });
  const overview = useQuery({
    queryKey: ["diagnostics", "overview"],
    queryFn: fetchDiagnosticsOverview,
    refetchInterval: 5000,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setTraceId(input.trim());
  }

  return (
    <main className="mx-auto min-h-dvh max-w-6xl px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-ink3 hover:text-ink">
            <ArrowLeft size={14} /> 返回控制台
          </Link>
          <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight text-ink">
            <ServerCog className="text-accent" /> 系统诊断
          </h1>
          <p className="mt-1 text-sm text-ink3">按 trace_id 串联 AI、MCP、MQTT、固件 ACK 与 WebSocket。</p>
        </div>
      </header>

      <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="服务健康状态">
        {Object.entries(health.data?.dependencies ?? {}).map(([name, value]) => {
          const healthy = ["connected", "healthy", "current", "enabled"].includes(value);
          return (
            <article key={name} className="rounded-xl border border-line bg-surface p-4 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs uppercase tracking-wide text-ink3">{name}</span>
                <Activity size={14} className={healthy ? "text-good" : "text-warn"} aria-hidden />
              </div>
              <p className={`mt-2 text-sm font-semibold ${healthy ? "text-good" : "text-warn"}`}>{value}</p>
            </article>
          );
        })}
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-3" aria-label="队列与设备诊断">
        {[
          ["AI 任务", overview.data?.ai_runs],
          ["命令 Outbox", overview.data?.outbox],
          ["实时事件", overview.data?.realtime],
        ].map(([title, values]) => (
          <article key={String(title)} className="rounded-2xl border border-line bg-surface p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-ink">{String(title)}</h2>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-ink2">
              {Object.entries((values ?? {}) as Record<string, number>).length ? (
                Object.entries((values ?? {}) as Record<string, number>).map(([status, count]) => (
                  <span key={status} className="rounded-full bg-raised px-2.5 py-1">
                    {status}: {count}
                  </span>
                ))
              ) : (
                <span className="text-ink3">暂无记录</span>
              )}
            </div>
          </article>
        ))}
      </section>

      <section className="mt-4 grid gap-4 lg:grid-cols-2">
        <article className="rounded-2xl border border-line bg-surface p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-ink">Worker 心跳</h2>
          <ul className="mt-3 space-y-2 text-xs text-ink2">
            {overview.data?.workers.length ? (
              overview.data.workers.map((worker) => (
                <li
                  key={worker.instance_id}
                  className="flex items-center justify-between gap-3 rounded-lg bg-raised p-2"
                >
                  <span>
                    {worker.instance_id} · {new Date(worker.heartbeat_at).toLocaleString("zh-CN")}
                  </span>
                  <span className={worker.healthy ? "text-ok" : "text-warn"}>
                    {worker.healthy ? "健康" : `已失联 ${worker.age_seconds} 秒`}
                  </span>
                </li>
              ))
            ) : (
              <li className="text-ink3">未发现 Worker 心跳</li>
            )}
          </ul>
        </article>
        <article className="rounded-2xl border border-line bg-surface p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-ink">设备能力与 MCP</h2>
          <p className="mt-2 text-xs text-ink2">
            内部 MCP：{overview.data?.mcp.internal_configured ? "已配置" : "未配置"} · 外部 MCP：
            {overview.data?.mcp.external_enabled ? "已启用" : "已关闭"}
          </p>
          <ul className="mt-3 space-y-2 text-xs text-ink2">
            {overview.data?.capabilities.map((device) => (
              <li key={device.device_id} className="rounded-lg bg-raised p-2">
                {device.device_id} · {device.hardware_model} · {device.command_count} 项命令
              </li>
            ))}
          </ul>
        </article>
      </section>

      <section className="mt-6 rounded-2xl border border-line bg-surface p-4 shadow-sm sm:p-5">
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row">
          <label className="flex-1">
            <span className="sr-only">Trace ID</span>
            <input
              value={input}
              onChange={(event) => setInput(event.currentTarget.value)}
              placeholder="trace-..."
              className="h-11 w-full rounded-xl border border-line bg-raised px-3 text-sm text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent/15"
            />
          </label>
          <Button type="submit" disabled={!input.trim()} className="h-11 gap-2 rounded-xl px-5">
            <Search size={15} /> 查询时间线
          </Button>
        </form>
      </section>

      <section
        className="mt-6 rounded-2xl border border-line bg-surface p-4 shadow-sm sm:p-5"
        aria-live="polite"
      >
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
          <Workflow size={17} className="text-accent" /> Trace 时间线
        </h2>
        {trace.isLoading ? <p className="py-10 text-center text-sm text-ink3">正在读取时间线…</p> : null}
        {trace.error ? <p className="mt-4 rounded-lg bg-alert/10 p-3 text-sm text-alert">查询失败</p> : null}
        {trace.data?.events?.length ? (
          <ol className="mt-4 space-y-3 border-l border-line pl-5">
            {trace.data.events?.map((event) => (
              <li key={event.event_id} className="relative rounded-xl border border-line bg-raised p-3">
                <span className="absolute -left-[1.58rem] top-4 size-2.5 rounded-full border-2 border-surface bg-accent" />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-ink">{event.event_type}</p>
                  <span className="text-xs text-ink3">
                    {new Date(event.occurred_at).toLocaleString("zh-CN")}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink3">
                  {event.component} · {event.status ?? "--"}
                </p>
                <pre className="mt-2 overflow-x-auto rounded-lg bg-surface p-2 text-xs text-ink2">
                  {JSON.stringify(event.detail, null, 2)}
                </pre>
              </li>
            ))}
          </ol>
        ) : traceId && !trace.isLoading ? (
          <p className="py-10 text-center text-sm text-ink3">没有找到该 trace 的事件。</p>
        ) : (
          <p className="py-10 text-center text-sm text-ink3">输入 trace_id 后查看完整执行链。</p>
        )}
      </section>
    </main>
  );
}
