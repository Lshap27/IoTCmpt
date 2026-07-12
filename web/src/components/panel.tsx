import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function Panel({
  title,
  icon,
  actions,
  children,
  className,
}: {
  title?: string;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("glass-panel block gap-0 border-line p-4 shadow-panel sm:p-5", className)}>
      {title || actions ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 text-base font-semibold tracking-tight text-ink">
            <span className="text-accent">{icon}</span>
            <h2>{title}</h2>
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </Card>
  );
}
