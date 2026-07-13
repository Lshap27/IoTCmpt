"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Bell,
  Building2,
  ClipboardList,
  CloudSun,
  Download,
  Lightbulb,
  Mail,
  Radio,
  Settings,
  Trophy,
  Volume2,
  VolumeX,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Legend, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip } from "recharts";
import { useDeviceLive } from "@/hooks/use-device-live";
import type { NotificationOut } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  DEMO_ALERTS,
  DEMO_DORMS,
  DEMO_NOTIFICATIONS,
  IOT_DEMO_DORMS,
  MAINTENANCE_ORDERS,
} from "./admin-demo-data";
import type { DemoAlert, DemoNotification } from "./admin-demo-data";

const DEVICE_ID = "esp32s3-001";
const DORM_NAME = "映雪3-301";

type Tab = "dashboard" | "score" | "alerts" | "messages" | "settings";
type SettingsTab = "accounts" | "maintenance" | "privacy";

const NAV_ITEMS: Array<{ id: Tab; label: string; icon: LucideIcon }> = [
  { id: "dashboard", label: "宿舍管理", icon: Building2 },
  { id: "score", label: "文明宿舍评分", icon: Trophy },
  { id: "alerts", label: "安全告警中心", icon: Bell },
  { id: "messages", label: "消息通知", icon: Mail },
  { id: "settings", label: "系统设置", icon: Settings },
];

const TEMPLATES = [
  {
    title: "恶劣天气提醒",
    icon: CloudSun,
    content:
      "紧急通知：近期有台风、暴雨等恶劣天气，请同学们及时关好门窗，注意出行安全，妥善保管个人贵重物品。",
  },
  {
    title: "安全通风警示",
    icon: Radio,
    content: "当前室内空气质量较差，请立即开窗通风，保持空气流通。",
  },
  {
    title: "查寝通知",
    icon: ClipboardList,
    content: "各位同学请注意，今晚22:00将进行例行查寝，请提前回到宿舍做好准备。",
  },
  {
    title: "文明宿舍评比通知",
    icon: Trophy,
    content: "本月文明宿舍评比即将开始，请各宿舍注意卫生、通风、节电，争取获得优秀评价！",
  },
];

const RADAR_DATA = [
  { subject: "通风", red: 88, black: 55, average: 72 },
  { subject: "节电", red: 85, black: 48, average: 68 },
  { subject: "安全告警", red: 92, black: 62, average: 78 },
  { subject: "作息健康", red: 80, black: 40, average: 65 },
];

function formatValue(value: number | null | undefined, digits = 0) {
  return value === null || value === undefined ? "--" : value.toFixed(digits);
}

function formatTime(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function approximateGb2312Bytes(value: string) {
  return [...value].reduce((total, character) => total + (character.codePointAt(0)! <= 0x7f ? 1 : 2), 0);
}

function DemoBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-full bg-slate-200 font-medium text-slate-600",
        compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]",
      )}
    >
      演示数据
    </span>
  );
}

function LiveBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" aria-hidden />
      实时
    </span>
  );
}

function Badge({
  children,
  tone = "blue",
}: {
  children: ReactNode;
  tone?: "blue" | "green" | "amber" | "red" | "gray";
}) {
  const styles = {
    blue: "bg-blue-50 text-blue-600",
    green: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    red: "bg-red-50 text-red-600",
    gray: "bg-slate-100 text-slate-600",
  };
  return (
    <span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-medium", styles[tone])}>
      {children}
    </span>
  );
}

function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border border-slate-100 bg-white p-4 shadow-sm sm:p-5", className)}>
      {children}
    </section>
  );
}

function CardTitle({ children, trailing }: { children: ReactNode; trailing?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-3">
      <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900">
        <span className="h-5 w-1 rounded-full bg-blue-600" aria-hidden />
        {children}
      </h2>
      {trailing}
    </div>
  );
}

function SmallButton({
  children,
  onClick,
  danger = false,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  danger?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      className={cn(
        "min-h-9 rounded border px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
        danger
          ? "border-red-500 bg-red-500 text-white hover:bg-red-600"
          : "border-blue-600 bg-white text-blue-600 hover:bg-blue-50",
      )}
    >
      {children}
    </button>
  );
}

function StatCard({
  emoji,
  value,
  label,
  change,
  tone = "blue",
}: {
  emoji: string;
  value: string | number;
  label: string;
  change?: string;
  tone?: "blue" | "green" | "amber" | "red";
}) {
  const tones = {
    blue: "text-blue-600",
    green: "text-emerald-600",
    amber: "text-amber-600",
    red: "text-red-500",
  };
  const backgrounds = { blue: "bg-blue-50", green: "bg-emerald-50", amber: "bg-amber-50", red: "bg-red-50" };
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-2xl",
            backgrounds[tone],
          )}
        >
          {emoji}
        </span>
        <div className="min-w-0">
          <p className={cn("text-3xl font-bold tabular-nums", tones[tone])}>{value}</p>
          <p className="text-sm text-slate-600">{label}</p>
          {change ? (
            <p
              className={cn(
                "mt-1 text-[11px]",
                tone === "green" ? "text-emerald-600" : tone === "red" ? "text-red-500" : "text-slate-500",
              )}
            >
              {change}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DashboardPanel({
  live,
  alerts,
  setTab,
  handleAlert,
  toast,
}: {
  live: ReturnType<typeof useDeviceLive>;
  alerts: DemoAlert[];
  setTab: (tab: Tab) => void;
  handleAlert: (dorm: string) => void;
  toast: (message: string, tone?: "success" | "info" | "danger") => void;
}) {
  const [selectedDorm, setSelectedDorm] = useState(0);
  const [demoLed, setDemoLed] = useState<Record<number, boolean>>({});
  const telemetry = live.latest?.telemetry;
  const sensors = telemetry?.sensors;
  const state = telemetry?.state;
  const fusion = telemetry?.fusion;
  const smoke = sensors?.smoke_detected === true;
  const online = live.latest?.device.status === "online";
  const demo = selectedDorm === 0 ? null : IOT_DEMO_DORMS[selectedDorm - 1];
  const selectedName = demo?.id ?? DORM_NAME;
  const temperature = demo?.temp ?? sensors?.temperature_c;
  const humidity = demo?.hum ?? sensors?.humidity_percent;
  const co2 = demo?.co2 ?? sensors?.eco2_ppm;
  const hcho = demo ? demo.formaldehyde * 1000 : sensors?.hcho_ug_m3;
  const tvoc = demo ? demo.tvoc * 1000 : sensors?.tvoc_ppb;
  const isDark = demo ? !demo.lightOn : sensors?.light_is_dark;
  const selectedSmoke = demo ? demo.mq2 > 0 : smoke;
  const ledOn = demo ? (demoLed[selectedDorm] ?? demo.lightOn) : state?.led_on;
  const buzzerOn = demo ? demo.mq2 > 0 || demo.temp > 35 || demo.co2 > 1500 : smoke || state?.alarm_on;
  const windowOpen = demo ? demo.windowOpen : state?.window_open;
  const airStatus =
    selectedSmoke || (demo ? demo.temp > 35 || demo.co2 > 1500 : fusion?.air_quality === "alert")
      ? "AIR BAD - ALERT!"
      : (demo ? demo.co2 > 1000 || demo.formaldehyde > 0.06 : fusion?.air_quality === "watch")
        ? "AIR FAIR - CHECK"
        : "AIR GOOD";
  const liveSmokeEvents = live.ledger.filter((event) => event.type.startsWith("smoke."));
  const highRiskCount = 3 + (smoke ? 1 : 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 rounded-lg border border-red-200 bg-gradient-to-r from-red-50 to-orange-50 p-4 lg:flex-row lg:items-center">
        <span className="text-3xl" aria-hidden>
          🚨
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-red-500">当前存在 {highRiskCount} 条高危告警需立即处理</h2>
          <p className="mt-1 text-sm text-slate-600">
            涉及燃气超标、高温预警、设备离线，请及时查看并采取措施
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {smoke ? (
              <button
                onClick={() => setTab("alerts")}
                className="rounded-full bg-red-500 px-3 py-1 text-xs text-white"
              >
                🔥 映雪3-301 检测到烟雾
              </button>
            ) : null}
            <button
              onClick={() => setTab("alerts")}
              className="rounded-full bg-red-500 px-3 py-1 text-xs text-white"
            >
              🔥 映雪3-512 燃气超标
            </button>
            <button
              onClick={() => setTab("alerts")}
              className="rounded-full bg-red-500 px-3 py-1 text-xs text-white"
            >
              🌡️ 映雪3-408 高温预警(35.6°C)
            </button>
            <button
              onClick={() => setTab("alerts")}
              className="rounded-full bg-orange-500 px-3 py-1 text-xs text-white"
            >
              ⚠️ 映雪3-305 CO₂严重超标
            </button>
          </div>
        </div>
        <button
          onClick={() => setTab("alerts")}
          className="min-h-10 rounded bg-red-500 px-4 text-sm font-medium text-white hover:bg-red-600"
        >
          一键查看处理 →
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>楼栋统计与未接入房间沿用原型演示数据</span>
        <span className="flex items-center gap-2">
          <DemoBadge /> 映雪3-301 使用 <LiveBadge />
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard emoji="🏢" value="180" label="总宿舍数" change="▲ 较上月持平" />
        <StatCard
          emoji="📡"
          value={online ? "892" : "891"}
          label="在线设备"
          change={online ? "▲ 99.6% 在线率" : "▲ 99.5% 在线率"}
          tone="green"
        />
        <StatCard
          emoji="⚠️"
          value={12 + (smoke ? 1 : 0)}
          label="异常宿舍"
          change="▼ 较昨日减少3间"
          tone="amber"
        />
        <StatCard
          emoji="🔔"
          value={28 + (smoke ? 1 : 0)}
          label="今日告警数量"
          change="▼ 较昨日减少8条"
          tone="red"
        />
        <StatCard emoji="🚪" value="8" label="门禁异常记录" change="▼ 较昨日减少2次" />
      </div>

      <Card>
        <CardTitle
          trailing={
            <select
              aria-label="物联网状态宿舍"
              value={selectedDorm}
              onChange={(event) => setSelectedDorm(Number(event.target.value))}
              className="min-h-9 rounded border border-slate-300 bg-white px-3 text-sm"
            >
              <option value={0}>映雪3-301</option>
              {IOT_DEMO_DORMS.map((dorm, index) => (
                <option key={dorm.id} value={index + 1}>
                  {dorm.id}
                </option>
              ))}
            </select>
          }
        >
          📡 {selectedName} 物联网设备状态
        </CardTitle>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {demo ? (
            <DemoBadge />
          ) : (
            <>
              <LiveBadge />
              <span>{DEVICE_ID}</span>
              <span>· MQ-2 仅显示检测到烟雾/正常，不虚构 ppm</span>
            </>
          )}
        </div>
        <div className="grid gap-4 lg:grid-cols-[1fr_150px_150px]">
          <div className="overflow-hidden rounded-lg bg-[#17172a] font-mono text-xs text-white shadow-inner">
            <div className="bg-blue-600 py-2 text-center text-[11px] tracking-wider">= Env Monitor =</div>
            <div className="space-y-1 p-4 leading-6">
              <p>
                T:<span className="text-red-400">{formatValue(temperature, 1)}°C</span> H:
                <span className="text-emerald-400">{formatValue(humidity)}%</span>
              </p>
              <p>
                V:<span className="text-emerald-400">{formatValue(tvoc)}</span> C:
                <span className={Number(co2) > 1500 ? "text-red-400" : "text-emerald-400"}>
                  {formatValue(co2)}
                </span>
              </p>
              <p>
                F:
                <span className={Number(hcho) > 100 ? "text-red-400" : "text-emerald-400"}>
                  {formatValue(hcho)}
                </span>{" "}
                L:
                <span className="text-emerald-400">
                  {isDark === null || isDark === undefined ? "--" : isDark ? "DIM" : "BRT"}
                </span>
              </p>
              <p>
                M:
                <span className={selectedSmoke ? "text-red-400" : "text-slate-400"}>
                  {demo ? (selectedSmoke ? `${demo.mq2}ppm!` : "----") : selectedSmoke ? "SMOKE!" : "CLEAR"}
                </span>
              </p>
              <div className="mt-2 border-t border-dashed border-slate-600 pt-2">
                <strong
                  className={
                    airStatus.includes("BAD")
                      ? "text-red-400"
                      : airStatus.includes("FAIR")
                        ? "text-orange-400"
                        : "text-emerald-400"
                  }
                >
                  {airStatus}
                </strong>
              </div>
              <p className="text-center text-[9px] text-slate-500">ST7735 128x128 TFT</p>
            </div>
          </div>
          <div className="flex flex-col items-center justify-center rounded-lg bg-slate-100 p-4 text-center">
            <Lightbulb size={38} className={ledOn ? "fill-amber-300 text-amber-500" : "text-slate-400"} />
            <h3 className="my-2 font-semibold">LED 照明灯</h3>
            <button
              type="button"
              disabled={!demo}
              onClick={() => {
                setDemoLed((current) => ({ ...current, [selectedDorm]: !ledOn }));
                toast(`LED灯已${ledOn ? "关闭" : "开启"}（演示操作）`, "success");
              }}
              aria-label={demo ? "切换演示 LED" : "LED 只读状态"}
              className={cn(
                "relative h-6 w-11 rounded-full transition",
                ledOn ? "bg-blue-600" : "bg-slate-300",
                !demo && "cursor-default",
              )}
            >
              <span
                className={cn(
                  "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition",
                  ledOn ? "left-[22px]" : "left-0.5",
                )}
              />
            </button>
            <p className="mt-2 text-xs text-slate-500">
              {ledOn === null || ledOn === undefined ? "状态未知" : ledOn ? "已开启" : "已关闭"}
            </p>
            {!demo ? <p className="mt-1 text-[10px] text-slate-400">真实设备只读</p> : null}
          </div>
          <div className="flex flex-col items-center justify-center rounded-lg bg-slate-100 p-4 text-center">
            {buzzerOn ? (
              <Volume2 size={38} className="text-red-500" />
            ) : (
              <VolumeX size={38} className="text-slate-400" />
            )}
            <h3 className="my-2 font-semibold">蜂鸣器</h3>
            <Badge tone={buzzerOn ? "red" : "green"}>{buzzerOn ? "蜂鸣告警中" : "正常待机"}</Badge>
            <p className="mt-2 text-[11px] text-slate-500">
              {selectedSmoke
                ? demo
                  ? "MQ2燃气超标"
                  : "MQ-2 检测到烟雾"
                : Number(co2) > 1500
                  ? "CO₂超标"
                  : "无警报触发"}
            </p>
          </div>
        </div>
        <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
          <div className="rounded bg-slate-50 p-2">
            🪟 窗户：{windowOpen === null || windowOpen === undefined ? "未知" : windowOpen ? "开启" : "关闭"}
          </div>
          <div className="rounded bg-slate-50 p-2">
            💡 明暗：{isDark === null || isDark === undefined ? "未知" : isDark ? "暗" : "亮"}
          </div>
          <div className="rounded bg-slate-50 p-2">🌫️ 烟雾：{selectedSmoke ? "检测到烟雾" : "正常"}</div>
          <div className="rounded bg-slate-50 p-2">
            📶 状态：{demo ? (demo.deviceOnline ? "在线" : "离线") : online ? "在线" : "离线"}
          </div>
        </div>
      </Card>

      <Card>
        <CardTitle trailing={<SmallButton onClick={() => setTab("alerts")}>查看全部 →</SmallButton>}>
          📋 最近告警记录
        </CardTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="p-3">宿舍号</th>
                <th className="p-3">异常类型</th>
                <th className="p-3">触发时间</th>
                <th className="p-3">持续时长</th>
                <th className="p-3">当前值</th>
                <th className="p-3">状态</th>
                <th className="p-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {liveSmokeEvents.slice(0, 1).map((event) => (
                <tr key={event.id} className="border-t">
                  <td className="p-3 font-semibold">
                    {DORM_NAME} <LiveBadge />
                  </td>
                  <td className="p-3">
                    <Badge tone={event.type === "smoke.detected" ? "red" : "green"}>
                      {event.type === "smoke.detected" ? "检测到烟雾" : "烟雾解除"}
                    </Badge>
                  </td>
                  <td className="p-3">{formatTime(event.created_at)}</td>
                  <td className="p-3">实时</td>
                  <td className="p-3 font-semibold">
                    {event.type === "smoke.detected" ? "检测到烟雾" : "正常"}
                  </td>
                  <td className="p-3">
                    <Badge tone={event.acknowledged_at ? "green" : "red"}>
                      {event.acknowledged_at ? "已确认" : "未处理"}
                    </Badge>
                  </td>
                  <td className="p-3">
                    <SmallButton onClick={() => setTab("alerts")}>处理</SmallButton>
                  </td>
                </tr>
              ))}
              {alerts.slice(0, 5).map((alert) => (
                <tr key={`${alert.dorm}-${alert.type}`} className="border-t border-slate-100">
                  <td className="p-3 font-semibold">
                    {alert.dorm} <DemoBadge compact />
                  </td>
                  <td className="p-3">
                    <Badge
                      tone={
                        alert.level === "三级高危" ? "red" : alert.level === "二级中度" ? "amber" : "blue"
                      }
                    >
                      {alert.type}
                    </Badge>
                  </td>
                  <td className="p-3">{alert.time}</td>
                  <td className="p-3">{alert.duration}</td>
                  <td className={cn("p-3 font-semibold", alert.level === "三级高危" && "text-red-500")}>
                    {alert.value}
                  </td>
                  <td className="p-3">
                    <Badge tone={alert.status === "未处理" ? "red" : "green"}>{alert.status}</Badge>
                  </td>
                  <td className="p-3">
                    <SmallButton onClick={() => handleAlert(alert.dorm)}>处理</SmallButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function ScorePanel({ toast }: { toast: (message: string, tone?: "success" | "info" | "danger") => void }) {
  const sorted = useMemo(() => [...DEMO_DORMS].sort((a, b) => b.score - a.score), []);
  const red = sorted.slice(0, 5);
  const black = sorted.slice(-5).reverse();
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardTitle
          trailing={
            <SmallButton onClick={() => toast("红黑榜 PDF 导出为演示功能", "info")}>
              <Download size={14} className="mr-1 inline" />
              导出红黑榜PDF
            </SmallButton>
          }
        >
          🏆 文明宿舍红黑榜（月度）
        </CardTitle>
        <div className="mb-3 flex items-center gap-2 text-xs text-slate-500">
          <DemoBadge />
          保留原型评分数据
        </div>
        <p className="mb-2 font-semibold text-red-500">🔴 红榜（优秀宿舍）</p>
        {red.map((dorm, index) => (
          <div key={dorm.id} className="flex items-center gap-3 border-b border-slate-100 py-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium">{dorm.id}</p>
              <p className="truncate text-xs text-slate-500">
                通风{dorm.scoreDetail.ventilation} | 节电{dorm.scoreDetail.energy} | 安全
                {dorm.scoreDetail.safety} | 作息{dorm.scoreDetail.health}
              </p>
            </div>
            <strong className="text-emerald-600">{dorm.score}分</strong>
          </div>
        ))}
        <p className="mb-2 mt-4 font-semibold text-slate-500">⚫ 黑榜（待改进宿舍）</p>
        {black.map((dorm, index) => (
          <div key={dorm.id} className="flex items-center gap-3 border-b border-slate-100 py-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-300 text-xs font-bold text-slate-700">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium">{dorm.id}</p>
              <p className="truncate text-xs text-slate-500">
                通风{dorm.scoreDetail.ventilation} | 节电{dorm.scoreDetail.energy} | 安全
                {dorm.scoreDetail.safety} | 作息{dorm.scoreDetail.health}
              </p>
            </div>
            <strong className="text-red-500">{dorm.score}分</strong>
          </div>
        ))}
      </Card>
      <Card>
        <CardTitle trailing={<DemoBadge />}>📊 评分维度分布</CardTitle>
        <div className="h-[420px] min-h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={RADAR_DATA} outerRadius="70%">
              <PolarGrid stroke="#e5e7eb" />
              <PolarAngleAxis dataKey="subject" tick={{ fill: "#64748b", fontSize: 12 }} />
              <Radar
                name="红榜平均"
                dataKey="red"
                stroke="#f53f3f"
                fill="#f53f3f"
                fillOpacity={0.1}
                isAnimationActive={false}
              />
              <Radar
                name="黑榜平均"
                dataKey="black"
                stroke="#86909c"
                fill="#86909c"
                fillOpacity={0.1}
                isAnimationActive={false}
              />
              <Radar
                name="全楼平均"
                dataKey="average"
                stroke="#165dff"
                fill="#165dff"
                fillOpacity={0.1}
                isAnimationActive={false}
              />
              <Legend />
              <Tooltip />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

function AlertsPanel({
  live,
  alerts,
  handleAlert,
  toast,
}: {
  live: ReturnType<typeof useDeviceLive>;
  alerts: DemoAlert[];
  handleAlert: (dorm: string) => void;
  toast: (message: string, tone?: "success" | "info" | "danger") => void;
}) {
  const [level, setLevel] = useState("all");
  const [status, setStatus] = useState("all");
  const smoke = live.latest?.telemetry?.sensors.smoke_detected === true;
  const events = live.ledger.filter((event) => event.type.startsWith("smoke."));
  const filtered = alerts.filter(
    (alert) => (level === "all" || alert.level === level) && (status === "all" || alert.status === status),
  );
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard emoji="⚠️" value="15" label="一级轻微预警" change="高湿 / 轻度CO₂超标" tone="amber" />
        <StatCard emoji="🔶" value="8" label="二级中度预警" change="甲醛超标" tone="amber" />
        <StatCard
          emoji="🚨"
          value={5 + (smoke ? 1 : 0)}
          label="三级高危告警"
          change="燃气 / 烟雾 / 高温"
          tone="red"
        />
      </div>
      <Card>
        <CardTitle
          trailing={
            <div className="flex flex-wrap gap-2">
              <select
                aria-label="告警等级"
                value={level}
                onChange={(event) => setLevel(event.target.value)}
                className="min-h-9 rounded border px-2 text-sm"
              >
                <option value="all">全部等级</option>
                <option>一级轻微</option>
                <option>二级中度</option>
                <option>三级高危</option>
              </select>
              <select
                aria-label="告警状态"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="min-h-9 rounded border px-2 text-sm"
              >
                <option value="all">全部状态</option>
                <option>未处理</option>
                <option>已处置</option>
              </select>
              <SmallButton onClick={() => toast("告警导出为演示功能", "info")}>📥 导出告警</SmallButton>
            </div>
          }
        >
          📋 告警台账列表
        </CardTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1100px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                {[
                  "宿舍号",
                  "异常类型",
                  "告警等级",
                  "触发时间",
                  "持续时长",
                  "当前值",
                  "阈值",
                  "处理状态",
                  "操作",
                ].map((title) => (
                  <th key={title} className="p-3">
                    {title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id} className="border-t">
                  <td className="p-3 font-semibold">
                    {DORM_NAME} <LiveBadge />
                  </td>
                  <td className="p-3">{event.type === "smoke.detected" ? "检测到烟雾" : "烟雾解除"}</td>
                  <td className="p-3">
                    <Badge tone={event.type === "smoke.detected" ? "red" : "green"}>
                      {event.type === "smoke.detected" ? "三级高危" : "解除"}
                    </Badge>
                  </td>
                  <td className="p-3">{formatTime(event.created_at)}</td>
                  <td className="p-3">实时</td>
                  <td className="p-3 font-semibold">
                    {event.type === "smoke.detected" ? "检测到烟雾" : "正常"}
                  </td>
                  <td className="p-3">布尔检测</td>
                  <td className="p-3">
                    <Badge tone={event.acknowledged_at ? "green" : "red"}>
                      {event.acknowledged_at ? "已确认" : "未处理"}
                    </Badge>
                  </td>
                  <td className="p-3">
                    <SmallButton
                      onClick={() => toast("真实烟雾事件请在宿舍环境页确认", "info")}
                      danger={!event.acknowledged_at}
                    >
                      立即处理
                    </SmallButton>
                  </td>
                </tr>
              ))}
              {filtered.map((alert) => (
                <tr key={`${alert.dorm}-${alert.type}`} className="border-t border-slate-100">
                  <td className="p-3 font-semibold">
                    {alert.dorm} <DemoBadge compact />
                  </td>
                  <td className="p-3">{alert.type}</td>
                  <td className="p-3">
                    <Badge
                      tone={
                        alert.level === "三级高危" ? "red" : alert.level === "二级中度" ? "amber" : "blue"
                      }
                    >
                      {alert.level}
                    </Badge>
                  </td>
                  <td className="p-3">{alert.time}</td>
                  <td className="p-3">{alert.duration}</td>
                  <td className="p-3 font-semibold">{alert.value}</td>
                  <td className="p-3">{alert.threshold}</td>
                  <td className="p-3">
                    <Badge tone={alert.status === "未处理" ? "red" : "green"}>{alert.status}</Badge>
                  </td>
                  <td className="p-3">
                    {alert.status === "未处理" ? (
                      <SmallButton danger onClick={() => handleAlert(alert.dorm)}>
                        立即处理
                      </SmallButton>
                    ) : (
                      <SmallButton onClick={() => toast(`${alert.dorm} 演示告警详情`, "info")}>
                        查看详情
                      </SmallButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card>
        <CardTitle trailing={<DemoBadge />}>🔇 告警降噪设置</CardTitle>
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-3 font-semibold">屏蔽时段设置</h3>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-sm text-slate-600">
                开始时间
                <input
                  type="time"
                  defaultValue="23:00"
                  className="mt-1 min-h-10 w-full rounded border px-3"
                />
              </label>
              <label className="text-sm text-slate-600">
                结束时间
                <input
                  type="time"
                  defaultValue="06:00"
                  className="mt-1 min-h-10 w-full rounded border px-3"
                />
              </label>
            </div>
            <p className="mt-3 text-xs text-slate-500">※ 屏蔽时段内仅记录三级高危告警，一二级告警静默</p>
          </div>
          <div>
            <h3 className="mb-3 font-semibold">告警阈值调整</h3>
            <div className="grid grid-cols-2 gap-3">
              {[
                ["温度上限(°C)", "35"],
                ["湿度上限(%)", "85"],
                ["CO₂上限(ppm)", "1500"],
                ["MQ2燃气(ppm)", "500"],
                ["甲醛上限(mg/m³)", "0.1"],
                ["TVOC上限(mg/m³)", "0.6"],
              ].map(([label, value]) => (
                <label key={label} className="text-sm text-slate-600">
                  {label}
                  <input
                    type="number"
                    defaultValue={value}
                    className="mt-1 min-h-10 w-full rounded border px-3"
                  />
                </label>
              ))}
            </div>
            <button
              onClick={() => toast("告警阈值已保存（演示设置）", "success")}
              className="mt-3 min-h-10 rounded bg-blue-600 px-4 text-sm text-white"
            >
              💾 保存设置
            </button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function notificationStatus(notification: NotificationOut) {
  const labels: Record<NotificationOut["voice_status"], string> = {
    not_requested: "文字已下发",
    unavailable: "文字已下发，语音不可用",
    pending: "语音待设备确认",
    executed: "文字及语音均已送达",
    rejected: "文字已下发，语音被拒绝",
    failed: "文字已下发，语音失败",
  };
  return labels[notification.voice_status];
}

function MessagesPanel({
  live,
  toast,
}: {
  live: ReturnType<typeof useDeviceLive>;
  toast: (message: string, tone?: "success" | "info" | "danger") => void;
}) {
  const [target, setTarget] = useState("room301");
  const [customDorm, setCustomDorm] = useState("");
  const [content, setContent] = useState(
    "同学们请注意，近期天气潮湿，请及时开窗通风，保持宿舍空气清新。如有不适请及时联系辅导员。",
  );
  const [voice, setVoice] = useState(true);
  const [feedback, setFeedback] = useState("");
  const [localHistory, setLocalHistory] = useState<DemoNotification[]>([]);
  const voiceBytes = approximateGb2312Bytes(content.trim());
  const targetLabels: Record<string, string> = {
    room301: "映雪3-301（真实接入）",
    all: "全部宿舍（映雪3号楼整栋）",
    floor3: "3层(映雪3-301~330)",
    floor4: "4层(映雪3-401~430)",
    floor5: "5层(映雪3-501~530)",
    custom: customDorm.trim() || "自定义宿舍",
  };
  const isRealTarget =
    target === "room301" || (target === "custom" && ["映雪3-301", "301"].includes(customDorm.trim()));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFeedback("");
    if (!content.trim()) return setFeedback("请输入通知内容");
    if (voice && voiceBytes > 220) return setFeedback("语音内容超过 SYN6288 的 220 字节限制");
    if (isRealTarget) {
      try {
        const result = await live.sendNotification(content, voice);
        setFeedback(`通知已下发到${DORM_NAME}：${notificationStatus(result)}`);
        toast("通知已真实下发到映雪3-301", "success");
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : "通知下发失败");
      }
      return;
    }
    const targetLabel = targetLabels[target];
    const count =
      target === "all"
        ? 178
        : target.startsWith("floor")
          ? 30
          : Math.max(customDorm.split(",").filter(Boolean).length, 1);
    setLocalHistory((current) => [
      {
        id: `demo-${Date.now()}`,
        time: new Date().toLocaleString("zh-CN", { hour12: false }),
        target: targetLabel,
        content: content.trim(),
        status: "演示已送达",
        count,
      },
      ...current,
    ]);
    setFeedback(`演示通知已下发到“${targetLabel}”；未调用真实后端。`);
    toast("演示通知已下发", "success");
  }

  function preview() {
    if (!content.trim()) return setFeedback("请先输入通知内容");
    if (!("speechSynthesis" in window)) return setFeedback("当前浏览器不支持语音合成预览");
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(content);
    utterance.lang = "zh-CN";
    window.speechSynthesis.speak(utterance);
    setFeedback("正在使用浏览器语音试听；真实播报由映雪3-301 的 SYN6288 完成。");
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardTitle>📢 一键下发通知</CardTitle>
          <form onSubmit={submit} className="space-y-4">
            <label className="block text-sm font-medium text-slate-700">
              目标宿舍
              <select
                aria-label="目标宿舍"
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                className="mt-2 min-h-11 w-full rounded border border-slate-300 bg-white px-3"
              >
                <option value="room301">映雪3-301（真实接入）</option>
                <option value="all">全部宿舍（映雪3号楼整栋）</option>
                <option value="floor3">3层(映雪3-301~330)</option>
                <option value="floor4">4层(映雪3-401~430)</option>
                <option value="floor5">5层(映雪3-501~530)</option>
                <option value="custom">自定义宿舍号</option>
              </select>
            </label>
            {target === "custom" ? (
              <input
                aria-label="自定义宿舍号"
                value={customDorm}
                onChange={(event) => setCustomDorm(event.target.value)}
                placeholder="输入宿舍号，多个用逗号分隔，如：映雪3-301,映雪3-408"
                className="min-h-11 w-full rounded border border-slate-300 px-3 text-sm"
                autoFocus
              />
            ) : null}
            <p
              className={cn(
                "rounded p-2 text-xs",
                isRealTarget ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700",
              )}
            >
              {isRealTarget
                ? "该目标会持久化并通过 WebSocket/MQTT 真实下发。"
                : "该目标保留原型演示效果，不会向未接入房间发送真实通知。"}
            </p>
            <div>
              <div className="flex items-center justify-between gap-3">
                <label htmlFor="notification-content" className="text-sm font-medium text-slate-700">
                  通知内容
                </label>
                <label className="flex min-h-11 items-center gap-2 text-sm text-slate-600">
                  <input
                    aria-label="语音播报"
                    type="checkbox"
                    checked={voice}
                    onChange={(event) => setVoice(event.target.checked)}
                    className="h-4 w-4 accent-blue-600"
                  />
                  语音播报
                </label>
              </div>
              <textarea
                id="notification-content"
                aria-label="通知内容"
                value={content}
                onChange={(event) => setContent(event.target.value)}
                maxLength={500}
                rows={4}
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2.5 text-sm leading-6 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
              />
              <p
                className={cn("mt-1 text-xs", voice && voiceBytes > 220 ? "text-red-600" : "text-slate-500")}
              >
                {content.length}/500 字符{voice ? ` · 约 ${voiceBytes}/220 GB2312 字节` : ""}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                disabled={live.notificationSending}
                className="min-h-11 rounded bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                📡 {live.notificationSending ? "正在下发…" : "立即下发"}
              </button>
              <button
                type="button"
                onClick={preview}
                className="min-h-11 rounded border border-blue-600 px-4 text-sm font-medium text-blue-600"
              >
                🔊 试听预览
              </button>
            </div>
            <p className="min-h-5 text-sm text-slate-600" role="status" aria-live="polite">
              {feedback}
            </p>
          </form>
        </Card>
        <Card>
          <CardTitle>📋 通知模板</CardTitle>
          <div className="space-y-2">
            {TEMPLATES.map((template) => (
              <button
                key={template.title}
                type="button"
                onClick={() => {
                  setContent(template.content);
                  toast("模板已加载", "info");
                }}
                className="flex min-h-20 w-full gap-3 rounded-lg border border-slate-200 p-3 text-left transition hover:border-blue-300 hover:bg-blue-50"
              >
                <template.icon className="mt-0.5 shrink-0 text-blue-600" size={19} />
                <span>
                  <strong className="text-sm">{template.title}</strong>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">{template.content}</span>
                </span>
              </button>
            ))}
          </div>
        </Card>
      </div>
      <Card>
        <CardTitle>📜 历史通知记录</CardTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="p-3">下发时间</th>
                <th className="p-3">目标宿舍</th>
                <th className="p-3">播报内容</th>
                <th className="p-3">发送状态</th>
                <th className="p-3">送达数</th>
              </tr>
            </thead>
            <tbody>
              {live.notifications.map((notification) => (
                <tr key={notification.id} className="border-t">
                  <td className="whitespace-nowrap p-3">{formatTime(notification.created_at)}</td>
                  <td className="p-3">
                    {DORM_NAME} <LiveBadge />
                  </td>
                  <td className="max-w-xl p-3">{notification.content}</td>
                  <td className="p-3">
                    <Badge
                      tone={
                        ["unavailable", "rejected", "failed"].includes(notification.voice_status)
                          ? "amber"
                          : notification.voice_status === "executed"
                            ? "green"
                            : "blue"
                      }
                    >
                      {notificationStatus(notification)}
                    </Badge>
                  </td>
                  <td className="p-3">1间</td>
                </tr>
              ))}
              {[...localHistory, ...DEMO_NOTIFICATIONS].map((notification) => (
                <tr key={notification.id} className="border-t border-slate-100">
                  <td className="whitespace-nowrap p-3">{notification.time}</td>
                  <td className="p-3">
                    {notification.target} <DemoBadge compact />
                  </td>
                  <td className="max-w-xl p-3">{notification.content}</td>
                  <td className="p-3">
                    <Badge tone="green">{notification.status}</Badge>
                  </td>
                  <td className="p-3">{notification.count}间</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function SettingsPanel({
  toast,
}: {
  toast: (message: string, tone?: "success" | "info" | "danger") => void;
}) {
  const [tab, setTab] = useState<SettingsTab>("accounts");
  const [cleanup, setCleanup] = useState(true);
  const [anonymous, setAnonymous] = useState(true);
  return (
    <div className="space-y-4">
      <div className="flex gap-1 overflow-x-auto border-b-2 border-slate-200">
        {[
          ["accounts", "权限管理"],
          ["maintenance", "设备运维工单"],
          ["privacy", "隐私设置"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id as SettingsTab)}
            className={cn(
              "min-h-11 shrink-0 border-b-2 px-4 text-sm",
              tab === id
                ? "-mb-0.5 border-blue-600 font-medium text-blue-600"
                : "border-transparent text-slate-500",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "accounts" ? (
        <Card>
          <CardTitle
            trailing={
              <SmallButton onClick={() => toast("新增账号为演示功能", "info")}>+ 新增账号</SmallButton>
            }
          >
            👥 角色权限管理
          </CardTitle>
          <div className="mb-3">
            <DemoBadge />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  {["账号", "姓名", "角色", "管理范围", "权限详情", "状态", "操作"].map((title) => (
                    <th key={title} className="p-3">
                      {title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ["zhang_fdy", "张老师", "辅导员", "映雪3号楼 1-6层", "全部功能"],
                  ["li_sg", "李阿姨", "宿管", "映雪3号楼 1-3层", "仅安全告警"],
                  ["wang_ld", "王主任", "领导", "全校", "仅统计看板"],
                ].map((row) => (
                  <tr key={row[0]} className="border-t">
                    {row.map((cell, index) => (
                      <td key={cell} className="p-3">
                        {index === 2 ? (
                          <Badge tone={index === 2 && row[2] === "宿管" ? "amber" : "blue"}>{cell}</Badge>
                        ) : (
                          cell
                        )}
                      </td>
                    ))}
                    <td className="p-3">
                      <Badge tone="green">正常</Badge>
                    </td>
                    <td className="p-3">
                      <SmallButton onClick={() => toast(`${row[1]}账号编辑为演示功能`, "info")}>
                        编辑
                      </SmallButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
      {tab === "maintenance" ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard emoji="🔧" value="5" label="离线/故障设备" tone="red" />
            <StatCard emoji="⏳" value="3" label="维修中" tone="amber" />
            <StatCard emoji="✅" value="12" label="本月已修复" tone="green" />
          </div>
          <Card>
            <CardTitle trailing={<DemoBadge />}>🔧 设备运维工单列表</CardTitle>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1000px] text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    {[
                      "工单号",
                      "宿舍号",
                      "设备类型",
                      "故障描述",
                      "报修时间",
                      "维修状态",
                      "维修人员",
                      "操作",
                    ].map((title) => (
                      <th key={title} className="p-3">
                        {title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MAINTENANCE_ORDERS.map((order) => (
                    <tr key={order.id} className="border-t">
                      <td className="p-3">{order.id}</td>
                      <td className="p-3">{order.dorm}</td>
                      <td className="p-3">{order.device}</td>
                      <td className="p-3">{order.desc}</td>
                      <td className="p-3">{order.time}</td>
                      <td className="p-3">
                        <Badge tone={order.status === "待维修" ? "red" : "amber"}>{order.status}</Badge>
                      </td>
                      <td className="p-3">{order.staff}</td>
                      <td className="p-3">
                        <SmallButton onClick={() => toast(`${order.id}进度为演示数据`, "info")}>
                          查看进度
                        </SmallButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}
      {tab === "privacy" ? (
        <Card>
          <CardTitle trailing={<DemoBadge />}>🔒 隐私与数据安全设置</CardTitle>
          <div className="divide-y divide-slate-100">
            <div className="flex items-center justify-between gap-4 py-4">
              <div>
                <strong className="text-sm">传感器数据自动清理</strong>
                <p className="mt-1 text-xs text-slate-500">每日凌晨3:00自动清除前一日冗余传感日志</p>
              </div>
              <Toggle checked={cleanup} onChange={setCleanup} label="传感器数据自动清理" />
            </div>
            <div className="flex items-center justify-between gap-4 py-4">
              <div>
                <strong className="text-sm">匿名化行为数据</strong>
                <p className="mt-1 text-xs text-slate-500">仅展示宿舍级统计数据，不关联具体学生身份信息</p>
              </div>
              <Toggle checked={anonymous} onChange={setAnonymous} label="匿名化行为数据" />
            </div>
            <div className="flex items-center justify-between gap-4 py-4">
              <strong className="text-sm">数据保留周期</strong>
              <select aria-label="数据保留周期" className="min-h-10 rounded border px-3">
                <option>30天</option>
                <option>60天</option>
                <option>90天</option>
                <option>180天</option>
              </select>
            </div>
          </div>
          <p className="mt-4 text-xs text-slate-500">※ 传感日志超期自动清除。匿名化统计数据保留不受影响。</p>
        </Card>
      ) : null}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn("relative h-6 w-11 shrink-0 rounded-full", checked ? "bg-blue-600" : "bg-slate-300")}
    >
      <span
        className={cn(
          "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition",
          checked ? "left-[22px]" : "left-0.5",
        )}
      />
    </button>
  );
}

export function AdminDashboard() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [alerts, setAlerts] = useState(DEMO_ALERTS);
  const [toastState, setToastState] = useState<{
    message: string;
    tone: "success" | "info" | "danger";
  } | null>(null);
  const live = useDeviceLive(DEVICE_ID);
  const smoke = live.latest?.telemetry?.sensors.smoke_detected === true;
  const unhandled = alerts.filter((alert) => alert.status === "未处理").length + (smoke ? 1 : 0);

  useEffect(() => {
    if (!toastState) return;
    const timeout = window.setTimeout(() => setToastState(null), 3500);
    return () => window.clearTimeout(timeout);
  }, [toastState]);

  function toast(message: string, tone: "success" | "info" | "danger" = "info") {
    setToastState({ message, tone });
  }

  function handleAlert(dorm: string) {
    setAlerts((current) =>
      current.map((alert) => (alert.dorm === dorm ? { ...alert, status: "已处置" } : alert)),
    );
    toast(`${dorm} 演示告警已处理`, "success");
  }

  return (
    <div className="min-h-dvh bg-[#f4f6f9] text-slate-800 lg:grid lg:grid-cols-[220px_1fr]">
      <a
        href="#admin-main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2"
      >
        跳到主要内容
      </a>
      <aside className="bg-gradient-to-b from-[#0d2b6b] to-[#173959] text-white lg:sticky lg:top-0 lg:h-dvh">
        <div className="flex items-center gap-3 border-b border-white/10 px-4 py-5">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 text-xl">
            🏠
          </span>
          <div>
            <p className="font-semibold">智宿云</p>
            <p className="text-[11px] text-white/65">辅导员管理平台</p>
          </div>
        </div>
        <nav
          aria-label="管理平台导航"
          className="flex gap-1 overflow-x-auto p-2 lg:block lg:space-y-1 lg:p-0 lg:py-3"
        >
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? "page" : undefined}
              className={cn(
                "flex min-h-12 shrink-0 items-center gap-3 px-4 text-sm transition lg:w-full lg:px-5",
                tab === item.id
                  ? "bg-blue-600/50 text-white lg:border-l-4 lg:border-blue-500"
                  : "text-white/70 hover:bg-white/10 hover:text-white",
              )}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.id === "alerts" ? (
                <span className="ml-auto rounded-full bg-red-500 px-2 py-0.5 text-[11px] text-white">
                  {unhandled}
                </span>
              ) : null}
            </button>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-2 shadow-sm backdrop-blur sm:px-6">
          <div className="flex flex-wrap items-center gap-4">
            <select
              aria-label="管理班级"
              className="min-h-10 rounded border border-slate-300 bg-white px-3 text-sm"
            >
              <option>计算机学院 — 2023级软件工程1-3班</option>
              <option>计算机学院 — 2023级软件工程4-6班</option>
              <option>计算机学院 — 2022级计算机科学1-2班</option>
            </select>
            <span className="text-xs text-slate-500">
              分管楼栋：<strong>映雪3号楼</strong>（1-6层）
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              aria-label="消息通知快捷入口"
              onClick={() => setTab("messages")}
              className="relative flex h-9 w-9 items-center justify-center rounded-full bg-slate-100"
            >
              <Mail size={16} />
              <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500" />
            </button>
            <button
              aria-label="告警中心快捷入口"
              onClick={() => setTab("alerts")}
              className="relative flex h-9 w-9 items-center justify-center rounded-full bg-slate-100"
            >
              <Bell size={16} />
              <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500" />
            </button>
            <SmallButton onClick={() => toast("全量报表导出为演示功能", "info")}>
              <Download size={14} className="mr-1 inline" />
              导出报表
            </SmallButton>
            <span className="hidden text-xs text-slate-600 xl:inline">👤 张辅导员 | 超级管理员</span>
            <span
              className={cn(
                "hidden items-center gap-1 rounded-full px-2 py-1 text-[11px] sm:inline-flex",
                live.socketState === "live" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700",
              )}
            >
              {live.socketState === "live" ? <Wifi size={12} /> : <WifiOff size={12} />}
              {live.socketState === "live" ? "实时连接" : "正在重连"}
            </span>
            <Link
              href="/"
              className="min-h-9 rounded border border-blue-600 px-3 py-2 text-xs font-medium text-blue-600"
            >
              宿舍端
            </Link>
          </div>
        </header>
        <main id="admin-main" className="p-4 sm:p-6">
          <h1 className="sr-only">{NAV_ITEMS.find((item) => item.id === tab)?.label}</h1>
          {live.error ? (
            <div className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              301 实时连接提示：{live.error}；原型演示内容不受影响。
            </div>
          ) : null}
          {tab === "dashboard" ? (
            <DashboardPanel
              live={live}
              alerts={alerts}
              setTab={setTab}
              handleAlert={handleAlert}
              toast={toast}
            />
          ) : tab === "score" ? (
            <ScorePanel toast={toast} />
          ) : tab === "alerts" ? (
            <AlertsPanel live={live} alerts={alerts} handleAlert={handleAlert} toast={toast} />
          ) : tab === "messages" ? (
            <MessagesPanel live={live} toast={toast} />
          ) : (
            <SettingsPanel toast={toast} />
          )}
        </main>
      </div>
      {toastState ? (
        <div
          role="status"
          aria-live="polite"
          className={cn(
            "fixed right-4 top-20 z-50 max-w-sm rounded-lg border bg-white px-4 py-3 text-sm shadow-xl",
            toastState.tone === "danger"
              ? "border-red-300 text-red-700"
              : toastState.tone === "success"
                ? "border-emerald-300 text-emerald-700"
                : "border-blue-300 text-blue-700",
          )}
        >
          {toastState.tone === "danger" ? "🚨" : toastState.tone === "success" ? "✅" : "ℹ️"}{" "}
          {toastState.message}
        </div>
      ) : null}
    </div>
  );
}
