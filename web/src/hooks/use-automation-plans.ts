"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  changeAutomationPlan,
  fetchAiRuns,
  fetchAiStrategies,
  fetchAutomationPlanEvents,
  fetchAutomationPlans,
  resolveAiStrategy,
  startAiRun,
} from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "skipped"]);

export function useAutomationPlans(deviceId: string) {
  const queryClient = useQueryClient();
  const plansQuery = useQuery({
    queryKey: deviceKeys.automationPlans(deviceId),
    queryFn: () => fetchAutomationPlans(deviceId),
  });
  const strategiesQuery = useQuery({
    queryKey: deviceKeys.aiStrategies(deviceId),
    queryFn: () => fetchAiStrategies(deviceId),
  });
  const runsQuery = useQuery({
    queryKey: deviceKeys.ai(deviceId),
    queryFn: () => fetchAiRuns(deviceId),
  });
  const plans = plansQuery.data ?? [];
  const userPlans = plans.filter((plan) => plan.plan_type === "user");
  const selectedPlan =
    userPlans.find((plan) => plan.status === "active" || plan.status === "paused") ?? userPlans[0] ?? null;
  const eventsQuery = useQuery({
    queryKey: deviceKeys.automationPlanEvents(deviceId, selectedPlan?.plan_id ?? "none"),
    queryFn: () => fetchAutomationPlanEvents(deviceId, selectedPlan!.plan_id),
    enabled: Boolean(selectedPlan),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: deviceKeys.automationPlans(deviceId) });
    void queryClient.invalidateQueries({ queryKey: deviceKeys.aiStrategies(deviceId) });
    void queryClient.invalidateQueries({ queryKey: deviceKeys.ai(deviceId) });
  };
  const compile = useMutation({
    mutationFn: (goal: string) => startAiRun(deviceId, { kind: "plan_compile", trigger: "manual", goal }),
    onSuccess: invalidate,
  });
  const generateStrategy = useMutation({
    mutationFn: (planId?: string) =>
      startAiRun(deviceId, { kind: "strategy", trigger: "manual", plan_id: planId }),
    onSuccess: invalidate,
  });
  const transition = useMutation({
    mutationFn: ({
      planId,
      action,
      replaceActive,
    }: {
      planId: string;
      action: "activate" | "pause" | "resume" | "cancel";
      replaceActive?: boolean;
    }) => changeAutomationPlan(deviceId, planId, action, replaceActive),
    onSuccess: invalidate,
  });
  const strategyAction = useMutation({
    mutationFn: ({ strategyId, action }: { strategyId: string; action: "approve" | "reject" }) =>
      resolveAiStrategy(deviceId, strategyId, action),
    onSuccess: invalidate,
  });
  const runs = runsQuery.data ?? [];
  const compileRun = runs.find((run) => run.kind === "plan_compile") ?? null;
  const strategyRun = runs.find((run) => run.kind === "strategy") ?? null;
  const error =
    compile.error ??
    generateStrategy.error ??
    transition.error ??
    strategyAction.error ??
    plansQuery.error ??
    strategiesQuery.error;

  return {
    plans: userPlans,
    selectedPlan,
    events: eventsQuery.data ?? [],
    strategies: strategiesQuery.data ?? [],
    compileRun,
    strategyRun,
    compiling: compile.isPending || Boolean(compileRun && !TERMINAL.has(compileRun.status)),
    generatingStrategy:
      generateStrategy.isPending || Boolean(strategyRun && !TERMINAL.has(strategyRun.status)),
    busy: transition.isPending || strategyAction.isPending,
    error: error instanceof Error ? error.message : "",
    compile: (goal: string) => compile.mutate(goal),
    generateStrategy: (planId?: string) => generateStrategy.mutate(planId),
    transition: (planId: string, action: "activate" | "pause" | "resume" | "cancel", replaceActive = false) =>
      transition.mutate({ planId, action, replaceActive }),
    resolveStrategy: (strategyId: string, action: "approve" | "reject") =>
      strategyAction.mutate({ strategyId, action }),
  };
}
