"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      aria-label="切换深浅主题"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-raised text-ink2 transition-all hover:border-accent hover:text-accent"
    >
      {mounted ? isDark ? <Sun size={16} /> : <Moon size={16} /> : <Moon size={16} className="opacity-0" />}
    </button>
  );
}
