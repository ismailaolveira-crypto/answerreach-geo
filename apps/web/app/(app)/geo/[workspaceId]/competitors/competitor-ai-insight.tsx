"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";
import {
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
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");
  const scope: InsightScopeKey = { workspaceId, periodDays, modelKey, questionPlanId };
  const reportHref = `/geo/${workspaceId}/competitors/report?period=${periodDays}&model=${encodeURIComponent(modelKey)}&question=${questionPlanId ?? "all"}`;

  useEffect(() => {
    setInsight(readCompetitorInsight(scope));
  }, [workspaceId, periodDays, modelKey, questionPlanId]);

  async function generate() {
    setStatus("loading");
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
      setStatus("error");
      setError(cause instanceof Error ? cause.message : "生成失败，请稍后重试。");
    }
  }

  return <section className={styles.panel} aria-labelledby="ai-insight-title">
    <header className={styles.header}>
      <div>
        <p>DeepSeek 范围洞察</p>
        <h2 id="ai-insight-title">本次筛选的分析报告</h2>
        <span>仅使用当前范围的聚合统计与证据摘要，不写入观测记录。</span>
      </div>
      <button type="button" onClick={generate} disabled={status === "loading"}>
        {status === "loading" ? "生成中" : insight ? "重新生成" : "生成分析"}
      </button>
    </header>

    {status === "idle" && !insight ? <div className={styles.empty}>
      <b>尚未生成范围分析</b><span>生成后先展示一段核心结论，完整报告单独打开。</span>
    </div> : null}
    {status === "loading" ? <div className={styles.loading} role="status"><i /><span>正在核对当前范围并请求 DeepSeek，请稍候。</span></div> : null}
    {status === "error" ? <div className={styles.error} role="alert"><b>未能生成分析</b><span>{error}</span><button type="button" onClick={generate}>重试</button></div> : null}

    {insight ? <div className={styles.result}>
      <div className={styles.scope}><span>{insight.provider} · {insight.model}</span><time>{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(insight.generated_at))}</time></div>
      <div className={styles.coreConclusion}>
        <span>核心结论</span>
        <p>{insight.analysis.overall_assessment}</p>
      </div>
      <Link className={styles.reportLink} href={reportHref as Route}>查看完整报告 <span aria-hidden="true">→</span></Link>
      <small className={styles.sessionNote}>报告仅保留在当前浏览器会话，刷新与打印均可复核生成范围。</small>
    </div> : null}
  </section>;
}
