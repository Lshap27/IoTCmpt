"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { EventOut, LatestState } from "@/lib/api";
import {
  acknowledgeDeviceEvent,
  fetchDeviceEvents,
  fetchHistory,
  fetchHistoryBucketed,
  fetchLatest,
  requestAiAnalysis,
  requestPoseAnalysis,
  sendCommand,
  updateAutopilot,
} from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";
import type { AiPanelState, UiEvent } from "@/lib/ws-dispatcher";
import { EMPTY_AI, HISTORY_CAP, addPendingCommand, applyEnvelope, isAckedCommand } from "@/lib/ws-dispatcher";
import { useDeviceSocket } from "@/hooks/use-device-socket";

export type { SocketState } from "@/hooks/use-device-socket";
export type { UiEvent } from "@/lib/ws-dispatcher";

const TERMINAL_COMMAND_STATUSES = ["executed", "rejected", "failed"];

let localIdSeq = 0;

// crypto.randomUUID 在非安全上下文（如局域网 HTTP）不可用，这里只需要本地占位 id
function makeLocalCommandId() {
  localIdSeq += 1;
  return `local-${Date.now()}-${localIdSeq}`;
}

function removePendingCommand(queryClient: ReturnType<typeof useQueryClient>, deviceId: string, id: string) {
  queryClient.setQueryData<Record<string, string>>(deviceKeys.pendingCommands(deviceId), (current = {}) => {
    if (!(id in current)) return current;
    const next = { ...current };
    delete next[id];
    return next;
  });
}

/** 组合层：HTTP 查询（TanStack Query）+ WebSocket 实时推送（写入 query cache）+ 操作 mutation。 */
export function useDeviceLive(deviceId: string) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState("");

  const latestQuery = useQuery({
    queryKey: deviceKeys.latest(deviceId),
    queryFn: () => fetchLatest(deviceId),
  });
  const historyQuery = useQuery({
    queryKey: deviceKeys.history(deviceId),
    queryFn: async () => [...(await fetchHistory(deviceId, HISTORY_CAP))].reverse(),
  });
  const reportHistoryQuery = useQuery({
    queryKey: deviceKeys.reportHistory(deviceId),
    queryFn: async () => [...(await fetchHistoryBucketed(deviceId, 3600, 168))].reverse(),
    refetchInterval: 5 * 60 * 1000,
  });
  const ledgerQuery = useQuery({
    queryKey: deviceKeys.ledger(deviceId),
    queryFn: () => fetchDeviceEvents(deviceId),
  });

  // 纯客户端状态放 query cache：WS dispatcher 可以在组件树外更新它们。
  const eventsQuery = useQuery({
    queryKey: deviceKeys.events(deviceId),
    queryFn: () => [] as UiEvent[],
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const aiQuery = useQuery({
    queryKey: deviceKeys.ai(deviceId),
    queryFn: () => EMPTY_AI,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const pendingQuery = useQuery({
    queryKey: deviceKeys.pendingCommands(deviceId),
    queryFn: () => ({}) as Record<string, string>,
    staleTime: Infinity,
    gcTime: Infinity,
  });

  const socketState = useDeviceSocket(
    deviceId,
    useCallback((envelope) => applyEnvelope(queryClient, deviceId, envelope), [queryClient, deviceId]),
    useCallback(() => {
      // 断线期间可能漏推送：重连成功后拉回权威快照。
      void queryClient.invalidateQueries({ queryKey: deviceKeys.latest(deviceId) }).then(() => {
        // 如果 analyzing 在断线时被悬置，用最新快照清掉
        queryClient.setQueryData<AiPanelState>(deviceKeys.ai(deviceId), (c = EMPTY_AI) =>
          c.analyzing ? { ...c, analyzing: null } : c,
        );
        // 断线期间 command_ack 可能已经错过，按权威快照清掉已终结的 pending 指令
        const latest = queryClient.getQueryData<LatestState>(deviceKeys.latest(deviceId));
        const command = latest?.command;
        if (command?.command_id && TERMINAL_COMMAND_STATUSES.includes(command.status)) {
          removePendingCommand(queryClient, deviceId, command.command_id);
        }
      });
      void queryClient.invalidateQueries({ queryKey: deviceKeys.history(deviceId) });
      void queryClient.invalidateQueries({ queryKey: deviceKeys.reportHistory(deviceId) });
      void queryClient.invalidateQueries({ queryKey: deviceKeys.ledger(deviceId) });
    }, [queryClient, deviceId]),
  );

  const analyzeMutation = useMutation({
    mutationFn: () => requestAiAnalysis(deviceId),
    onMutate: () => {
      setActionError("");
      queryClient.setQueryData<AiPanelState>(deviceKeys.ai(deviceId), (current = EMPTY_AI) => ({
        ...current,
        analyzing: current.analyzing ?? "manual",
      }));
    },
    onSuccess: (result) => {
      queryClient.setQueryData<AiPanelState>(deviceKeys.ai(deviceId), { analyzing: null, decision: result });
    },
    onError: (err) => {
      setActionError(err instanceof Error ? err.message : "AI 分析失败");
      queryClient.setQueryData<AiPanelState>(deviceKeys.ai(deviceId), (current = EMPTY_AI) => ({
        ...current,
        analyzing: null,
      }));
    },
  });

  const commandMutation = useMutation({
    mutationFn: (type: string) => sendCommand(deviceId, type),
    onMutate: (type) => {
      setActionError("");
      const localId = makeLocalCommandId();
      addPendingCommand(queryClient, deviceId, localId, type);
      return { localId };
    },
    onSuccess: (command, type, context) => {
      removePendingCommand(queryClient, deviceId, context.localId);
      if (command?.command_id && !isAckedCommand(command.command_id)) {
        addPendingCommand(queryClient, deviceId, command.command_id, type);
      }
    },
    onError: (err, _type, context) => {
      if (context) removePendingCommand(queryClient, deviceId, context.localId);
      setActionError(err instanceof Error ? err.message : "指令下发失败");
    },
  });

  const acknowledgeMutation = useMutation({
    mutationFn: (eventId: number) => acknowledgeDeviceEvent(deviceId, eventId),
    onSuccess: (event) => {
      queryClient.setQueryData<EventOut[]>(deviceKeys.ledger(deviceId), (current = []) =>
        current.map((item) => (item.id === event.id ? event : item)),
      );
    },
    onError: (err) => setActionError(err instanceof Error ? err.message : "告警确认失败"),
  });

  const poseMutation = useMutation({
    mutationFn: () => requestPoseAnalysis(deviceId),
    onError: (err) => setActionError(err instanceof Error ? err.message : "姿态分析请求失败"),
  });

  const autopilotMutation = useMutation({
    mutationFn: (enabled: boolean) => updateAutopilot(deviceId, enabled),
    onMutate: async (enabled) => {
      setActionError("");
      await queryClient.cancelQueries({ queryKey: deviceKeys.latest(deviceId) });
      const previous = queryClient.getQueryData<LatestState>(deviceKeys.latest(deviceId));
      queryClient.setQueryData<LatestState>(deviceKeys.latest(deviceId), (current) =>
        current ? { ...current, autopilot: { enabled } } : current,
      );
      return { previous };
    },
    onSuccess: (state) => {
      queryClient.setQueryData<LatestState>(deviceKeys.latest(deviceId), (current) =>
        current ? { ...current, autopilot: { enabled: state.enabled } } : current,
      );
    },
    onError: (err, _enabled, context) => {
      if (context?.previous) {
        // 只回滚 autopilot 字段，不覆盖并发 WS 推送的 telemetry/command/status
        queryClient.setQueryData<LatestState>(deviceKeys.latest(deviceId), (current) =>
          current
            ? { ...current, autopilot: context.previous?.autopilot ?? null }
            : current,
        );
      }
      setActionError(err instanceof Error ? err.message : "自动决策开关设置失败");
    },
  });

  const latest = latestQuery.data ?? null;
  const ai = aiQuery.data ?? EMPTY_AI;
  const queryError =
    latestQuery.error ?? historyQuery.error ?? reportHistoryQuery.error ?? ledgerQuery.error;

  return {
    latest,
    history: historyQuery.data ?? [],
    reportHistory: reportHistoryQuery.data ?? [],
    events: eventsQuery.data ?? [],
    ledger: ledgerQuery.data ?? [],
    socketState,
    analyzing: ai.analyzing,
    decision: ai.decision,
    autopilotEnabled: latest?.autopilot?.enabled ?? null,
    pendingCommands: pendingQuery.data ?? {},
    error: actionError || (queryError instanceof Error ? queryError.message : ""),
    triggerAnalysis: useCallback(() => analyzeMutation.mutate(), [analyzeMutation]),
    dispatchCommand: useCallback((type: string) => commandMutation.mutate(type), [commandMutation]),
    acknowledgeEvent: useCallback(
      (eventId: number) => acknowledgeMutation.mutate(eventId),
      [acknowledgeMutation],
    ),
    requestPose: useCallback(() => poseMutation.mutate(), [poseMutation]),
    toggleAutopilot: useCallback(
      (enabled: boolean) => autopilotMutation.mutate(enabled),
      [autopilotMutation],
    ),
  };
}
