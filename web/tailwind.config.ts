import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        raised: "var(--raised)",
        line: "var(--line)",
        ink: "var(--ink)",
        ink2: "var(--ink-2)",
        ink3: "var(--ink-3)",
        accent: "var(--accent)",
        good: "var(--good)",
        warn: "var(--warn)",
        alert: "var(--alert)",
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
        glow: "0 0 0 1px var(--accent-soft), 0 0 24px var(--accent-glow)",
      },
      keyframes: {
        "fade-slide": {
          from: { opacity: "0", transform: "translateY(-4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "flash-ring": {
          from: { boxShadow: "0 0 0 0 var(--accent-glow)" },
          to: { boxShadow: "0 0 0 14px rgba(0, 0, 0, 0)" },
        },
      },
      animation: {
        "fade-slide": "fade-slide 0.35s ease-out both",
        "pulse-soft": "pulse-soft 1.6s ease-in-out infinite",
        shimmer: "shimmer 1.8s linear infinite",
        "flash-ring": "flash-ring 0.9s ease-out 1",
      },
    },
  },
  plugins: [],
};

export default config;
