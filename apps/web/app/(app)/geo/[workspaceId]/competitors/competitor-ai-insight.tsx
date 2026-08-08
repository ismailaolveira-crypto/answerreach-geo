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
import styles from "./competitor-ai-insight.module.css";

export function CompetitorAiInsight({
  workspaceId,
  periodDays,
  modelKey,
  questionPlanId,
}: {
  workspaceId: string;
  periodDays: number;
  modelKey: string;
  questionPlanId?: number;
}) {
  const [insight, setInsight] = useState<CompetitorInsight | null>(null);
  const [status, setStatus] = useState<"restoring" | "idle" | "generating" | "error">("restoring");
  const [error, setError] = useState("");
  const [errorMode, setErrorMode] = useState<"restore" | "generate">("restore");
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const scope: InsightScopeKey = { workspaceId, periodDays, modelKey, questionPlanId };
  const reportHref = `/geo/${workspaceId}/competitors/report?period=${periodDays}&model=${encodeURIComponent(modelKey)}&question=${questionPlanId ?? "all"}`;

  useEffect(() => {
    const activeScope = { workspaceId, periodDays, modelKey, questionPlanId };
    const cached = readCompetitorInsight(activeScope);
    const controller = new AbortController();
    setInsight(cached);
    setStatus("restoring");
    setError("");
    void fetchCompetitorInsight(activeScope, controller.signal)
      .then((saved) => {
        if (saved) {
          storeCompetitorInsight(activeScope, saved);
          setInsight(saved);
        } else {
          clearCompetitorInsight(activeScope);
          setInsight(null);
        }
        setStatus("idle");
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setErrorMode("restore");
        setError(cause instanceof Error ? cause.message : "暂时无法读取已保存报告。");
        setStatus("error");
      });
    return () => controller.abort();
  }, [workspaceId, periodDays, modelKey, questionPlanId, restoreAttempt]);

  async function generate() {
    setStatus("generating");
    setError("");
    try {
      const response = await fetch(`/api/geo/${workspaceId}/competitor-insights`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          period_days: periodDays,
          model_key: modelKey === "all" ? undefined : modelKey,
          question_plan_id: questionPlanId,
        }),
      });
      const payload = await response.json().catch(() => null) as CompetitorInsight | { detail?: string } | null;
      if (!response.ok || !payload || !("analysis" in payload)) {
        throw new Error((payload && "detail" in payload && payload.detail) || "生成失败，请稍后重试。");
      }
      storeCompetitorInsight(scope, payload);
      setInsight(payload);
      setStatus("idle");
    } catch (cause) {
      setErrorMode("generate");
      setStatus("error");
      setError(cause instanceof Error ? cause.message : "生成失败，请稍后重试。");
    }
  }

  const busy = status === "restoring" || status === "generating";
  const buttonLabel = status === "restoring"
    ? "读取中"
    : status === "generating"
      ? "生成中"
      : insight?.is_stale
        ? "按新数据重新生成"
        : insight
          ? "重新生成"
          : "生成分析";

  return <section className={styles.panel} aria-labelledby="ai-insight-title" aria-busy={busy}>
    <header className={styles.header}>
      <div>
        <p>DeepSeek 范围洞察</p>
        <h2 id="ai-insight-title">本次筛选的分析报告</h2>
        <span>仅使用当前范围的聚合统计与证据摘要，不写入观测记录。</span>
      </div>
      <button type="button" onClick={generate} disabled={busy}>
        {buttonLabel}
      </button>
    </header>

    {status === "idle" && !insight ? <div className={styles.empty}>
      <b>尚未生成范围分析</b><span>生成后先展示一段核心结论，完整报告单独打开。</span>
    </div> : null}
    {status === "restoring" && !insight ? <div className={styles.loading} role="status"><i /><span>正在读取这个筛选范围的账号报告…</span></div> : null}
    {status === "generating" ? <div className={styles.loading} role="status"><i /><span>正在核对真实证据并请求 DeepSeek，完成后会自动保存。</span></div> : null}
    {status === "error" ? <div className={styles.error} role="alert"><b>{errorMode === "restore" ? "未能读取账号报告" : "未能生成分析"}</b><span>{error}</span><button type="button" onClick={errorMode === "restore" ? () => setRestoreAttempt((value) => value + 1) : generate}>{errorMode === "restore" ? "重新读取" : "重试生成"}</button></div> : null}

    {insight ? <div className={styles.result}>
      <div className={styles.scope}><span>{insight.provider} · {insight.model}</span><time>{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(insight.generated_at))}</time></div>
      {insight.is_stale ? <div className={styles.staleNotice} role="status"><b>筛选数据已更新</b><span>这是上次保存的报告。重新生成后，结论才会反映当前证据。</span></div> : null}
      <div className={styles.coreConclusion}>
        <span>核心结论</span>
        <p>{insight.analysis.overall_assessment}</p>
      </div>
      <Link className={styles.reportLink} href={reportHref as Route}>查看完整报告 <span aria-hidden="true">→</span></Link>
      <small className={styles.sessionNote}>{insight.persisted ? `已保存到当前账号${insight.snapshot_id ? ` · 报告 #${insight.snapshot_id}` : ""}，可跨刷新打开。` : "当前仅显示浏览器缓存，账号保存状态暂未确认。"}</small>
    </div> : null}
  </section>;
}
