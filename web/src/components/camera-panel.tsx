"use client";

import { useState } from "react";
import {
  Activity,
  BrainCircuit,
  Camera,
  CameraOff,
  Loader2,
  PersonStanding,
  ScanSearch,
  TimerReset,
} from "lucide-react";
import { Panel } from "@/components/panel";
import { Switch } from "@/components/ui/switch";
import type { LatestState } from "@/lib/api";
import { formatRelative } from "@/lib/utils";

export function CameraPanel({
  image,
  pose,
  onAnalyze,
  onAiAnalyze,
  aiAnalyzing,
  visionCapability,
  autopilot,
  onUpdateAutomation,
  className,
}: {
  image: { url: string; created_at: string } | null | undefined;
  pose: LatestState["pose"] | undefined;
  onAnalyze: () => void;
  onAiAnalyze: () => void;
  aiAnalyzing: boolean;
  visionCapability: "unknown" | "supported" | "unsupported";
  autopilot: LatestState["autopilot"];
  onUpdateAutomation: (values: {
    vision_interval_enabled?: boolean;
    vision_interval_seconds?: number;
    sedentary_threshold_seconds?: number;
  }) => void;
  className?: string;
}) {
  const [showAnnotated, setShowAnnotated] = useState(true);
  const showingAnnotated = showAnnotated && Boolean(pose?.annotated_image_url);
  const imageUrl = showingAnnotated ? pose?.annotated_image_url : image?.url;
  const capturedAt = showingAnnotated ? pose?.created_at : image?.created_at;
  const coverageLabel =
    pose?.body_coverage === "full_body"
      ? "全身"
      : pose?.body_coverage === "upper_body"
        ? "上半身"
        : "关键点不足";
  const postureLabel = !pose
    ? "等待姿态识别"
    : !pose.human_present
      ? "无人时不评估"
      : pose.posture_code === "unknown"
        ? pose.label === "姿态确认中"
          ? "姿态确认中"
          : "姿态暂不可判"
        : pose.label;
  return (
    <Panel
      title="现场画面与姿态"
      icon={<Camera size={17} />}
      className={className}
      actions={
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onAnalyze}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-sm text-ink2 transition-colors hover:border-accent hover:text-ink"
          >
            <ScanSearch size={13} /> 重新识别
          </button>
          <button
            type="button"
            onClick={onAiAnalyze}
            disabled={aiAnalyzing || visionCapability === "unsupported"}
            aria-describedby={visionCapability === "unsupported" ? "vision-unsupported" : undefined}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/5 px-3 text-sm text-accent transition-colors hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {aiAnalyzing ? <Loader2 size={13} className="animate-spin" /> : <BrainCircuit size={13} />}
            {aiAnalyzing ? "分析中…" : "AI 精准分析"}
          </button>
        </div>
      }
    >
      {imageUrl ? (
        <figure
          key={imageUrl}
          className="relative aspect-video animate-flash-ring overflow-hidden rounded-xl border border-line bg-black/70"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt={showAnnotated ? "设备姿态骨架图" : "设备最新原始画面"}
            className="h-full w-full object-contain"
          />
          <figcaption className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/75 to-transparent px-3 pb-2.5 pt-8 text-xs text-white/90">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-white" aria-hidden />
              OV2640
            </span>
            <span>更新于 {formatRelative(capturedAt)}</span>
          </figcaption>
        </figure>
      ) : (
        <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line text-ink3">
          <CameraOff size={24} />
          <p className="text-xs">等待设备上传画面</p>
        </div>
      )}
      <div className="mt-3 grid gap-2 sm:grid-cols-2" aria-live="polite">
        <div className="rounded-xl border border-line bg-raised px-3 py-2.5">
          <div className="flex items-center justify-between gap-2 text-xs text-ink3">
            <span className="inline-flex items-center gap-1.5">
              <PersonStanding size={14} className={pose?.human_present ? "text-good" : "text-ink3"} />
              人体存在
            </span>
            <span className="tnum">{pose ? `${Math.round(pose.presence_confidence * 100)}%` : "--"}</span>
          </div>
          <p className={`mt-1 text-sm font-medium ${pose?.human_present ? "text-good" : "text-ink2"}`}>
            {pose ? (pose.human_present ? "检测到人体" : "未检测到人体") : "等待人体检测"}
          </p>
        </div>
        <div className="rounded-xl border border-line bg-raised px-3 py-2.5">
          <div className="flex items-center justify-between gap-2 text-xs text-ink3">
            <span className="inline-flex items-center gap-1.5">
              <Activity
                size={14}
                className={pose?.posture_code !== "unknown" ? "text-accent" : "text-ink3"}
              />
              坐姿状态
            </span>
            <span className="inline-flex items-center gap-1.5">
              {pose && !pose.posture_fresh && pose.posture_code !== "unknown" ? (
                <span className="rounded bg-warn/10 px-1.5 py-0.5 text-warn">短暂保持</span>
              ) : null}
              <span className="tnum">
                {pose?.human_present ? `${Math.round(pose.posture_confidence * 100)}%` : "--"}
              </span>
            </span>
          </div>
          <p className="mt-1 text-sm font-medium text-ink2">{postureLabel}</p>
          {pose?.human_present ? (
            <p className="mt-0.5 text-[11px] text-ink3">识别范围：{coverageLabel}</p>
          ) : null}
        </div>
      </div>
      <div className="mt-2 flex justify-end">
        {pose?.annotated_image_url ? (
          <div className="flex rounded-md border border-line bg-raised p-0.5" aria-label="画面类型">
            <button
              type="button"
              onClick={() => setShowAnnotated(false)}
              className={`min-h-8 rounded px-2.5 text-xs ${!showAnnotated ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}
            >
              原图
            </button>
            <button
              type="button"
              onClick={() => setShowAnnotated(true)}
              className={`min-h-8 rounded px-2.5 text-xs ${showAnnotated ? "bg-surface text-ink shadow-sm" : "text-ink3"}`}
            >
              骨架图
            </button>
          </div>
        ) : null}
      </div>
      {visionCapability === "unsupported" ? (
        <p
          id="vision-unsupported"
          tabIndex={0}
          className="mt-3 rounded-lg bg-alert/10 px-3 py-2 text-xs text-alert"
        >
          当前模型不支持图片分析，请更换视觉模型。
        </p>
      ) : null}
      <div className="mt-3 rounded-xl border border-line bg-raised p-3">
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 text-sm font-medium text-ink2">
            <TimerReset size={14} className="text-accent" /> 定时视觉分析
          </span>
          <Switch
            checked={autopilot?.vision_interval_enabled ?? false}
            disabled={visionCapability === "unsupported"}
            onCheckedChange={(value) => onUpdateAutomation({ vision_interval_enabled: value })}
            aria-label="定时视觉分析开关"
          />
        </div>
        <label className="mt-3 flex items-center justify-between gap-3 text-xs text-ink3">
          自动分析间隔
          <span className="flex items-center gap-2">
            <input
              key={`vision-${autopilot?.vision_interval_seconds}`}
              type="number"
              min={30}
              max={3600}
              defaultValue={autopilot?.vision_interval_seconds ?? 300}
              onBlur={(event) =>
                onUpdateAutomation({ vision_interval_seconds: Number(event.currentTarget.value) })
              }
              className="h-9 w-24 rounded-md border border-line bg-surface px-2 text-sm text-ink"
            />
            秒
          </span>
        </label>
        <label className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3 text-xs text-ink3">
          <span>
            <span className="block text-sm font-medium text-ink2">久坐提醒时间</span>
            <span>连续坐姿达到该时长后语音提醒</span>
          </span>
          <span className="flex items-center gap-2">
            <input
              key={`sit-${autopilot?.sedentary_threshold_seconds}`}
              type="number"
              min={5}
              max={28800}
              defaultValue={autopilot?.sedentary_threshold_seconds ?? 7200}
              onBlur={(event) =>
                onUpdateAutomation({ sedentary_threshold_seconds: Number(event.currentTarget.value) })
              }
              className="h-9 w-24 rounded-md border border-line bg-surface px-2 text-sm text-ink"
            />
            秒
          </span>
        </label>
      </div>
    </Panel>
  );
}
