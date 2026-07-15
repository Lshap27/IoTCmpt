"use client";

import type { ComponentPropsWithoutRef } from "react";
import { ExternalLink, Maximize2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export function AiMarkdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("min-w-0 text-sm leading-6 text-ink2", className)}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ ...props }) => (
            <h1 className="mt-5 mb-2 text-lg font-semibold text-ink first:mt-0" {...props} />
          ),
          h2: ({ ...props }) => (
            <h2 className="mt-5 mb-2 text-base font-semibold text-ink first:mt-0" {...props} />
          ),
          h3: ({ ...props }) => <h3 className="mt-4 mb-1.5 font-semibold text-ink first:mt-0" {...props} />,
          p: ({ ...props }) => <p className="my-2 break-words first:mt-0 last:mb-0" {...props} />,
          ul: ({ ...props }) => <ul className="my-2 list-disc space-y-1 pl-5" {...props} />,
          ol: ({ ...props }) => <ol className="my-2 list-decimal space-y-1 pl-5" {...props} />,
          blockquote: ({ ...props }) => (
            <blockquote
              className="my-3 border-l-2 border-accent/50 bg-raised px-3 py-1 text-ink3"
              {...props}
            />
          ),
          pre: ({ ...props }) => (
            <pre
              className="my-3 max-w-full overflow-x-auto rounded-lg border border-line bg-raised p-3 text-xs"
              {...props}
            />
          ),
          code: ({ className: codeClassName, ...props }) => (
            <code
              className={cn(
                codeClassName,
                codeClassName ? "font-mono" : "rounded bg-raised px-1 py-0.5 font-mono text-[0.9em]",
              )}
              {...props}
            />
          ),
          table: ({ ...props }) => (
            <div className="my-3 max-w-full overflow-x-auto">
              <table className="w-max min-w-full border-collapse text-left text-xs" {...props} />
            </div>
          ),
          thead: ({ ...props }) => <thead className="bg-raised text-ink" {...props} />,
          th: ({ ...props }) => <th className="border border-line px-2.5 py-2 font-semibold" {...props} />,
          td: ({ ...props }) => <td className="border border-line px-2.5 py-2 align-top" {...props} />,
          a: ({ href, children, ...props }: ComponentPropsWithoutRef<"a">) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex max-w-full items-baseline gap-1 break-all text-accent underline-offset-2 hover:underline"
              {...props}
            >
              {children}
              <ExternalLink className="inline size-3 shrink-0" aria-hidden="true" />
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export function AiTextPreview({
  content,
  title,
  description = "AI 生成内容仅用于辅助判断，请结合设备状态确认。",
  className,
}: {
  content: string;
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="relative max-h-28 overflow-hidden rounded-xl border border-line bg-raised px-3.5 py-3">
        <AiMarkdown content={content} />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-raised to-transparent" />
      </div>
      <Dialog>
        <DialogTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="mt-1.5 text-accent">
            <Maximize2 /> 查看完整分析
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto overscroll-contain pr-1">
            <AiMarkdown content={content} />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
