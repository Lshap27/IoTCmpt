"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { LatestState } from "@/lib/api";
import { fetchHistory, fetchLatest, requestAiAnalysis, sendCommand, updateAutopilot } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";
import type { AiPanelState, UiEvent } from "@/lib/ws-dispatcher";
import { EMPTY_AI, addPendingCommand, applyEnvelope } from "@/lib/ws-dispatcher";
import { useDeviceSocket } from "@/hooks/use-device-socket";

export type { SocketState } from "@/hooks/use-device-socket";
export type { UiEvent } from "@/lib/ws-dispatcher";

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
    queryFn: async () => [...(await fetchHistory(deviceId))].reverse(),
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
      void queryClient.invalidateQueries({ queryKey: deviceKeys.latest(deviceId) });
      void queryClient.invalidateQueries({ queryKey: deviceKeys.history(deviceId) });
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
    onMutate: () => setActionError(""),
    onSuccess: (command, type) => {
      if (command?.command_id) {
        addPendingCommand(queryClient, deviceId, command.command_id, type);
      }
    },
    onError: (err) => setActionError(err instanceof Error ? err.message : "指令下发失败"),
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
        queryClient.setQueryData(deviceKeys.latest(deviceId), context.previous);
      }
      setActionError(err instanceof Error ? err.message : "自动决策开关设置失败");
    },
  });

  const latest = latestQuery.data ?? null;
  const ai = aiQuery.data ?? EMPTY_AI;
  const queryError = latestQuery.error ?? historyQuery.error;

  return {
    latest,
    history: historyQuery.data ?? [],
    events: eventsQuery.data ?? [],
    socketState,
    analyzing: ai.analyzing,
    decision: ai.decision,
    autopilotEnabled: latest?.autopilot?.enabled ?? null,
    pendingCommands: pendingQuery.data ?? {},
    error: actionError || (queryError instanceof Error ? queryError.message : ""),
    triggerAnalysis: useCallback(() => analyzeMutation.mutate(), [analyzeMutation]),
    dispatchCommand: useCallback((type: string) => commandMutation.mutate(type), [commandMutation]),
    toggleAutopilot: useCallback(
      (enabled: boolean) => autopilotMutation.mutate(enabled),
      [autopilotMutation],
    ),
  };
}
