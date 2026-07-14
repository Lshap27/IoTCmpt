"use client";

import { useCallback, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchCapabilities, sendCommand } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";
import { addPendingCommand } from "@/lib/ws-dispatcher";

const TERMINAL = new Set(["executed", "rejected", "failed", "expired", "timed_out"]);

function removePending(queryClient: ReturnType<typeof useQueryClient>, deviceId: string, id: string) {
  queryClient.setQueryData<Record<string, string>>(deviceKeys.pendingCommands(deviceId), (current = {}) => {
    if (!(id in current)) return current;
    const next = { ...current };
    delete next[id];
    return next;
  });
}

export function useDeviceCommands(deviceId: string) {
  const queryClient = useQueryClient();
  const localSequence = useRef(0);
  const [error, setError] = useState("");
  const capabilities = useQuery({
    queryKey: deviceKeys.capabilities(deviceId),
    queryFn: () => fetchCapabilities(deviceId),
  });
  const pending = useQuery({
    queryKey: deviceKeys.pendingCommands(deviceId),
    queryFn: () => ({}) as Record<string, string>,
    staleTime: Infinity,
    gcTime: Infinity,
  });

  const mutation = useMutation({
    mutationFn: ({ type, parameter = {} }: { type: string; parameter?: Record<string, unknown> }) =>
      sendCommand(deviceId, type, parameter),
    onMutate: ({ type }) => {
      setError("");
      localSequence.current += 1;
      const localId = `local-${Date.now()}-${localSequence.current}`;
      addPendingCommand(queryClient, deviceId, localId, type);
      return { localId };
    },
    onSuccess: (command, { type }, context) => {
      removePending(queryClient, deviceId, context.localId);
      const statuses = queryClient.getQueryData<Record<string, string>>(deviceKeys.commandStatuses(deviceId));
      if (!TERMINAL.has(statuses?.[command.command_id] ?? command.status)) {
        addPendingCommand(queryClient, deviceId, command.command_id, type);
      }
    },
    onError: (reason, _variables, context) => {
      if (context) removePending(queryClient, deviceId, context.localId);
      setError(reason instanceof Error ? reason.message : "指令下发失败");
    },
  });

  return {
    capabilities: capabilities.data ?? null,
    pendingCommands: pending.data ?? {},
    error: error || (capabilities.error instanceof Error ? capabilities.error.message : ""),
    dispatchCommand: useCallback(
      (type: string, parameter?: Record<string, unknown>) => mutation.mutate({ type, parameter }),
      [mutation],
    ),
  };
}
