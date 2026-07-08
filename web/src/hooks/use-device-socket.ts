"use client";

import { useEffect, useRef, useState } from "react";
import type { WsMessage } from "@/lib/api";
import { wsUrl } from "@/lib/api";

export type SocketState = "connecting" | "live" | "offline";

/** 只负责 WebSocket 连接：指数退避重连、状态上报、消息回调、重连成功回调。 */
export function useDeviceSocket(
  deviceId: string,
  onMessage: (envelope: WsMessage) => void,
  onReconnect: () => void,
) {
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const onMessageRef = useRef(onMessage);
  const onReconnectRef = useRef(onReconnect);
  onMessageRef.current = onMessage;
  onReconnectRef.current = onReconnect;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retries = 0;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (closed) return;
      setSocketState((state) => (state === "live" ? state : "connecting"));
      socket = new WebSocket(wsUrl(deviceId));
      socket.onopen = () => {
        setSocketState("live");
        if (retries > 0) {
          onReconnectRef.current();
        }
        retries = 0;
      };
      socket.onmessage = (message) => {
        try {
          const envelope = JSON.parse(message.data) as WsMessage;
          if (envelope && typeof envelope.type === "string") {
            onMessageRef.current(envelope);
          }
        } catch {
          // 忽略非 JSON 帧
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setSocketState("offline");
        const delay = Math.min(15_000, 1_000 * 2 ** retries);
        retries += 1;
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [deviceId]);

  return socketState;
}
