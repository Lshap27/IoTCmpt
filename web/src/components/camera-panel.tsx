"use client";

import { Camera, CameraOff } from "lucide-react";
import { Panel } from "@/components/panel";
import { formatRelative } from "@/lib/utils";

export function CameraPanel({
  image,
  className
}: {
  image: { url: string; created_at: string } | null | undefined;
  className?: string;
}) {
  return (
    <Panel title="现场画面" icon={<Camera size={17} />} className={className}>
      {image?.url ? (
        <figure
          key={image.url}
          className="relative aspect-video animate-flash-ring overflow-hidden rounded-xl border border-line bg-black/70"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={image.url} alt="设备最新画面" className="h-full w-full object-contain" />
          <figcaption className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent px-3 pb-2 pt-8 text-[11px] text-white/90">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-white" aria-hidden />
              OV2640
            </span>
            <span>更新于 {formatRelative(image.created_at)}</span>
          </figcaption>
        </figure>
      ) : (
        <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line text-ink3">
          <CameraOff size={24} />
          <p className="text-xs">等待设备上传画面</p>
        </div>
      )}
    </Panel>
  );
}
