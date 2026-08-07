import type { Route } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getCleanroomCompetitorComparison,
  type CleanroomCompetitorComparison,
  type CompetitorBrandStat,
  type CompetitorBreakdown,
  type CompetitorEvidenceSnippet,
} from "@/lib/cleanroom-v1-api";
import styles from "./competitor-comparison.module.css";

type Props = {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

type ActionDiagnostic = CleanroomCompetitorComparison["action_diagnostics"][number];

const PERIODS = new Set(["7", "30", "90", "3650"]);
const VIEWS = new Set(["overall", "model", "question"]);

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function formatNumber(value: number) {
  return value.toLocaleString("zh-CN");
}

function explicitPositionLabel(brand: CompetitorBrandStat) {
  return brand.explicit_average_position == null ? "—" : String(brand.explicit_average_position);
}

function evidenceLabel(row: CompetitorEvidenceSnippet) {
  if (row.win_reason_type === "explicit_rank_ahead") return "明确排序在前";
  if (row.win_reason_type === "selected_baseline_absent") return "竞品入选、我们缺席";
  if (row.status === "recommended") return "明确推荐";
  if (row.status === "shortlisted") return "进入候选";
  if (row.status === "negative") return "负面语境";
  return "普通提及";
}

function evidenceRows(brand: CompetitorBrandStat) {
  return brand.win_evidence.length ? brand.win_evidence : brand.evidence;
}

function EvidenceDisclosure({
  workspaceId,
  rows,
}: {
  workspaceId: string;
  rows: CompetitorEvidenceSnippet[];
}) {
  if (!rows.length) return <span className={styles.zeroEvidence}>真实 0</span>;

  return <details className={styles.evidenceDisclosure}>
    <summary>查看证据</summary>
    <div>
      {rows.slice(0, 8).map((row) => <Link
        href={`/geo/${workspaceId}/evidence/${row.evidence_id}`}
        key={`${row.brand_key}-${row.evidence_id}`}
      >
        <b>{row.model_label} · {evidenceLabel(row)}</b>
        <span>{row.question}</span>
        <small>{row.context_snippet || "查看完整回答与引用"}</small>
      </Link>)}
    </div>
  </details>;
}

function BrandRanking({
  workspaceId,
  brands,
}: {
  workspaceId: string;
  brands: CompetitorBrandStat[];
}) {
  const baseline = brands.find((brand) => brand.is_baseline);
  const competitors = brands
    .filter((brand) => !brand.is_baseline)
    .sort((left, right) =>
      right.mention_rate - left.mention_rate
      || right.hit_answer_count - left.hit_answer_count
      || right.wins_over_baseline - left.wins_over_baseline
      || left.canonical_name.localeCompare(right.canonical_name, "zh-CN")
    );
  const rows = baseline ? [baseline, ...competitors] : competitors;

  return <>
    <div className={styles.tableWrap}>
      <table className={styles.rankingTable}>
        <thead><tr>
          <th>排名</th><th>竞品</th><th>出现率</th><th>对比信号</th>
          <th>Top 3</th><th>平均位置</th><th>覆盖模型</th><th>证据</th>
        </tr></thead>
        <tbody>{rows.map((brand) => {
          const brandEvidence = evidenceRows(brand);
          const rank = brand.is_baseline ? "我" : competitors.indexOf(brand) + 1;
          return <tr key={brand.key} data-baseline={brand.is_baseline || undefined}>
            <td><i className={styles.rankNumber}>{rank}</i></td>
            <th><b>{brand.canonical_name}</b><small>{brand.is_baseline ? "基准品牌" : `固定追踪 · ${brand.hit_answer_count} 条`}</small></th>
            <td><strong>{brand.mention_rate}%</strong><small>{brand.hit_answer_count}/{brand.sample_answer_count} 条回答</small></td>
            <td><strong>{brand.is_baseline ? "—" : `${formatNumber(brand.wins_over_baseline)} 次`}</strong><small>{brand.is_baseline ? "作为比较基准" : `${brand.comparable_answers} 条可比较`}</small></td>
            <td>{brand.top3_rate}%</td>
            <td>{explicitPositionLabel(brand)}<small>{brand.explicit_rank_observation_count} 条有排名</small></td>
            <td>{brand.model_count}</td>
            <td><EvidenceDisclosure workspaceId={workspaceId} rows={brandEvidence} /></td>
          </tr>;
        })}</tbody>
      </table>
    </div>

    <div className={styles.mobileRanking} aria-label="竞品真实回答排行榜">
      {rows.map((brand) => {
        const brandEvidence = evidenceRows(brand);
        const rank = brand.is_baseline ? "我" : competitors.indexOf(brand) + 1;
        return <article key={brand.key} data-baseline={brand.is_baseline || undefined}>
          <header><i className={styles.rankNumber}>{rank}</i><span><b>{brand.canonical_name}</b><small>{brand.is_baseline ? "基准品牌（我们）" : "固定追踪竞品"}</small></span><strong>{brand.mention_rate}%<small>{brand.hit_answer_count}/{brand.sample_answer_count} 条</small></strong></header>
          <dl>
            <div><dt>对比信号</dt><dd>{brand.is_baseline ? "—" : `${brand.wins_over_baseline} 次`}</dd></div>
            <div><dt>Top 3</dt><dd>{brand.top3_rate}%</dd></div>
            <div><dt>平均位置</dt><dd>{explicitPositionLabel(brand)}</dd></div>
            <div><dt>覆盖</dt><dd>{brand.model_count} 模型</dd></div>
          </dl>
          <EvidenceDisclosure workspaceId={workspaceId} rows={brandEvidence} />
        </article>;
      })}
    </div>
  </>;
}

function DiagnosticPanel({
  workspaceId,
  items,
}: {
  workspaceId: string;
  items: ActionDiagnostic[];
}) {
  return <section className={styles.diagnosticPanel} id="action-diagnostics">
    <header><div><h2>需要核验的对比信号</h2><p>这不等同于出现率；展开后可回看模型、问题和原回答。</p></div><b>{items.length}</b></header>
    {items.length ? <div className={styles.diagnosticList}>
      {items.slice(0, 3).map((item, index) => {
        const signedGap = item.mention_gap > 0 ? `+${item.mention_gap}` : String(item.mention_gap);
        return <details
          className={styles.diagnosticItem}
          key={`${item.competitor_key}-${item.model_key}-${item.question_plan_id}`}
          open={index === 0}
        >
          <summary>
            <span><b>{item.competitor_name}</b><small>{item.model_label} · 差值 {signedGap}</small></span>
            <em>{item.wins_over_baseline} 条信号</em><i aria-hidden="true">⌄</i>
          </summary>
          <div>
            <dl>
              <div><dt>问题</dt><dd>{item.question}</dd></div>
              <div><dt>量化差值</dt><dd>竞品 {item.competitor_hit_count} 次，春秋元泉 {item.baseline_hit_count} 次，差值 {signedGap}。</dd></div>
              <div><dt>明确判定</dt><dd>{item.reason_label}；来自 {item.comparable_answers} 条可比较回答。</dd></div>
              <div><dt>下一步</dt><dd>{item.suggestion.replace(/^建议：/, "")}</dd></div>
            </dl>
            {item.evidence.slice(0, 3).map((row) => <Link key={row.evidence_id} href={`/geo/${workspaceId}/evidence/${row.evidence_id}`}>
              {row.model_label} · {evidenceLabel(row)} <span aria-hidden="true">↗</span>
            </Link>)}
          </div>
        </details>;
      })}
    </div> : <div className={styles.diagnosticEmpty}>
      <span>◎</span><h3>当前没有可确认的竞品胜出</h3>
      <p>真实 0 保持可见；扩大问题或模型采样后再判断，不补写虚构原因。</p>
    </div>}
  </section>;
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
      <BrandRanking workspaceId={workspaceId} brands={group.brands} />
    </article>)}
  </section>;
}

export default async function CompetitorComparisonPage({ params, searchParams }: Props) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const period = PERIODS.has(first(query.period) ?? "") ? first(query.period)! : "90";
  const model = first(query.model) || "all";
  const question = Number(first(query.question) || 0);
  const view = VIEWS.has(first(query.view) ?? "") ? first(query.view)! : "overall";

  let comparison: CleanroomCompetitorComparison;
  try {
    comparison = await getCleanroomCompetitorComparison(workspaceId, {
      periodDays: Number(period),
      modelKey: model,
      questionPlanId: question > 0 ? question : undefined,
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
  const selectedModel = model === "all"
    ? "全部已测模型"
    : comparison.available_models.find((item) => item.key === model)?.label ?? model;
  const selectedQuestion = question > 0
    ? comparison.available_questions.find((item) => item.id === question)?.question_text ?? `问题 #${question}`
    : "全部已选问题";

  function viewHref(nextView: string) {
    const next = new URLSearchParams({ period, view: nextView });
    if (model !== "all") next.set("model", model);
    if (question > 0) next.set("question", String(question));
    return `/geo/${workspaceId}/competitors?${next.toString()}`;
  }

  return <div className={`${styles.page} geo-competitors-page`}>
    <header className={styles.topbar}>
      <Link className={styles.brand} href={`/geo/${workspaceId}`}><span aria-hidden="true">◈</span><b>春秋元泉 GEO</b></Link>
      <nav className={styles.toplinks} aria-label="GEO 主导航">
        <Link href={`/geo/${workspaceId}`}>决策地图</Link>
        <Link aria-current="page" href={`/geo/${workspaceId}/competitors` as Route}>竞品对比</Link>
        <Link href={`/geo/${workspaceId}/actions`}>优化行动</Link>
        <Link href="/admin/providers">模型与渠道</Link>
      </nav>
    </header>

    <main className={styles.main}>
      <section className={styles.heading}>
        <div><span>竞争情报</span><h1>竞品对比</h1><p>看清真实 AI 采购回答里，各品牌被提到的频率与对比信号。</p></div>
        <form method="get" className={styles.filters} aria-label="筛选竞品对比">
          <input type="hidden" name="view" value={view} />
          <select name="period" defaultValue={period} aria-label="统计范围">
            <option value="7">近 7 天</option><option value="30">近 30 天</option>
            <option value="90">近 90 天</option><option value="3650">全部归档</option>
          </select>
          <select name="model" defaultValue={model} aria-label="模型">
            <option value="all">全部模型</option>
            {comparison.available_models.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
          <select name="question" defaultValue={question || "all"} aria-label="问题">
            <option value="all">全部问题</option>
            {comparison.available_questions.map((item) => <option key={item.id} value={item.id}>{item.question_text}</option>)}
          </select>
          <button type="submit">应用</button>
        </form>
      </section>

      <section className={styles.summary} aria-labelledby="comparison-headline">
        <div className={styles.conclusion}><small>本轮结论</small><h2 id="comparison-headline">{headline}</h2><p>{comparison.summary.answer_count} 条真实回答 · {comparison.by_model.filter((item) => item.answer_count > 0).length} 个模型</p></div>
        <dl>
          <div><dt>品牌出现率</dt><dd>{baseline.mention_rate}%</dd><small>{baseline.hit_answer_count}/{baseline.sample_answer_count} 条</small></div>
          <div><dt>平均位置</dt><dd>{explicitPositionLabel(baseline)}</dd><small>{baseline.explicit_rank_observation_count} 条有明确排序</small></div>
          <div><dt>对比信号</dt><dd>{comparison.summary.answers_where_competitor_wins}</dd><small>仅用于回看同一回答</small></div>
        </dl>
        <div className={styles.gap}><span>最高竞品出现率</span><b>{topAppearingCompetitor ? `${topAppearingCompetitor.canonical_name} · ${topAppearingCompetitor.hit_answer_count}/${topAppearingCompetitor.sample_answer_count} 条（${topAppearingCompetitor.mention_rate}%）` : "当前没有追踪竞品"}</b><a href="#action-diagnostics">查看对比信号 →</a></div>
      </section>

      <div className={styles.comparisonGrid}>
        <section className={styles.ranking} id="competitor-leaderboard">
          <header><div><h2>品牌出现率排行榜</h2><p>出现率 = 品牌出现的回答数 ÷ 当前筛选的有效回答总数；真实 0 保留。</p></div><span>{scopeLabel}</span></header>
          <BrandRanking workspaceId={workspaceId} brands={comparison.brands} />
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
          <DiagnosticPanel workspaceId={workspaceId} items={comparison.action_diagnostics} />
        </aside>
      </div>

      {view === "model" ? <BreakdownSections workspaceId={workspaceId} groups={comparison.by_model} /> : null}
      {view === "question" ? <BreakdownSections workspaceId={workspaceId} groups={comparison.by_question} /> : null}

    </main>
  </div>;
}
