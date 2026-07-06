import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AIoT Control Console",
  description: "ESP32-S3 AIoT real-time device console"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

