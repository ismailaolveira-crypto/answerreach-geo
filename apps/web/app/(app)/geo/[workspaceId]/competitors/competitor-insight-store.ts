export type CompetitorInsight = {
  provider: string;
  model: string;
  generated_at: string;
  scope: {
    kind: string;
    period: string;
    model: string;
    question: string;
    answer_count: number;
  };
  analysis: {
    scope_summary: string;
    overall_assessment: string;
    findings: Array<{ title: string; detail: string; evidence_ids: number[] }>;
    recommended_actions: string[];
    limitations: string[];
  };
  snapshot_id?: number;
  persisted?: boolean;
  is_stale?: boolean;
  source_evidence_count?: number;
};

export type InsightScopeKey = {
  workspaceId: string;
  periodDays: number;
  modelKey: string;
  questionPlanId?: number;
};

function storageKey({ workspaceId, periodDays, modelKey, questionPlanId }: InsightScopeKey) {
  return ["geo-competitor-insight", workspaceId, periodDays, modelKey, questionPlanId ?? "all"].join(":");
}

export function storeCompetitorInsight(scope: InsightScopeKey, insight: CompetitorInsight) {
  window.sessionStorage.setItem(storageKey(scope), JSON.stringify(insight));
}

export function clearCompetitorInsight(scope: InsightScopeKey) {
  window.sessionStorage.removeItem(storageKey(scope));
}

export function readCompetitorInsight(scope: InsightScopeKey) {
  const raw = window.sessionStorage.getItem(storageKey(scope));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CompetitorInsight;
  } catch {
    window.sessionStorage.removeItem(storageKey(scope));
    return null;
  }
}

export async function fetchCompetitorInsight(
  scope: InsightScopeKey,
  signal?: AbortSignal,
): Promise<CompetitorInsight | null> {
  const query = new URLSearchParams({ period_days: String(scope.periodDays) });
  if (scope.modelKey && scope.modelKey !== "all") query.set("model_key", scope.modelKey);
  if (scope.questionPlanId) query.set("question_plan_id", String(scope.questionPlanId));
  const response = await fetch(
    `/api/geo/${scope.workspaceId}/competitor-insights?${query}`,
    { cache: "no-store", signal },
  );
  const payload = await response.json().catch(() => null) as
    | CompetitorInsight
    | { detail?: string }
    | null;
  if (!response.ok) {
    throw new Error(
      (payload && "detail" in payload && payload.detail) || "暂时无法读取已保存报告。",
    );
  }
  if (!payload) return null;
  if (!("analysis" in payload)) throw new Error("已保存报告的返回格式不正确。");
  return payload;
}
