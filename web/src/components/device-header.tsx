"use client";

import { ChevronDown, Cpu } from "lucide-react";
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
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-raised px-2.5 py-1 text-xs font-medium text-ink2">
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
  socketState
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
    <header className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex items-center gap-3">
        <div
          className="flex h-11 w-11 items-center justify-center rounded-xl text-white shadow-glow"
          style={{ background: "linear-gradient(135deg, var(--accent), var(--m-eco2))" }}
        >
          <Cpu size={22} />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-accent">ESP32-S3 AIoT</p>
          <h1 className="text-xl font-semibold tracking-tight text-ink">宿智云 · 智能环境控制中心</h1>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <AirQualityBadge level={airQuality} />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-raised px-2.5 py-1 text-xs font-medium text-ink2">
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
            className="appearance-none rounded-lg border border-line bg-raised py-1.5 pl-3 pr-8 text-xs font-medium text-ink2 outline-none transition-colors hover:border-accent focus:border-accent"
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
