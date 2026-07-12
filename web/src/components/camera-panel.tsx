"use client";

import { useState } from "react";
import { Camera, CameraOff, PersonStanding, ScanSearch } from "lucide-react";
import { Panel } from "@/components/panel";
import { formatRelative } from "@/lib/utils";

export function CameraPanel({
  image,
  pose,
  onAnalyze,
  className,
}: {
  image: { url: string; created_at: string } | null | undefined;
  pose:
    | {
        human_present: boolean;
        label: string;
        confidence: number;
        source_image_url: string;
        annotated_image_url?: string | null;
        created_at: string;
      }
    | null
    | undefined;
  onAnalyze: () => void;
  className?: string;
}) {
  const [showAnnotated, setShowAnnotated] = useState(true);
  const showingAnnotated = showAnnotated && Boolean(pose?.annotated_image_url);
  const imageUrl = showingAnnotated ? pose?.annotated_image_url : image?.url;
  const capturedAt = showingAnnotated ? pose?.created_at : image?.created_at;
  return (
    <Panel
      title="现场画面与姿态"
      icon={<Camera size={17} />}
      className={className}
      actions={
        <button
          type="button"
          onClick={onAnalyze}
          className="inline-flex items-center gap-1 rounded-md border border-line bg-raised px-2 py-1 text-[11px] text-ink2 hover:text-ink"
        >
          <ScanSearch size={13} /> 重新识别
        </button>
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
          <figcaption className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent px-3 pb-2 pt-8 text-[11px] text-white/90">
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
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs text-ink2">
          <PersonStanding size={15} className={pose?.human_present ? "text-good" : "text-ink3"} />
          <span>{pose?.label ?? "等待姿态识别"}</span>
          {pose ? <span className="tnum text-ink3">{Math.round(pose.confidence * 100)}%</span> : null}
        </div>
        {pose?.annotated_image_url ? (
          <div className="flex rounded-md border border-line bg-raised p-0.5" aria-label="画面类型">
            <button
              type="button"
              onClick={() => setShowAnnotated(false)}
              className={`rounded px-2 py-0.5 text-[11px] ${!showAnnotated ? "bg-surface text-ink" : "text-ink3"}`}
            >
              原图
            </button>
            <button
              type="button"
              onClick={() => setShowAnnotated(true)}
              className={`rounded px-2 py-0.5 text-[11px] ${showAnnotated ? "bg-surface text-ink" : "text-ink3"}`}
            >
              骨架图
            </button>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
