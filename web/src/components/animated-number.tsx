"use client";

import { useEffect, useRef, useState } from "react";

/** rAF 插值的数值动画；value 为 null 时显示占位符。 */
export function AnimatedNumber({
  value,
  digits = 1,
  className,
  placeholder = "--",
}: {
  value: number | null | undefined;
  digits?: number;
  className?: string;
  placeholder?: string;
}) {
  const [display, setDisplay] = useState<number | null>(typeof value === "number" ? value : null);
  const previous = useRef<number | null>(typeof value === "number" ? value : null);

  useEffect(() => {
    if (typeof value !== "number") {
      previous.current = null;
      setDisplay(null);
      return;
    }
    const from = previous.current;
    previous.current = value;
    if (from === null || from === value) {
      setDisplay(value);
      return;
    }

    const start = performance.now();
    const duration = 550;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (value - from) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return <span className={className}>{display === null ? placeholder : display.toFixed(digits)}</span>;
}
