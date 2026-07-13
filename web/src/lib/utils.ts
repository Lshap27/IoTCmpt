import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const COMMAND_LABELS: Record<string, string> = {
  none: "无动作",
  "window.open": "开窗",
  "window.close": "关窗",
  "alarm.on": "开启报警",
  "alarm.off": "关闭报警",
  "led.on": "开启 LED",
  "led.off": "关闭 LED",
  "control.set_priority": "切换控制优先级",
  "control.resume_auto": "释放手动锁定",
  "alarm.silence": "限时静音",
  "voice.speak": "语音播报",
  "display.message": "屏显消息",
};

export function commandLabel(type: string | null | undefined): string {
  if (!type) return "--";
  return COMMAND_LABELS[type] ?? type;
}

export function describeTrigger(trigger: string | null | undefined): string {
  if (!trigger) return "";
  if (trigger === "manual") return "手动触发";
  if (trigger.startsWith("auto:air_quality=")) {
    const level = trigger.split("=")[1];
    const levelLabel = level === "alert" ? "告警" : level === "watch" ? "观察" : level;
    return `自动触发 · 空气质量${levelLabel}`;
  }
  if (trigger === "auto:alarm_enabled") return "自动触发 · 报警条件";
  if (trigger.startsWith("auto:")) return `自动触发 · ${trigger.slice(5)}`;
  return trigger;
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "--";
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "--";
  const delta = Math.max(0, Date.now() - time);
  if (delta < 10_000) return "刚刚";
  if (delta < 60_000) return `${Math.floor(delta / 1000)} 秒前`;
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分钟前`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时前`;
  return formatDateTime(iso);
}

export function formatValue(value: number | null | undefined, digits = 1): string {
  return typeof value === "number" ? value.toFixed(digits) : "--";
}
