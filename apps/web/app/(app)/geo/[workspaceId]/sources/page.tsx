import Link from "next/link";
import type { Route } from "next";
import { notFound } from "next/navigation";
import { getCleanroomSourceMap, type SourceMapItem } from "@/lib/cleanroom-v1-api";
import styles from "./source-map.module.css";
import { SourceBoard } from "./source-board";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";

type Props = {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const PERIODS = new Set(["7", "30", "90", "365", "3650"]);

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function number(value: number) {
  return value.toLocaleString("zh-CN");
}

function LegacyEvidenceLinks({ workspaceId, item }: { workspaceId: string; item: SourceMapItem }) {
  const references = item.evidence_references.length
    ? item.evidence_references
    : item.evidence_ids.map((evidence_id) => ({ evidence_id, source_url: "" }));
  return <div className={styles.legacyEvidenceLinks} aria-label={`核验 ${item.label} 的原始回答`}>
    {references.slice(0, 3).map((reference, index) => <Link
      key={`${reference.evidence_id}-${reference.source_url}`}
      href={`/geo/${workspaceId}/evidence/${reference.evidence_id}${reference.source_url ? `?source=${encodeURIComponent(reference.source_url)}` : ""}`}
    >证据 {index + 1}<span aria-hidden="true">↗</span></Link>)}
    {item.evidence_total > 3 ? <small>另有 {item.evidence_total - 3} 条</small> : null}
  </div>;
}

function LegacyBreakdown({ item }: { item: SourceMapItem }) {
  return <details className={styles.legacyBreakdown}>
    <summary>按模型 / 问题查看 <span aria-hidden="true">⌄</span></summary>
    <div>
      <section><h4>模型偏好</h4>{item.models.map((model) => <p key={model.key}><span>{model.label}</span><b>{model.citation_count} 次引用 · {model.answer_count} 条回答</b></p>)}</section>
      <section><h4>关联问题</h4>{item.questions.map((question) => <p key={question.id}><span>{question.text}</span><b>{question.citation_count} 次引用</b></p>)}</section>
    </div>
  </details>;
}

function LegacyRanking({
  title,
  description,
  items,
  workspaceId,
  pages = false,
}: {
  title: string;
  description: string;
  items: SourceMapItem[];
  workspaceId: string;
  pages?: boolean;
}) {
  return <section className={styles.legacyPanel}>
    <header><div><p>真实引用排行</p><h3>{title}</h3><span>{description}</span></div><small>{items.length} 项</small></header>
    <div className={styles.legacyRanking}>{items.map((item, index) => <article key={item.key}>
      <span>{String(index + 1).padStart(2, "0")}</span>
      <div>
        {pages && item.canonical_url ? <><a href={item.canonical_url} target="_blank" rel="noreferrer">{item.title || item.label}<i aria-hidden="true">↗</i></a><small>{item.label}</small></> : <h4>{item.label}</h4>}
        <div className={styles.legacyChips}><span>{number(item.citation_count)} 次引用</span><span>{number(item.answer_count)} 条回答</span><span>{item.model_count} 个模型</span>{item.brand_absent_answer_count ? <em>{item.brand_absent_answer_count} 条回答未出现品牌</em> : null}</div>
        <LegacyEvidenceLinks workspaceId={workspaceId} item={item} />
        <LegacyBreakdown item={item} />
      </div>
    </article>)}</div>
  </section>;
}

export default async function SourceMapPage({ params, searchParams }: Props) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const rangeDays = first(query.range)?.replace("d", "");
  const period = PERIODS.has(rangeDays ?? "") ? rangeDays! : PERIODS.has(first(query.period) ?? "") ? first(query.period)! : "30";
  const selectedModels = (Array.isArray(query.model) ? query.model : query.model ? [query.model] : []).filter((value) => value && value !== "all");
  const selectedQuestions = (Array.isArray(query.question) ? query.question : query.question ? [query.question] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0);
  const selectedBatches = (Array.isArray(query.batch) ? query.batch : query.batch ? [query.batch] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0);

  let sourceMap;
  try {
    sourceMap = await getCleanroomSourceMap(workspaceId, {
      periodDays: Number(period),
      dateFrom: first(query.range) === "custom" && first(query.from) ? `${first(query.from)}T00:00:00Z` : undefined,
      dateTo: first(query.range) === "custom" && first(query.to) ? `${first(query.to)}T23:59:59Z` : undefined,
      modelKeys: selectedModels,
      questionPlanIds: selectedQuestions,
      batchIds: selectedBatches,
      limit: 48,
    });
  } catch (error) {
    if (error instanceof Error && error.message.includes("404")) notFound();
    throw error;
  }

  const { summary } = sourceMap;
  const topSource = sourceMap.domains[0];

  return <div className={`${styles.page} geo-sources-page`}>
    <header className={styles.topbar}>
      <Link className={styles.brand} href={`/geo/${workspaceId}`}><img alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" /><b>入答 AnswerReach</b></Link>
      <nav aria-label="GEO 工作区导航">
        <Link href={`/geo/${workspaceId}`}>决策地图</Link>
        <Link aria-current="page" href={`/geo/${workspaceId}/sources`}>信源地图</Link>
        <Link href={`/geo/${workspaceId}/competitors` as Route}>竞品对比</Link>
        <Link href={`/geo/${workspaceId}/actions`}>优化行动</Link>
      </nav>
    </header>

    <main className={styles.main}>
      <section className={styles.hero}>
        <div>
          <p>Source intelligence</p>
          <h1>信源看板</h1>
          <span>按影响力分层，看清重要信源、共同引用关系与品牌机会。</span>
        </div>
        <dl className={styles.heroStats}>
          <div><dt>重点信源</dt><dd>{number(sourceMap.domains.length)}<small> / 共 {number(summary.unique_domain_count)}</small></dd></div>
          <div><dt>有效引用</dt><dd>{number(summary.citation_count)}</dd></div>
          <div><dt>覆盖问题</dt><dd>{number(sourceMap.available_questions.length)}</dd></div>
        </dl>
      </section>
      <GeoGlobalScopeBar workspaceId={workspaceId} />

      {summary.answers_with_sources === 0 ? <section className={styles.empty}>
        <span aria-hidden="true">↗</span><h2>还没有真实引用可分析</h2>
        <p>当前筛选命中了 {number(summary.answer_count)} 条真实回答，但没有可解析 URL。请先完成启用联网搜索的模型观测，或放宽筛选条件。</p>
        <Link href={`/geo/${workspaceId}`}>返回决策地图</Link>
      </section> : <>
        <SourceBoard
          workspaceId={workspaceId}
          items={sourceMap.domains}
          topSourceKey={topSource?.key ?? null}
        />

        <details className={styles.legacyMap}>
          <summary><span>展开完整信源地图</span><small>域名排行、具体页面、机会与逐条证据</small><i aria-hidden="true">⌄</i></summary>
          <div className={styles.legacyContent}>
            <section className={styles.legacyMetrics} aria-label="信源地图关键指标">
              <article><span>有效引用</span><strong>{number(summary.citation_count)}</strong><small>回答内重复 URL 已去重</small></article>
              <article><span>信源域名</span><strong>{number(summary.unique_domain_count)}</strong><small>已合并 scheme 与 www.</small></article>
              <article><span>有引用回答</span><strong>{number(summary.answers_with_sources)}</strong><small>共筛选 {number(summary.answer_count)} 条回答</small></article>
              <article><span>回答未出现品牌</span><strong>{summary.brand_absent_answer_ratio}%</strong><small>{summary.brand_absent_answer_count} 条，仅指回答文本</small></article>
            </section>
            <div className={styles.legacyGrid}>
              <LegacyRanking title="Top 信源域名" description="按真实回答中的引用频次排序。" items={sourceMap.domains} workspaceId={workspaceId} />
              <LegacyRanking title="Top 具体页面" description="保留规范化 URL 与原始页面入口。" items={sourceMap.pages} workspaceId={workspaceId} pages />
            </div>
            <section className={styles.legacyOpportunities}>
              <header><div><p>候选机会</p><h3>高频引用且回答未出现品牌</h3></div><small>{sourceMap.opportunities.length} 项</small></header>
              <div>{sourceMap.opportunities.map((item, index) => <article key={item.key}>
                <span>{String(index + 1).padStart(2, "0")}</span><div><h4>{item.label}</h4><p>{item.reason}</p><LegacyEvidenceLinks workspaceId={workspaceId} item={item} /></div><strong>{item.brand_absent_answer_ratio}%<small>对应回答未出现品牌</small></strong>
              </article>)}</div>
            </section>
          </div>
        </details>
      </>}
    </main>
  </div>;
}
