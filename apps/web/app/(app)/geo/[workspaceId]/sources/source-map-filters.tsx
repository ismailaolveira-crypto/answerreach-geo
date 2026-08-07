"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { useMemo, useState, useTransition } from "react";
import styles from "./source-map.module.css";

type Option = { key: string; label: string };

export function SourceMapFilters({
  period,
  model,
  question,
  models,
  questions,
}: {
  period: string;
  model: string;
  question: number;
  models: Option[];
  questions: Array<{ id: number; question_text: string }>;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();
  const [draft, setDraft] = useState({ period, model, question: question ? String(question) : "all" });
  const isDirty = useMemo(
    () => draft.period !== period || draft.model !== model || draft.question !== (question ? String(question) : "all"),
    [draft, model, period, question],
  );

  function apply() {
    const params = new URLSearchParams(searchParams.toString());
    params.set("period", draft.period);
    if (draft.model === "all") params.delete("model"); else params.set("model", draft.model);
    if (draft.question === "all") params.delete("question"); else params.set("question", draft.question);
    startTransition(() => router.push(`${pathname}?${params.toString()}` as Route));
  }

  return <div className={styles.filters} aria-label="筛选信源地图">
    <label><span>时间范围</span><select value={draft.period} disabled={isPending} onChange={(event) => setDraft((value) => ({ ...value, period: event.target.value }))}>
      <option value="7">近 7 天</option><option value="30">近 30 天</option>
      <option value="90">近 90 天</option><option value="3650">全部归档</option>
    </select></label>
    <label><span>模型</span><select value={draft.model} disabled={isPending} onChange={(event) => setDraft((value) => ({ ...value, model: event.target.value }))}>
      <option value="all">全部模型</option>
      {models.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
    </select></label>
    <label><span>问题</span><select value={draft.question} disabled={isPending} onChange={(event) => setDraft((value) => ({ ...value, question: event.target.value }))}>
      <option value="all">全部问题</option>
      {questions.map((item) => <option key={item.id} value={item.id}>{item.question_text}</option>)}
    </select></label>
    <button type="button" disabled={isPending || !isDirty} onClick={apply} aria-live="polite">
      {isPending ? <><i className={styles.filterSpinner} aria-hidden="true" />正在更新</> : "应用筛选"}
    </button>
    <span className={styles.filterStatus} aria-live="polite">{isPending ? "正在读取已归档的真实引用…" : ""}</span>
  </div>;
}
