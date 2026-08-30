import type { Route } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getCleanroomCompetitorComparison,
  type CleanroomCompetitorComparison,
  type CompetitorBrandStat,
  type CompetitorBreakdown,
} from "@/lib/cleanroom-v1-api";
import { CompetitorAiInsight } from "./competitor-ai-insight";
import { CompetitorRanking } from "./competitor-ranking";
import styles from "./competitor-comparison.module.css";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";

type Props = {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const PERIODS = new Set(["7", "30", "90", "365", "3650"]);
const VIEWS = new Set(["overall", "model", "question"]);

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function explicitPositionLabel(brand: CompetitorBrandStat) {
  return brand.explicit_average_position == null ? "—" : String(brand.explicit_average_position);
}

function BreakdownSections({
  workspaceId,
  groups,
}: {
  workspaceId: string;
  groups: CompetitorBreakdown[];
}) {
  return <section className={styles.breakdowns} aria-label="分组竞品排行榜">
    {groups.map((group) => <article key={group.key ?? group.id}>
      <header><div><h2>{group.label}</h2><p>{group.answer_count} 条真实回答</p></div></header>
      <CompetitorRanking workspaceId={workspaceId} brands={group.brands} />
    </article>)}
  </section>;
}

export default async function CompetitorComparisonPage({ params, searchParams }: Props) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const rangeDays = first(query.range)?.replace("d", "");
  const period = PERIODS.has(rangeDays ?? "") ? rangeDays! : PERIODS.has(first(query.period) ?? "") ? first(query.period)! : "90";
  const model = first(query.model) || "all";
  const question = Number(first(query.question) || 0);
  const selectedModels = (Array.isArray(query.model) ? query.model : query.model ? [query.model] : []).filter((value) => value && value !== "all");
  const selectedQuestions = (Array.isArray(query.question) ? query.question : query.question ? [query.question] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0);
  const selectedBatches = (Array.isArray(query.batch) ? query.batch : query.batch ? [query.batch] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0);
  const view = VIEWS.has(first(query.view) ?? "") ? first(query.view)! : "overall";

  let comparison: CleanroomCompetitorComparison;
  try {
    comparison = await getCleanroomCompetitorComparison(workspaceId, {
      periodDays: Number(period),
      dateFrom: first(query.range) === "custom" && first(query.from) ? `${first(query.from)}T00:00:00Z` : undefined,
      dateTo: first(query.range) === "custom" && first(query.to) ? `${first(query.to)}T23:59:59Z` : undefined,
      modelKeys: selectedModels,
      questionPlanIds: selectedQuestions,
      batchIds: selectedBatches,
      evidenceLimit: 50,
    });
  } catch (error) {
    if (error instanceof Error && error.message.includes("404")) notFound();
    throw error;
  }

  const baseline = comparison.brands.find((brand) => brand.is_baseline)!;
  const competitors = comparison.brands.filter((brand) => !brand.is_baseline);
  const topAppearingCompetitor = [...competitors].sort((left, right) =>
    right.mention_rate - left.mention_rate
    || right.hit_answer_count - left.hit_answer_count
    || right.wins_over_baseline - left.wins_over_baseline
    || left.canonical_name.localeCompare(right.canonical_name, "zh-CN")
  )[0];
  const headline = comparison.summary.answer_count === 0
    ? "当前范围没有已归档真实回答"
    : `${baseline.canonical_name} 在 ${baseline.hit_answer_count}/${baseline.sample_answer_count} 条回答中出现`;
  const scopeLabel = period === "3650" ? "全部归档" : `近 ${period} 天`;
	const selectedModel = selectedModels.length > 1 ? `已选 ${selectedModels.length} 个模型` : model === "all"
    ? "全部已测模型"
    : comparison.available_models.find((item) => item.key === model)?.label ?? model;
	const selectedQuestion = selectedQuestions.length > 1 ? `已选 ${selectedQuestions.length} 个问题` : question > 0
    ? comparison.available_questions.find((item) => item.id === question)?.question_text ?? `问题 #${question}`
    : "全部已选问题";

  function viewHref(nextView: string) {
		const next = new URLSearchParams();
		for (const [key, raw] of Object.entries(query)) {
			for (const value of Array.isArray(raw) ? raw : raw ? [raw] : []) next.append(key, value);
		}
		next.set("view", nextView);
    return `/geo/${workspaceId}/competitors?${next.toString()}`;
  }

  return <div className={`${styles.page} geo-competitors-page`}>
    <header className={styles.topbar}>
      <Link className={styles.brand} href={`/geo/${workspaceId}`}><img alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" /><b>入答 AnswerReach</b></Link>
      <nav className={styles.toplinks} aria-label="GEO 主导航">
        <Link href={`/geo/${workspaceId}`}>决策地图</Link>
        <Link aria-current="page" href={`/geo/${workspaceId}/competitors` as Route}>竞品对比</Link>
        <Link href={`/geo/${workspaceId}/actions`}>优化行动</Link>
        <Link href={`/admin/providers?workspace=${workspaceId}` as Route}>模型与渠道</Link>
      </nav>
    </header>

    <main className={styles.main}>
      <section className={styles.heading}>
        <div><span>竞争情报</span><h1>竞品对比</h1><p>看清真实 AI 采购回答里，各品牌被提到的频率与对比信号。</p></div>
      </section>
      <GeoGlobalScopeBar workspaceId={workspaceId} />
      <section className={styles.summary} aria-labelledby="comparison-headline">
        <div className={styles.conclusion}><small>本轮结论</small><h2 id="comparison-headline">{headline}</h2><p>{comparison.summary.answer_count} 条真实回答 · {comparison.by_model.filter((item) => item.answer_count > 0).length} 个模型</p></div>
        <dl>
          <div><dt>品牌出现率</dt><dd>{baseline.mention_rate}%</dd><small>{baseline.hit_answer_count}/{baseline.sample_answer_count} 条</small></div>
          <div><dt>平均位置</dt><dd>{explicitPositionLabel(baseline)}</dd><small>{baseline.explicit_rank_observation_count} 条有明确排序</small></div>
          <div><dt>对比信号</dt><dd>{comparison.summary.answers_where_competitor_wins}</dd><small>仅用于回看同一回答</small></div>
        </dl>
        <div className={styles.gap}><span>最高竞品出现率</span><b>{topAppearingCompetitor ? `${topAppearingCompetitor.canonical_name} · ${topAppearingCompetitor.hit_answer_count}/${topAppearingCompetitor.sample_answer_count} 条（${topAppearingCompetitor.mention_rate}%）` : "当前没有追踪竞品"}</b><a href="#competitor-leaderboard">查看行内信号 →</a></div>
      </section>

      <div className={styles.comparisonGrid}>
        <section className={styles.ranking} id="competitor-leaderboard">
          <header><div><h2>品牌出现率排行榜</h2><p>出现率 = 品牌出现的回答数 ÷ 当前筛选的有效回答总数；真实 0 保留。</p></div><span>{scopeLabel}</span></header>
          <CompetitorRanking workspaceId={workspaceId} brands={comparison.brands} actionDiagnostics={comparison.action_diagnostics} />
        </section>

        <aside className={styles.side}>
          <section className={styles.scopeCard}>
            <header><h2>问题与模型</h2><nav aria-label="排行榜视角">
              <Link aria-current={view === "overall" ? "page" : undefined} href={viewHref("overall") as Route}>总榜</Link>
              <Link aria-current={view === "model" ? "page" : undefined} href={viewHref("model") as Route}>模型</Link>
              <Link aria-current={view === "question" ? "page" : undefined} href={viewHref("question") as Route}>问题</Link>
            </nav></header>
            <p><b>{selectedQuestion}</b><span>{selectedModel}</span><small>{comparison.summary.answer_count} 条真实回答</small></p>
          </section>
          <CompetitorAiInsight
            workspaceId={workspaceId}
            periodDays={Number(period)}
            modelKey={model}
            questionPlanId={question > 0 ? question : undefined}
          />
        </aside>
      </div>

      {view === "model" ? <BreakdownSections workspaceId={workspaceId} groups={comparison.by_model} /> : null}
      {view === "question" ? <BreakdownSections workspaceId={workspaceId} groups={comparison.by_question} /> : null}

    </main>
  </div>;
}
