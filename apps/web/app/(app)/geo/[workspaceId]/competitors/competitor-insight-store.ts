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
