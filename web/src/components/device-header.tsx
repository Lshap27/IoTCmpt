"use client";

import { ChevronDown, CircuitBoard } from "lucide-react";
import { AirQualityBadge } from "@/components/air-quality-badge";
import { ThemeToggle } from "@/components/theme-toggle";
import type { DeviceSummary } from "@/lib/api";
import type { SocketState } from "@/hooks/use-device-live";
import { cn } from "@/lib/utils";

function LivePill({ socketState }: { socketState: SocketState }) {
  const config =
    socketState === "live"
      ? { label: "实时", color: "var(--good)", pulse: true }
      : socketState === "connecting"
        ? { label: "连接中", color: "var(--warn)", pulse: true }
        : { label: "离线重连中", color: "var(--alert)", pulse: false };
  return (
    <span className="inline-flex min-h-9 items-center gap-2 rounded-full border border-line bg-surface px-3 text-sm font-medium text-ink2">
      <span
        className={cn("h-2 w-2 rounded-full", config.pulse && "animate-pulse-soft")}
        style={{ background: config.color }}
        aria-hidden
      />
      {config.label}
    </span>
  );
}

export function DeviceHeader({
  devices,
  deviceId,
  onDeviceChange,
  deviceStatus,
  airQuality,
  socketState,
}: {
  devices: DeviceSummary[];
  deviceId: string;
  onDeviceChange: (deviceId: string) => void;
  deviceStatus: string;
  airQuality: string | null | undefined;
  socketState: SocketState;
}) {
  const online = deviceStatus === "online";
  const options = devices.some((device) => device.device_id === deviceId)
    ? devices
    : [{ device_id: deviceId, display_name: deviceId, status: deviceStatus, last_seen_at: null }, ...devices];

  return (
    <header className="flex flex-col gap-5 border-b border-line pb-6 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex items-center gap-3.5">
        <div
          className="flex h-12 w-12 items-center justify-center rounded-2xl text-white shadow-glow"
          style={{ background: "linear-gradient(145deg, var(--accent), var(--accent-strong))" }}
        >
          <CircuitBoard size={23} />
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">宿智云</h1>
          <p className="mt-0.5 text-sm text-ink2">智能环境控制中心</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <AirQualityBadge level={airQuality} />
        <span className="inline-flex min-h-9 items-center gap-2 rounded-full border border-line bg-surface px-3 text-sm font-medium text-ink2">
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: online ? "var(--good)" : "var(--ink-3)" }}
            aria-hidden
          />
          {online ? "设备在线" : "设备离线"}
        </span>
        <LivePill socketState={socketState} />
        <label className="relative inline-flex items-center">
          <span className="sr-only">选择设备</span>
          <select
            value={deviceId}
            onChange={(event) => onDeviceChange(event.target.value)}
            className="min-h-10 appearance-none rounded-xl border border-line bg-surface py-2 pl-3 pr-9 text-sm font-medium text-ink2 outline-hidden transition-colors hover:border-accent focus:border-accent focus:ring-2 focus:ring-accent/20"
          >
            {options.map((device) => (
              <option key={device.device_id} value={device.device_id}>
                {device.display_name || device.device_id}
              </option>
            ))}
          </select>
          <ChevronDown size={14} className="pointer-events-none absolute right-2.5 text-ink3" />
        </label>
        <ThemeToggle />
      </div>
    </header>
  );
}
