"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AiDecisionPayload,
  CommandInfo,
  Envelope,
  LatestState,
  TelemetryPoint,
  fetchHistory,
  fetchLatest,
  requestAiAnalysis,
  sendCommand,
  updateAutopilot,
  wsUrl
} from "@/lib/api";

export type SocketState = "connecting" | "live" | "offline";

export type UiEvent = {
  id: number;
  type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

const HISTORY_CAP = 120;
const EVENT_CAP = 30;

export function useDeviceLive(deviceId: string) {
  const [latest, setLatest] = useState<LatestState | null>(null);
  const [history, setHistory] = useState<TelemetryPoint[]>([]);
  const [events, setEvents] = useState<UiEvent[]>([]);
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [decision, setDecision] = useState<AiDecisionPayload | null>(null);
  const [autopilotEnabled, setAutopilotEnabled] = useState<boolean | null>(null);
  const [pendingCommands, setPendingCommands] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const eventSeq = useRef(0);

  const load = useCallback(async () => {
    const [latestState, historyRows] = await Promise.all([fetchLatest(deviceId), fetchHistory(deviceId)]);
    setLatest(latestState);
    setHistory([...historyRows].reverse());
    setAutopilotEnabled(latestState.autopilot?.enabled ?? null);
  }, [deviceId]);

  useEffect(() => {
    let cancelled = false;
    setLatest(null);
    setHistory([]);
    setEvents([]);
    setDecision(null);
    setAnalyzing(null);
    setPendingCommands({});
    setError("");
    load().catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "初始数据加载失败");
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const applyEnvelope = useCallback((envelope: Envelope) => {
    const { type, payload, occurred_at } = envelope;
    eventSeq.current += 1;
    setEvents((current) =>
      [{ id: eventSeq.current, type, payload, occurred_at }, ...current].slice(0, EVENT_CAP)
    );

    switch (type) {
      case "telemetry": {
        const point = payload as unknown as TelemetryPoint;
        setHistory((current) => [...current.slice(-(HISTORY_CAP - 1)), point]);
        setLatest((current) =>
          current
            ? { ...current, telemetry: point, device: { ...current.device, status: "online", last_seen_at: occurred_at } }
            : current
        );
        break;
      }
      case "status": {
        const status = typeof payload.status === "string" ? payload.status : undefined;
        setLatest((current) =>
          current && status
            ? { ...current, device: { ...current.device, status, last_seen_at: occurred_at } }
            : current
        );
        break;
      }
      case "image": {
        setLatest((current) =>
          current ? { ...current, image: payload as unknown as LatestState["image"] } : current
        );
        break;
      }
      case "ai_analyzing": {
        setAnalyzing(typeof payload.trigger === "string" ? payload.trigger : "manual");
        break;
      }
      case "ai_result": {
        const result = payload as unknown as AiDecisionPayload;
        setAnalyzing(null);
        setDecision(result);
        if (result.command) {
          setLatest((current) => (current ? { ...current, command: result.command } : current));
        }
        break;
      }
      case "command": {
        setLatest((current) => (current ? { ...current, command: payload as unknown as CommandInfo } : current));
        break;
      }
      case "command_ack": {
        const commandId = typeof payload.command_id === "string" ? payload.command_id : "";
        if (commandId) {
          setPendingCommands((current) => {
            if (!(commandId in current)) return current;
            const next = { ...current };
            delete next[commandId];
            return next;
          });
          setLatest((current) =>
            current && current.command && current.command.command_id === commandId
              ? {
                  ...current,
                  command: {
                    ...current.command,
                    status: typeof payload.status === "string" ? payload.status : current.command.status,
                    executed_at:
                      typeof payload.executed_at === "string" ? payload.executed_at : current.command.executed_at
                  }
                }
              : current
          );
        }
        break;
      }
      case "autopilot": {
        setAutopilotEnabled(Boolean(payload.enabled));
        break;
      }
      default:
        break;
    }
  }, []);

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
          load().catch(() => undefined);
        }
        retries = 0;
      };
      socket.onmessage = (message) => {
        try {
          const envelope = JSON.parse(message.data) as Envelope;
          if (envelope && typeof envelope.type === "string") {
            applyEnvelope(envelope);
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
  }, [deviceId, load, applyEnvelope]);

  const triggerAnalysis = useCallback(async () => {
    setError("");
    setAnalyzing((current) => current ?? "manual");
    try {
      const result = await requestAiAnalysis(deviceId);
      setDecision(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 分析失败");
    } finally {
      setAnalyzing(null);
    }
  }, [deviceId]);

  const dispatchCommand = useCallback(
    async (type: string) => {
      setError("");
      try {
        const command = await sendCommand(deviceId, type);
        if (command?.command_id) {
          setPendingCommands((current) => ({ ...current, [command.command_id]: type }));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "指令下发失败");
      }
    },
    [deviceId]
  );

  const toggleAutopilot = useCallback(
    async (enabled: boolean) => {
      setError("");
      const previous = autopilotEnabled;
      setAutopilotEnabled(enabled);
      try {
        const state = await updateAutopilot(deviceId, enabled);
        setAutopilotEnabled(state.enabled);
      } catch (err) {
        setAutopilotEnabled(previous);
        setError(err instanceof Error ? err.message : "自动决策开关设置失败");
      }
    },
    [deviceId, autopilotEnabled]
  );

  return {
    latest,
    history,
    events,
    socketState,
    analyzing,
    decision,
    autopilotEnabled,
    pendingCommands,
    error,
    triggerAnalysis,
    dispatchCommand,
    toggleAutopilot
  };
}
