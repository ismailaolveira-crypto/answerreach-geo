"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";
import {
  clearCompetitorInsight,
  fetchCompetitorInsight,
  readCompetitorInsight,
  storeCompetitorInsight,
  type CompetitorInsight,
  type InsightScopeKey,
} from "./competitor-insight-store";
import styles from "./competitor-insight-report.module.css";

export function CompetitorInsightReport({
  workspaceId,
  periodDays,
  modelKey,
  questionPlanId,
}: InsightScopeKey) {
  const [insight, setInsight] = useState<CompetitorInsight | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const comparisonHref = `/geo/${workspaceId}/competitors?view=overall&period=${periodDays}&model=${encodeURIComponent(modelKey)}&question=${questionPlanId ?? "all"}`;

  useEffect(() => {
    const activeScope = { workspaceId, periodDays, modelKey, questionPlanId };
    const cached = readCompetitorInsight(activeScope);
    const controller = new AbortController();
    setInsight(cached);
    setLoaded(false);
    setLoadError("");
    void fetchCompetitorInsight(activeScope, controller.signal)
      .then((saved) => {
        if (saved) {
          storeCompetitorInsight(activeScope, saved);
          setInsight(saved);
        } else {
          clearCompetitorInsight(activeScope);
          setInsight(null);
        }
        setLoaded(true);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setLoadError(cause instanceof Error ? cause.message : "暂时无法读取已保存报告。");
        setLoaded(true);
      });
    return () => controller.abort();
  }, [workspaceId, periodDays, modelKey, questionPlanId, restoreAttempt]);

  if (!loaded) return <main className={styles.page}><div className={styles.loading} role="status"><i /><span>正在读取当前账号保存的报告…</span></div></main>;

  if (!insight) return <main className={styles.page}>
    <section className={styles.empty}>
      <span>◇</span><p>竞品范围分析报告</p><h1>{loadError ? "暂时无法读取账号报告" : "尚未生成这个筛选范围的报告"}</h1>
      <div>{loadError || "报告不会伪造或补写。请先回到竞品对比，按相同筛选范围生成分析。"}</div>
      {loadError ? <button type="button" onClick={() => setRestoreAttempt((value) => value + 1)}>重新读取</button> : null}
      <Link href={comparisonHref as Route}>返回竞品对比</Link>
    </section>
  </main>;

  const evidenceIds = [...new Set(insight.analysis.findings.flatMap((item) => item.evidence_ids))];
  const generatedAt = new Intl.DateTimeFormat("zh-CN", { dateStyle: "long", timeStyle: "short" }).format(new Date(insight.generated_at));

  return <main className={styles.page}>
    <div className={styles.reportShell}>
      <header className={styles.topbar}>
        <Link href={comparisonHref as Route} className={styles.back}>← 返回竞品对比</Link>
        <div className={styles.actions}>
          <button type="button" onClick={() => window.print()}>导出 PDF</button>
        </div>
      </header>

      <article className={styles.report}>
        {loadError ? <div className={styles.syncWarning} role="alert"><b>账号报告状态暂未确认</b><span>当前显示浏览器缓存。{loadError}</span></div> : null}
        {insight.is_stale ? <div className={styles.staleWarning} role="status"><b>这是一份历史快照</b><span>当前筛选数据已经变化。报告内容保持原样，避免把旧结论伪装成当前结论；请返回竞品对比重新生成。</span></div> : null}
        <header className={styles.reportHeader}>
          <div><span>GEO · 范围分析报告</span><h1>竞品对比洞察</h1><p>{insight.analysis.scope_summary}</p></div>
          <dl><div><dt>分析范围</dt><dd>{insight.scope.period}</dd></div><div><dt>真实回答</dt><dd>{insight.scope.answer_count} 条</dd></div><div><dt>生成模型</dt><dd>{insight.provider} · {insight.model}</dd></div><div><dt>保存状态</dt><dd>{insight.persisted ? `账号报告${insight.snapshot_id ? ` #${insight.snapshot_id}` : ""}` : "浏览器缓存"}</dd></div></dl>
        </header>

        <section className={styles.section} aria-labelledby="core-conclusion">
          <div className={styles.sectionHeading}><span>01</span><div><p>核心结论</p><h2 id="core-conclusion">先看一句可执行的判断</h2></div></div>
          <div className={styles.coreConclusion}>{insight.analysis.overall_assessment}</div>
        </section>

        <section className={styles.section} aria-labelledby="analysis-body">
          <div className={styles.sectionHeading}><span>02</span><div><p>主体分析内容</p><h2 id="analysis-body">当前范围下的关键观察</h2></div></div>
          <div className={styles.analysisReader}>
            <header><span aria-hidden="true">✦</span><div><b>分析正文</b><small>随页面自然阅读 · 已绑定生成时的筛选范围</small></div></header>
            <div className={styles.analysisNarrative}>
              {insight.analysis.findings.map((finding, index) => <article key={`${finding.title}-${index}`}>
                <span>{String(index + 1).padStart(2, "0")}</span><div><h3>{finding.title}</h3><p>{finding.detail}</p>
                  {finding.evidence_ids.length ? <div className={styles.inlineEvidence}>对应证据：{finding.evidence_ids.map((id) => <Link key={id} href={`/geo/${workspaceId}/evidence/${id}`}>#{id}</Link>)}</div> : <small>本段未引用单条证据</small>}
                </div>
              </article>)}
            </div>
          </div>
          <div className={styles.recommendations}><h3>建议行动</h3><ol>{insight.analysis.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ol></div>
        </section>

        <section className={styles.section} aria-labelledby="evidence">
          <div className={styles.sectionHeading}><span>03</span><div><p>引用证据</p><h2 id="evidence">可回到原回答逐条复核</h2></div></div>
          {evidenceIds.length ? <div className={styles.evidenceList}>{evidenceIds.map((id) => <Link key={id} href={`/geo/${workspaceId}/evidence/${id}`}>
            <b>证据 #{id}</b><span>打开原回答与关联引用</span><i aria-hidden="true">↗</i>
          </Link>)}</div> : <p className={styles.noEvidence}>本次模型没有引用单条证据；结论仅应按范围统计理解。</p>}
        </section>

        <footer className={styles.footer}>由 {insight.provider} · {insight.model} 于 {generatedAt} 基于生成时的筛选范围完成。该报告是分析快照，不计入 GEO 观测指标。{insight.analysis.limitations.join(" ")}</footer>
      </article>
    </div>
  </main>;
}
