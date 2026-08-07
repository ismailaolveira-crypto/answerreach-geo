import Link from "next/link";
import type { Route } from "next";
import { notFound } from "next/navigation";
import {
  getCleanroomSourceMap,
  type SourceMapItem,
} from "@/lib/cleanroom-v1-api";
import styles from "./source-map.module.css";
import { SourceMapFilters } from "./source-map-filters";

type Props = {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const PERIODS = new Set(["7", "30", "90", "3650"]);

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function number(value: number) {
  return value.toLocaleString("zh-CN");
}

function EvidenceLinks({ workspaceId, item }: { workspaceId: string; item: SourceMapItem }) {
  return <div className={styles.evidenceLinks} aria-label={`核验 ${item.label} 的原始回答`}>
    {item.evidence_ids.slice(0, 3).map((evidenceId, index) => (
      <Link key={evidenceId} href={`/geo/${workspaceId}/evidence/${evidenceId}`}>
        证据 {index + 1}<span aria-hidden="true">↗</span>
      </Link>
    ))}
    {item.evidence_total > 3 ? <small>另有 {item.evidence_total - 3} 条</small> : null}
  </div>;
}

function Breakdown({ item }: { item: SourceMapItem }) {
  return <details className={styles.breakdown}>
    <summary>按模型 / 问题查看 <span aria-hidden="true">⌄</span></summary>
    <div>
      <section>
        <h4>模型偏好</h4>
        {item.models.map((model) => <p key={model.key}>
          <span>{model.label}</span><b>{model.citation_count} 次引用 · {model.answer_count} 条回答</b>
        </p>)}
      </section>
      <section>
        <h4>关联问题</h4>
        {item.questions.map((question) => <p key={question.id}>
          <span>{question.text}</span><b>{question.citation_count} 次引用</b>
        </p>)}
      </section>
    </div>
  </details>;
}

function Ranking({
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
  return <section className={styles.panel}>
    <header className={styles.panelHeader}>
      <div><p>真实引用排行</p><h2>{title}</h2><span>{description}</span></div>
      <small>{items.length} 项</small>
    </header>
    <div className={styles.ranking}>
      {items.map((item, index) => <article className={styles.rankRow} key={item.key}>
        <span className={styles.rank}>{String(index + 1).padStart(2, "0")}</span>
        <div className={styles.rankMain}>
          <div className={styles.rankTitle}>
            {pages && item.canonical_url
              ? <a href={item.canonical_url} target="_blank" rel="noreferrer">{item.title || item.label}<i aria-hidden="true">↗</i></a>
              : <h3>{item.label}</h3>}
            {pages ? <small>{item.label}</small> : null}
          </div>
          <div className={styles.chips}>
            <span>{number(item.citation_count)} 次引用</span>
            <span>{number(item.answer_count)} 条回答</span>
            <span>{item.model_count} 个模型</span>
            <span className={item.brand_absent_answer_count ? styles.opportunityChip : undefined}>
              {item.brand_absent_answer_count} 条回答未出现品牌
            </span>
          </div>
          <EvidenceLinks workspaceId={workspaceId} item={item} />
          <Breakdown item={item} />
        </div>
      </article>)}
    </div>
  </section>;
}

export default async function SourceMapPage({ params, searchParams }: Props) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const period = PERIODS.has(first(query.period) ?? "") ? first(query.period)! : "30";
  const selectedModel = first(query.model) || "all";
  const selectedQuestion = Number(first(query.question) || 0);
  let sourceMap;
  try {
    sourceMap = await getCleanroomSourceMap(workspaceId, {
      periodDays: Number(period),
      modelKey: selectedModel,
      questionPlanId: selectedQuestion > 0 ? selectedQuestion : undefined,
      limit: 12,
    });
  } catch (error) {
    if (error instanceof Error && error.message.includes("404")) notFound();
    throw error;
  }

  const summary = sourceMap.summary;
  const topDomain = sourceMap.domains[0];
  const conclusion = topDomain
    ? `${topDomain.label} 以 ${number(topDomain.citation_count)} 次引用居首，覆盖 ${topDomain.model_count} 个模型；其中 ${topDomain.brand_absent_answer_count} 条对应回答未出现“${sourceMap.workspace.brand_name}”。建议先核验这些回答与引用页面，再决定投放或内容补强。`
    : "当前筛选范围内没有可解析的真实引用。完成一次启用联网搜索的真实观测后，这里会自动形成排行与机会清单。";

  return <div className={`${styles.page} geo-sources-page`}>
    <header className={styles.topbar}>
      <Link className={styles.brand} href={`/geo/${workspaceId}`}><span>◈</span><b>春秋元泉 GEO</b></Link>
      <nav aria-label="GEO 工作区导航">
        <Link href={`/geo/${workspaceId}`}>决策地图</Link>
        <Link aria-current="page" href={`/geo/${workspaceId}/sources`}>信源地图</Link>
        <Link href={`/geo/${workspaceId}/competitors` as Route}>竞品对比</Link>
        <Link href={`/geo/${workspaceId}/actions`}>优化行动</Link>
      </nav>
    </header>

    <main className={styles.main}>
      <section className={styles.hero}>
        <div><h1>信源地图</h1><span>看清 AI 反复引用哪里，并从原始回答核验每一个数字。</span></div>
        <SourceMapFilters period={period} model={selectedModel} question={selectedQuestion} models={sourceMap.available_models} questions={sourceMap.available_questions} />
      </section>

      <section className={styles.conclusion} aria-labelledby="source-conclusion">
        <span className={styles.conclusionIcon} aria-hidden="true">✓</span>
        <div><p>优先核验</p><h2 id="source-conclusion">{conclusion}</h2></div>
        {topDomain ? <a className={styles.conclusionAction} href="#source-opportunities">
          查看 {topDomain.brand_absent_answer_count} 条回答对应的核验机会 <span aria-hidden="true">→</span>
        </a> : null}
      </section>

      <section className={styles.metrics} aria-label="信源地图关键指标">
        <article><span className={styles.metricIcon} aria-hidden="true">↗</span><div><span>有效引用</span><strong>{number(summary.citation_count)}</strong><small>同一回答内重复 URL 已去重</small></div></article>
        <article><span className={styles.metricIcon} aria-hidden="true">◎</span><div><span>信源域名</span><strong>{number(summary.unique_domain_count)}</strong><small>已合并 scheme 与 www.</small></div></article>
        <article><span className={styles.metricIcon} aria-hidden="true">▤</span><div><span>有引用回答</span><strong>{number(summary.answers_with_sources)}</strong><small>共筛选 {number(summary.answer_count)} 条真实回答</small></div></article>
        <article><span className={styles.metricIcon} aria-hidden="true">✓</span><div><span>回答未出现品牌</span><strong>{summary.brand_absent_answer_ratio}%</strong><small>{summary.brand_absent_answer_count} 条，仅指回答文本</small></div></article>
      </section>

      <aside className={styles.notice} role="note"><b>数据说明</b><span>{sourceMap.interpretation_notice}</span></aside>

      {summary.answers_with_sources === 0 ? <section className={styles.empty}>
        <span aria-hidden="true">↗</span><h2>还没有真实引用可分析</h2>
        <p>当前筛选命中了 {summary.answer_count} 条真实回答，但没有可解析 URL。请先在决策地图完成启用联网搜索的模型观测，或放宽时间、模型和问题筛选。</p>
        <Link href={`/geo/${workspaceId}`}>返回决策地图</Link>
      </section> : <>
        <div className={styles.grid}>
          <Ranking title="Top 信源域名" description="一个回答可引用同域名下多个页面，因此引用次数与回答数分开计算。" items={sourceMap.domains} workspaceId={workspaceId} />
          <Ranking title="Top 具体页面" description="URL 已去除片段、统一尾斜杠并排序查询参数；外链不代表已核验正文。" items={sourceMap.pages} workspaceId={workspaceId} pages />
        </div>

        <section className={styles.opportunities} id="source-opportunities">
          <header><div><p>优先研究 / 投放机会</p><h2>从“高频引用 + 回答未出现品牌”开始核验</h2></div><small>{sourceMap.opportunities.length} 个候选信源</small></header>
          <div>
            {sourceMap.opportunities.map((item, index) => <article key={item.key}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><h3>{item.label}</h3><p>{item.reason}</p><EvidenceLinks workspaceId={workspaceId} item={item} /></div>
              <strong>{item.brand_absent_answer_ratio}%<small>引用回答未出现品牌</small></strong>
            </article>)}
          </div>
        </section>
      </>}

      <footer className={styles.auditNote}>
        已忽略 {summary.ignored_source_count} 条无效 URL，合并 {summary.duplicate_source_count} 条回答内重复 URL；另排除 {summary.excluded_non_real_answer_count} 条非真实提供方证据。
      </footer>
    </main>
  </div>;
}
