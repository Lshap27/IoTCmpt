"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AiHealthReport, AiRunOut, ReportPeriod } from "@/lib/api";
import { cancelDeviceAiRun, fetchAiRun, fetchAiRuns, startAiRun } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "skipped"]);

async function waitForRun(deviceId: string, initial: AiRunOut): Promise<AiRunOut> {
  let current = initial;
  for (let attempt = 0; attempt < 120 && !TERMINAL.has(current.status); attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    current = await fetchAiRun(deviceId, current.run_id);
  }
  if (!TERMINAL.has(current.status)) throw new Error("AI 任务等待超时，可稍后按 run_id 查询");
  if (current.status === "failed") throw new Error(current.error_message || "AI 任务失败");
  return current;
}

export function useAiRuns(deviceId: string) {
  const queryClient = useQueryClient();
  const [decisionRun, setDecisionRun] = useState<AiRunOut | null>(null);
  const [healthReport, setHealthReport] = useState<AiHealthReport | null>(null);
  const [error, setError] = useState("");
  const runsQuery = useQuery({
    queryKey: deviceKeys.ai(deviceId),
    queryFn: () => fetchAiRuns(deviceId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((run) => !TERMINAL.has(run.status)) ? 2000 : false,
  });

  const decision = useMutation({
    mutationFn: async (kind: "decision" | "vision") =>
      waitForRun(deviceId, await startAiRun(deviceId, { kind, trigger: "manual" })),
    onMutate: () => setError(""),
    onSuccess: (run) => {
      setDecisionRun(run);
      void queryClient.invalidateQueries({ queryKey: deviceKeys.ai(deviceId) });
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "AI 分析失败"),
  });
  const report = useMutation({
    mutationFn: async (period: ReportPeriod) =>
      waitForRun(deviceId, await startAiRun(deviceId, { kind: "report", trigger: "manual", period })),
    onMutate: () => setError(""),
    onSuccess: (run) => {
      setHealthReport(run.output as AiHealthReport);
      void queryClient.invalidateQueries({ queryKey: deviceKeys.ai(deviceId) });
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "AI 报告生成失败"),
  });

  const cancel = useMutation({
    mutationFn: (runId: string) => cancelDeviceAiRun(deviceId, runId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: deviceKeys.ai(deviceId) }),
    onError: (reason) => setError(reason instanceof Error ? reason.message : "取消任务失败"),
  });
  const runs = runsQuery.data ?? [];
  const latestDecision =
    decisionRun ?? runs.find((run) => run.kind === "decision" || run.kind === "patrol") ?? null;
  const latestReport = runs.find((run) => run.kind === "report" && run.status === "succeeded");

  return {
    runs,
    decisionRun: latestDecision,
    healthReport: healthReport ?? (latestReport?.output as AiHealthReport | undefined) ?? null,
    analyzing: decision.isPending ? "manual" : null,
    imageAnalyzing: decision.isPending && decision.variables === "vision",
    reportGenerating: report.isPending,
    error: error || (runsQuery.error instanceof Error ? runsQuery.error.message : ""),
    triggerAnalysis: useCallback(() => decision.mutate("decision"), [decision]),
    triggerImageAnalysis: useCallback(() => decision.mutate("vision"), [decision]),
    generateReport: useCallback((period: ReportPeriod) => report.mutate(period), [report]),
    cancelRun: useCallback((runId: string) => cancel.mutate(runId), [cancel]),
  };
}
