"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AiHealthReport, AiRunOut, ReportPeriod } from "@/lib/api";
import { cancelDeviceAiRun, fetchAiRuns, startAiRun } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "skipped"]);

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
    mutationFn: (kind: "decision" | "vision") => startAiRun(deviceId, { kind, trigger: "manual" }),
    onMutate: () => setError(""),
    onSuccess: (run) => {
      setDecisionRun(run);
      void queryClient.invalidateQueries({ queryKey: deviceKeys.ai(deviceId) });
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "AI 分析失败"),
  });
  const report = useMutation({
    mutationFn: (period: ReportPeriod) => startAiRun(deviceId, { kind: "report", trigger: "manual", period }),
    onMutate: () => setError(""),
    onSuccess: (run) => {
      if (run.output) setHealthReport(run.output as AiHealthReport);
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
  const activeDecision = runs.find(
    (run) => (run.kind === "decision" || run.kind === "patrol") && !TERMINAL.has(run.status),
  );
  const activeVision = runs.find((run) => run.kind === "vision" && !TERMINAL.has(run.status));
  const activeReport = runs.find((run) => run.kind === "report" && !TERMINAL.has(run.status));

  return {
    runs,
    decisionRun: latestDecision,
    healthReport: healthReport ?? (latestReport?.output as AiHealthReport | undefined) ?? null,
    analyzing: decision.isPending || activeDecision ? "manual" : null,
    imageAnalyzing: (decision.isPending && decision.variables === "vision") || Boolean(activeVision),
    reportGenerating: report.isPending || Boolean(activeReport),
    error: error || (runsQuery.error instanceof Error ? runsQuery.error.message : ""),
    triggerAnalysis: useCallback(() => decision.mutate("decision"), [decision]),
    triggerImageAnalysis: useCallback(() => decision.mutate("vision"), [decision]),
    generateReport: useCallback((period: ReportPeriod) => report.mutate(period), [report]),
    cancelRun: useCallback((runId: string) => cancel.mutate(runId), [cancel]),
  };
}
