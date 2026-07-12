"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  const isDark = resolvedTheme === "dark";

  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      aria-label="切换深浅主题"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="h-10 w-10 rounded-xl border-line bg-surface text-ink2 hover:border-accent hover:bg-raised hover:text-accent"
    >
      {mounted ? isDark ? <Sun size={16} /> : <Moon size={16} /> : <Moon size={16} className="opacity-0" />}
    </Button>
  );
}
