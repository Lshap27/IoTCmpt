import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17202A",
        panel: "#F7F9FB",
        line: "#D9E2EC",
        accent: "#0E7C86",
        warn: "#C77D12",
        danger: "#B42318"
      }
    }
  },
  plugins: []
};

export default config;

