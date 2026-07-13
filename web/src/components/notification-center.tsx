"use client";

import { AlertTriangle, Bell, CheckCircle2, ChevronDown, Volume2, VolumeX } from "lucide-react";
import type { NotificationOut } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_LABELS: Record<NotificationOut["voice_status"], string> = {
  not_requested: "仅文字",
  unavailable: "文字已送达 · 语音不可用",
  pending: "文字已送达 · 语音待确认",
  executed: "文字与语音均已送达",
  rejected: "文字已送达 · 语音被拒绝",
  failed: "文字已送达 · 语音失败",
};

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function VoiceState({ notification }: { notification: NotificationOut }) {
  const failed = ["unavailable", "rejected", "failed"].includes(notification.voice_status);
  const successful = notification.voice_status === "executed";
  const Icon = !notification.voice_requested
    ? VolumeX
    : failed
      ? AlertTriangle
      : successful
        ? CheckCircle2
        : Volume2;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        failed ? "bg-alert/10 text-alert" : successful ? "bg-good/10 text-good" : "bg-accent/10 text-accent",
      )}
    >
      <Icon size={13} aria-hidden />
      {STATUS_LABELS[notification.voice_status]}
    </span>
  );
}

export function NotificationCenter({ notifications }: { notifications: NotificationOut[] }) {
  const [latest, ...older] = notifications;
  return (
    <section className="glass-panel mt-5 overflow-hidden" aria-labelledby="notification-heading">
      <div className="flex items-center gap-3 border-b border-line px-4 py-3.5 sm:px-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent/10 text-accent">
          <Bell size={18} aria-hidden />
        </span>
        <div>
          <h2 id="notification-heading" className="font-semibold text-ink">
            宿舍通知
          </h2>
          <p className="text-xs text-ink3">辅导员下发的文字与语音通知</p>
        </div>
      </div>

      <div className="px-4 py-4 sm:px-5" aria-live="polite" aria-atomic="true">
        {latest ? (
          <article
            key={latest.id}
            className="animate-fade-slide rounded-xl border border-accent/25 bg-accent/5 p-4"
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <p className="max-w-4xl whitespace-pre-wrap text-sm leading-6 text-ink">{latest.content}</p>
              <VoiceState notification={latest} />
            </div>
            <time className="mt-3 block text-xs text-ink3" dateTime={latest.created_at}>
              {formatTime(latest.created_at)}
            </time>
          </article>
        ) : (
          <p className="py-2 text-sm text-ink3">暂无通知</p>
        )}
      </div>

      {older.length ? (
        <details className="group border-t border-line px-4 py-3 sm:px-5">
          <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between text-sm font-medium text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30">
            查看历史通知（{older.length}）
            <ChevronDown size={16} className="transition-transform group-open:rotate-180" aria-hidden />
          </summary>
          <ol className="mt-2 divide-y divide-line">
            {older.slice(0, 9).map((notification) => (
              <li key={notification.id} className="py-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <p className="whitespace-pre-wrap text-sm leading-6 text-ink2">{notification.content}</p>
                  <VoiceState notification={notification} />
                </div>
                <time className="mt-1 block text-xs text-ink3" dateTime={notification.created_at}>
                  {formatTime(notification.created_at)}
                </time>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}
