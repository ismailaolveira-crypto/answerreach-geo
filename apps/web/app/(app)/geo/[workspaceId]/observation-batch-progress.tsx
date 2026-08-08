"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { BrandLogo } from "@/components/brand-logo";
import type { OfficialApiObservationBatch } from "@/lib/cleanroom-v1-api";

const SETTLED = new Set(["success", "partial", "failed"]);

function summary(batch: OfficialApiObservationBatch) {
  if (batch.status === "success") return "本批次真实观测已全部完成";
  if (batch.status === "partial") return "本批次已结束，部分观测需要重试";
  if (batch.status === "failed") return "本批次未获得有效结果";
  if (batch.running) return "正在采集真实联网结果";
  return "任务已排队，等待采集服务";
}

function conciseProviderLabel(label: string) {
  return label.split("·", 1)[0]?.trim() || label;
}

export default function ObservationBatchProgress({
  workspaceId,
  initialBatch,
}: {
  workspaceId: string;
  initialBatch: OfficialApiObservationBatch;
}) {
  const router = useRouter();
  const [batch, setBatch] = useState(initialBatch);
  const [pollError, setPollError] = useState("");
  const refreshed = useRef(false);
  const lastSettled = useRef(initialBatch.succeeded + initialBatch.failed);
  const completed = batch.succeeded + batch.failed;
  const isRunning = batch.running > 0;
  const isQueued = !isRunning && batch.pending > 0 && !SETTLED.has(batch.status);
  const statusPercentages = batch.status_percentages ?? {
    succeeded: batch.total ? Math.round((batch.succeeded / batch.total) * 100) : 0,
    running: batch.total ? Math.round((batch.running / batch.total) * 100) : 0,
    pending: batch.total ? Math.round((batch.pending / batch.total) * 100) : 0,
    failed: batch.total ? Math.round((batch.failed / batch.total) * 100) : 0,
  };

  useEffect(() => {
    if (completed > lastSettled.current) {
      lastSettled.current = completed;
      // KPI cards are server-calculated from this batch's archived evidence.
      // Refresh only when a task settles, never on every polling tick.
      router.refresh();
    }
    if (SETTLED.has(batch.status)) {
      if (!refreshed.current) {
        refreshed.current = true;
        router.refresh();
      }
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`/api/geo/${workspaceId}/observation-batches/${batch.batch_id}`, { cache: "no-store" });
        if (!response.ok) throw new Error("进度同步暂时中断");
        setBatch(await response.json() as OfficialApiObservationBatch);
        setPollError("");
      } catch (error) {
        setPollError(error instanceof Error ? error.message : "进度同步暂时中断");
      }
    }, pollError ? 3000 : 1200);
    return () => window.clearTimeout(timer);
  }, [batch, completed, pollError, router, workspaceId]);

  return <section className={`sy-batch-progress is-${batch.status}`} role="status" aria-live="polite">
    <header>
      <div><span>批次 #{batch.batch_id}</span><h2>{summary(batch)}</h2><p>{batch.provider_count} 个模型 × {batch.question_count} 个问题 × {batch.repeat_count} 次，共 {batch.total} 条</p></div>
      <div className="sy-batch-progress-actions"><strong>{batch.progress_percent}<small>%</small></strong></div>
    </header>
    <div className="sy-batch-progress-bar" role="progressbar" aria-label={`批次 ${batch.batch_id} 整体完成进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={batch.progress_percent}><i style={{ width: `${batch.progress_percent}%` }} /></div>
    <div className="sy-batch-counters">
      <span><i className="is-success" />成功 <b>{batch.succeeded}</b><em>{statusPercentages.succeeded}%</em></span>
      <span><i className="is-running" />运行中 <b>{batch.running}</b><em>{statusPercentages.running}%</em></span>
      <span><i className="is-pending" />等待 <b>{batch.pending}</b><em>{statusPercentages.pending}%</em></span>
      <span><i className="is-failed" />失败 <b>{batch.failed}</b><em>{statusPercentages.failed}%</em></span>
      <small>已完成 {completed}/{batch.total} · {SETTLED.has(batch.status) ? "结果已归档，可在下方任务矩阵打开逐条证据" : "可以离开此页，后台仍会继续执行"}</small>
    </div>
    {isRunning ? <section className="sy-batch-live-state is-running" aria-label={`正在检测 ${batch.running} 条任务`}>
      <i aria-hidden="true" />
      <div><b>正在检测</b><small>{batch.running} 条任务正在请求模型并校验回答、来源与搜索证据</small></div>
      <em>{completed}/{batch.total}</em>
    </section> : null}
    {isQueued ? <section className="sy-batch-live-state is-queued" aria-label="任务正在等待采集服务">
      <i aria-hidden="true" />
      <div><b>等待采集服务</b><small>任务已写入队列；启动 worker 后才会开始请求模型</small></div>
      <em>{completed}/{batch.total}</em>
    </section> : null}
    <div className="sy-batch-provider-progress">
      {batch.provider_groups.map((group) => {
        const done = group.succeeded + group.failed;
        const label = conciseProviderLabel(group.label);
        return <article key={group.id}>
          <BrandLogo brand={group.key} label={label} />
          <div><b>{label}</b><span role="progressbar" aria-label={`${label} 完成进度`} aria-valuemin={0} aria-valuemax={group.total} aria-valuenow={done}><i style={{ width: `${group.total ? Math.round(done / group.total * 100) : 0}%` }} /></span></div>
          <small>{done}/{group.total}</small>
        </article>;
      })}
    </div>
    {pollError ? <p className="sy-batch-poll-warning">{pollError}，系统会自动重试，不影响后台任务。</p> : null}
  </section>;
}
