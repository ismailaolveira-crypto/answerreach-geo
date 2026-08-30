import Link from "next/link";
import type { Route } from "next";
import { notFound } from "next/navigation";
import { BrandLogo } from "@/components/brand-logo";
import { getOfficialProviderObservationBatch, type OfficialApiObservationTask } from "@/lib/cleanroom-v1-api";
import ObservationBatchProgress from "../../observation-batch-progress";

type Props = {
  params: Promise<{ workspaceId: string; batchId: string }>;
  searchParams: Promise<{ taskPage?: string }>;
};

const TASK_LABELS = { pending: "等待", running: "运行中", success: "成功", failed: "失败" };

function batchSourceLabel(sourceType: string) {
  if (sourceType === "official_api") return "官方 API 联网观测";
  if (sourceType === "official_api_single") return "单次官方 API 观测";
  if (sourceType === "browser_profile") return "网页端真实采样";
  if (sourceType === "legacy_import") return "历史真实观测迁移";
  if (sourceType.startsWith("yao_")) return "授权观测导入";
  return "统一观测台账";
}

function TaskCell({ task, workspaceId }: { task?: OfficialApiObservationTask; workspaceId: string }) {
  if (!task) return <span className="sy-task-cell is-missing"><b>未创建</b><small>后台无对应任务</small></span>;
  const content = <><b>{TASK_LABELS[task.status]}</b><small>{task.duration_seconds == null ? `任务 #${task.job_id}` : `${task.duration_seconds}s · 任务 #${task.job_id}`}</small>{task.error_message ? <em title={task.error_message}>{task.error_message}</em> : null}</>;
  return task.evidence_id
    ? <Link className={`sy-task-cell is-${task.status}`} href={`/geo/${workspaceId}/evidence/${task.evidence_id}`}>{content}<i>查看证据 #{task.evidence_id} →</i></Link>
    : <span className={`sy-task-cell is-${task.status}`}>{content}</span>;
}

export default async function ObservationBatchDetailPage({ params, searchParams }: Props) {
  const { workspaceId, batchId } = await params;
  const query = await searchParams;
  const parsedBatchId = Number(batchId);
  if (!Number.isInteger(parsedBatchId) || parsedBatchId < 1) notFound();
  const requestedTaskPage = Math.max(1, Number(query.taskPage) || 1);
  const batch = await getOfficialProviderObservationBatch(workspaceId, parsedBatchId, { taskPage: requestedTaskPage, taskPageSize: 125 }).catch(() => null);
  if (!batch) notFound();
  const taskByCell = new Map(batch.tasks.map((task) => [`${task.question_plan_id}:${task.provider_id}:${task.repeat_index}`, task]));
  const repeats = Array.from({ length: batch.repeat_count }, (_, index) => index + 1);
  const failedTasks = batch.tasks.filter((task) => task.status === "failed");
  const usesTaskPages = batch.task_pagination.total > batch.task_pagination.page_size;
  const previousPage = Math.max(1, batch.task_pagination.page - 1);
  const nextPage = Math.min(batch.task_pagination.total_pages, batch.task_pagination.page + 1);

  return <div className="sy-page">
    <header className="sy-topbar">
      <Link className="sy-brand" href={`/geo/${workspaceId}`}><img alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" /><b>入答 AnswerReach</b></Link>
      <div className="sy-toplinks"><Link href={`/geo/${workspaceId}/batches`}>全部批次</Link><Link href={`/geo/${workspaceId}`}>返回决策地图</Link></div>
    </header>
    <main className="sy-main sy-batch-detail-main">
      <section className="sy-heading"><div><h1>批次 #{batch.batch_id}</h1><p>{batchSourceLabel(batch.source_type)} · 完整任务矩阵 · 模型 × 问题 × 第几次</p></div></section>
      <ObservationBatchProgress workspaceId={workspaceId} initialBatch={batch} />
      <section className="sy-batch-matrix-card">
        <header><div><h2>{usesTaskPages ? "任务清单" : "任务矩阵"}</h2><p>{usesTaskPages ? "大批次按页展示已持久化任务；每条成功任务都可直接打开归档证据。" : "每格对应统一台账中的一条持久化观测任务；成功任务可直接打开归档证据。"}</p></div><small>{usesTaskPages ? `第 ${batch.task_pagination.page} / ${batch.task_pagination.total_pages} 页 · ` : ""}{batch.task_pagination.total} 条真实任务</small></header>
        {batch.tasks.length ? <div className="sy-table-wrap"><table className="sy-batch-matrix">{usesTaskPages ? <><thead><tr><th>问题</th><th>模型</th><th>次数</th><th>状态与证据</th></tr></thead><tbody>{batch.tasks.map((task) => <tr key={task.job_id}><th><b>{task.question_label}</b><small>问题 #{task.question_plan_id}</small></th><td><BrandLogo brand={task.provider_key} label={task.provider_label} /><span>{task.provider_label}</span></td><td>第 {task.repeat_index} 次</td><td><TaskCell workspaceId={workspaceId} task={task} /></td></tr>)}</tbody></> : <><thead><tr><th>问题 / 次数</th>{batch.provider_groups.map((provider) => <th key={provider.id}><BrandLogo brand={provider.key} label={provider.label} /><span>{provider.label}</span></th>)}</tr></thead><tbody>{batch.question_groups.flatMap((question) => repeats.map((repeat) => <tr key={`${question.id}:${repeat}`}><th><b>{question.label}</b><small>第 {repeat} 次</small></th>{batch.provider_groups.map((provider) => <td key={provider.id}><TaskCell workspaceId={workspaceId} task={taskByCell.get(`${question.id}:${provider.id}:${repeat}`)} /></td>)}</tr>))}</tbody></>}</table></div> : <div className="sy-batch-empty is-compact"><h2>{usesTaskPages ? "当前页没有任务" : "这个批次没有任务"}</h2><p>{usesTaskPages ? "请返回有效页码继续查看。" : "批次父记录存在，但后台没有找到对应子任务。"}</p></div>}
        {usesTaskPages ? <nav className="sy-toplinks" aria-label="任务分页"><Link aria-disabled={batch.task_pagination.page <= 1} href={`/geo/${workspaceId}/batches/${batch.batch_id}?taskPage=${previousPage}` as Route}>上一页</Link><span>第 {batch.task_pagination.page} / {batch.task_pagination.total_pages} 页</span><Link aria-disabled={batch.task_pagination.page >= batch.task_pagination.total_pages} href={`/geo/${workspaceId}/batches/${batch.batch_id}?taskPage=${nextPage}` as Route}>下一页</Link></nav> : null}
      </section>
      {failedTasks.length ? <section className="sy-batch-failure-list"><h2>失败任务</h2>{failedTasks.map((task) => <article key={task.job_id}><div><b>{task.provider_label} · 第 {task.repeat_index} 次</b><span>{task.question_label}</span></div><p>{task.error_message || "后台未记录错误详情"}</p></article>)}</section> : null}
    </main>
  </div>;
}
