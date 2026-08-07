import { CompetitorInsightReport } from "../competitor-insight-report";

type Props = {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export default async function CompetitorInsightReportPage({ params, searchParams }: Props) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const requestedPeriod = Number(first(query.period));
  const periodDays = [7, 30, 90, 3650].includes(requestedPeriod) ? requestedPeriod : 90;
  const modelKey = first(query.model) || "all";
  const questionValue = first(query.question);
  const questionPlanId = questionValue && questionValue !== "all" && Number(questionValue) > 0
    ? Number(questionValue)
    : undefined;

  return <CompetitorInsightReport
    workspaceId={workspaceId}
    periodDays={periodDays}
    modelKey={modelKey}
    questionPlanId={questionPlanId}
  />;
}
