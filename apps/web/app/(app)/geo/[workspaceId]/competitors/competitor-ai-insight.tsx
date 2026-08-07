"use client";

import Link from "next/link";
import { useState } from "react";
import styles from "./competitor-ai-insight.module.css";

type Insight = {
  provider: string;
  model: string;
  generated_at: string;
  scope: { kind: string; period: string; model: string; question: string; answer_count: number };
  analysis: {
    scope_summary: string;
    overall_assessment: string;
    findings: Array<{ title: string; detail: string; evidence_ids: number[] }>;
    recommended_actions: string[];
    limitations: string[];
  };
};

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
  const [insight, setInsight] = useState<Insight | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");

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
      const payload = await response.json().catch(() => null) as Insight | { detail?: string } | null;
      if (!response.ok || !payload || !("analysis" in payload)) {
        throw new Error((payload && "detail" in payload && payload.detail) || "生成失败，请稍后重试。");
      }
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
        <h2 id="ai-insight-title">根据当前筛选范围给出分析结论</h2>
        <span>仅发送当前范围的聚合统计和证据摘要，不写入观测记录。</span>
      </div>
      <button type="button" onClick={generate} disabled={status === "loading"}>
        {status === "loading" ? "正在生成" : insight ? "重新生成" : "生成分析"}
      </button>
    </header>
    {status === "idle" && !insight ? <div className={styles.empty}>
      <b>尚未生成范围分析</b><span>选择时间、模型和问题后再生成，结论会绑定此刻的筛选范围。</span>
    </div> : null}
    {status === "loading" ? <div className={styles.loading} role="status"><i /><span>正在核对范围内数据并请求 DeepSeek，请稍候。</span></div> : null}
    {status === "error" ? <div className={styles.error} role="alert"><b>未能生成分析</b><span>{error}</span><button type="button" onClick={generate}>重试</button></div> : null}
    {insight ? <div className={styles.result}>
      <div className={styles.scope}><span>{insight.provider} · {insight.model}</span><time>{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(insight.generated_at))}</time></div>
      <p className={styles.scopeSummary}>{insight.analysis.scope_summary}</p>
      <p className={styles.assessment}>{insight.analysis.overall_assessment}</p>
      <div className={styles.findings}>{insight.analysis.findings.map((finding) => <article key={`${finding.title}-${finding.detail}`}>
        <h3>{finding.title}</h3><p>{finding.detail}</p>
        {finding.evidence_ids.length ? <div>{finding.evidence_ids.map((id) => <Link key={id} href={`/geo/${workspaceId}/evidence/${id}`}>证据 #{id}</Link>)}</div> : <small>模型未引用单条证据</small>}
      </article>)}</div>
      <div className={styles.bottomGrid}>
        <section><h3>建议行动</h3><ol>{insight.analysis.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ol></section>
        <section><h3>结论边界</h3><ul>{insight.analysis.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section>
      </div>
    </div> : null}
  </section>;
}
