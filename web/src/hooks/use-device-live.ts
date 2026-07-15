"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { EventOut, LatestState } from "@/lib/api-client/types.gen";
import {
  acknowledgeDeviceEvent,
  fetchDeviceEvents,
  fetchHistory,
  fetchHistoryBucketed,
  fetchLatest,
  requestPoseAnalysis,
} from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";
import type { UiEvent } from "@/lib/ws-dispatcher";
import { HISTORY_CAP, applyEnvelope } from "@/lib/ws-dispatcher";
import { useAiRuns } from "@/hooks/use-ai-runs";
import { useAutomationPolicy } from "@/hooks/use-automation-policy";
import { useDeviceCommands } from "@/hooks/use-device-commands";
import { useDeviceNotifications } from "@/hooks/use-device-notifications";
import { useDeviceSocket } from "@/hooks/use-device-socket";

export type { SocketState } from "@/hooks/use-device-socket";
export type { UiEvent } from "@/lib/ws-dispatcher";

const TERMINAL_COMMAND_STATUSES = ["executed", "rejected", "failed", "expired", "timed_out"];

function removePendingCommand(queryClient: ReturnType<typeof useQueryClient>, deviceId: string, id: string) {
  queryClient.setQueryData<Record<string, string>>(deviceKeys.pendingCommands(deviceId), (current = {}) => {
    if (!(id in current)) return current;
    const next = { ...current };
    delete next[id];
    return next;
  });
}

/** Device-page composition only; commands, AI, policy and notifications own their data flows. */
export function useDeviceLive(deviceId: string) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState("");
  const commands = useDeviceCommands(deviceId);
  const automation = useAutomationPolicy(deviceId);
  const ai = useAiRuns(deviceId);
  const notifications = useDeviceNotifications(deviceId);

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
  const eventsQuery = useQuery({
    queryKey: deviceKeys.events(deviceId),
    queryFn: () => [] as UiEvent[],
    staleTime: Infinity,
    gcTime: Infinity,
  });

  const socketState = useDeviceSocket(
    deviceId,
    useCallback((envelope) => applyEnvelope(queryClient, deviceId, envelope), [queryClient, deviceId]),
    useCallback(() => {
      void queryClient.invalidateQueries({ queryKey: deviceKeys.latest(deviceId) }).then(() => {
        const command = queryClient.getQueryData<LatestState>(deviceKeys.latest(deviceId))?.command;
        if (command?.command_id && TERMINAL_COMMAND_STATUSES.includes(command.status)) {
          removePendingCommand(queryClient, deviceId, command.command_id);
        }
      });
      for (const key of [
        deviceKeys.history(deviceId),
        deviceKeys.reportHistory(deviceId),
        deviceKeys.ledger(deviceId),
        deviceKeys.notifications(deviceId),
        deviceKeys.capabilities(deviceId),
        deviceKeys.automationPolicy(deviceId),
        deviceKeys.automationPlans(deviceId),
        deviceKeys.aiStrategies(deviceId),
        deviceKeys.ai(deviceId),
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    }, [queryClient, deviceId]),
  );

  const acknowledgeMutation = useMutation({
    mutationFn: (eventId: number) => acknowledgeDeviceEvent(deviceId, eventId),
    onSuccess: (event) => {
      queryClient.setQueryData<EventOut[]>(deviceKeys.ledger(deviceId), (current = []) =>
        current.map((item) => (item.id === event.id ? event : item)),
      );
    },
    onError: (reason) => setActionError(reason instanceof Error ? reason.message : "告警确认失败"),
  });
  const poseMutation = useMutation({
    mutationFn: () => requestPoseAnalysis(deviceId),
    onError: (reason) => setActionError(reason instanceof Error ? reason.message : "姿态分析请求失败"),
  });
  const queryError = latestQuery.error ?? historyQuery.error ?? reportHistoryQuery.error ?? ledgerQuery.error;
  return {
    latest: latestQuery.data ?? null,
    history: historyQuery.data ?? [],
    reportHistory: reportHistoryQuery.data ?? [],
    events: eventsQuery.data ?? [],
    ledger: ledgerQuery.data ?? [],
    notifications: notifications.notifications,
    socketState,
    decisionRun: ai.decisionRun,
    aiRuns: ai.runs,
    analyzing: ai.analyzing,
    healthReport: ai.healthReport,
    reportGenerating: ai.reportGenerating,
    imageAnalyzing: ai.imageAnalyzing,
    automationPolicy: automation.policy,
    automationSaving: automation.saving,
    capabilities: commands.capabilities,
    pendingCommands: commands.pendingCommands,
    notificationSending: notifications.notificationSending,
    error:
      actionError ||
      commands.error ||
      automation.error ||
      ai.error ||
      notifications.error ||
      (queryError instanceof Error ? queryError.message : ""),
    triggerAnalysis: ai.triggerAnalysis,
    triggerImageAnalysis: ai.triggerImageAnalysis,
    generateReport: ai.generateReport,
    cancelAiRun: ai.cancelRun,
    dispatchCommand: commands.dispatchCommand,
    sendNotification: notifications.sendNotification,
    acknowledgeEvent: useCallback(
      (eventId: number) => acknowledgeMutation.mutate(eventId),
      [acknowledgeMutation],
    ),
    requestPose: useCallback(() => poseMutation.mutate(), [poseMutation]),
    toggleAutomationPolicy: useCallback(
      (enabled: boolean) => automation.updatePolicy({ enabled }),
      [automation],
    ),
    updatePolicy: automation.updatePolicy,
    updateAutomation: automation.updatePolicy,
  };
}
