"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AutomationPolicyIn, AutomationPolicyOut } from "@/lib/api";
import { fetchAutomationPolicy, saveAutomationPolicy } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";

export function useAutomationPolicy(deviceId: string) {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: deviceKeys.automationPolicy(deviceId),
    queryFn: () => fetchAutomationPolicy(deviceId),
  });
  const mutation = useMutation({
    mutationFn: (values: AutomationPolicyIn) => saveAutomationPolicy(deviceId, values),
    onMutate: () => setError(""),
    onSuccess: (policy) =>
      queryClient.setQueryData<AutomationPolicyOut>(deviceKeys.automationPolicy(deviceId), policy),
    onError: (reason) => setError(reason instanceof Error ? reason.message : "自动化策略保存失败"),
  });

  return {
    policy: query.data ?? null,
    saving: mutation.isPending,
    error: error || (query.error instanceof Error ? query.error.message : ""),
    updatePolicy: useCallback((values: AutomationPolicyIn) => mutation.mutate(values), [mutation]),
  };
}
