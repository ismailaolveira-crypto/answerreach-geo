import Link from "next/link";
import { notFound } from "next/navigation";
import { BrandLogo } from "@/components/brand-logo";
import { getOfficialProviderObservationBatch, type OfficialApiObservationTask } from "@/lib/cleanroom-v1-api";
import ObservationBatchProgress from "../../observation-batch-progress";

type Props = { params: Promise<{ workspaceId: string; batchId: string }> };

const TASK_LABELS = { pending: "等待", running: "运行中", success: "成功", failed: "失败" };

function TaskCell({ task, workspaceId }: { task?: OfficialApiObservationTask; workspaceId: string }) {
  if (!task) return <span className="sy-task-cell is-missing"><b>未创建</b><small>后台无对应任务</small></span>;
  const content = <><b>{TASK_LABELS[task.status]}</b><small>{task.duration_seconds == null ? `任务 #${task.job_id}` : `${task.duration_seconds}s · #${task.job_id}`}</small>{task.error_message ? <em title={task.error_message}>{task.error_message}</em> : null}</>;
  return task.evidence_id
    ? <Link className={`sy-task-cell is-${task.status}`} href={`/geo/${workspaceId}/evidence/${task.evidence_id}`}>{content}<i>查看证据 →</i></Link>
    : <span className={`sy-task-cell is-${task.status}`}>{content}</span>;
}

export default async function ObservationBatchDetailPage({ params }: Props) {
  const { workspaceId, batchId } = await params;
  const parsedBatchId = Number(batchId);
  if (!Number.isInteger(parsedBatchId) || parsedBatchId < 1) notFound();
  const batch = await getOfficialProviderObservationBatch(workspaceId, parsedBatchId, { taskPageSize: 125 }).catch(() => null);
  if (!batch) notFound();
  const taskByCell = new Map(batch.tasks.map((task) => [`${task.question_plan_id}:${task.provider_id}:${task.repeat_index}`, task]));
  const repeats = Array.from({ length: batch.repeat_count }, (_, index) => index + 1);
  const failedTasks = batch.tasks.filter((task) => task.status === "failed");

  return <div className="sy-page">
    <header className="sy-topbar">
      <Link className="sy-brand" href={`/geo/${workspaceId}`}><span>◈</span><b>春秋元泉 GEO</b></Link>
      <div className="sy-toplinks"><Link href={`/geo/${workspaceId}/batches`}>全部批次</Link><Link href={`/geo/${workspaceId}`}>返回决策地图</Link></div>
    </header>
    <main className="sy-main sy-batch-detail-main">
      <section className="sy-heading"><div><h1>批次 #{batch.batch_id}</h1><p>完整任务矩阵 · 模型 × 问题 × 第几次</p></div></section>
      <ObservationBatchProgress workspaceId={workspaceId} initialBatch={batch} />
      <section className="sy-batch-matrix-card">
        <header><div><h2>任务矩阵</h2><p>每格对应一条持久化后台任务；成功任务可直接打开归档证据。</p></div><small>{batch.task_pagination.total} 条真实任务</small></header>
        {batch.tasks.length ? <div className="sy-table-wrap"><table className="sy-batch-matrix"><thead><tr><th>问题 / 次数</th>{batch.provider_groups.map((provider) => <th key={provider.id}><BrandLogo brand={provider.key} label={provider.label} /><span>{provider.label}</span></th>)}</tr></thead><tbody>{batch.question_groups.flatMap((question) => repeats.map((repeat) => <tr key={`${question.id}:${repeat}`}><th><b>{question.label}</b><small>第 {repeat} 次</small></th>{batch.provider_groups.map((provider) => <td key={provider.id}><TaskCell workspaceId={workspaceId} task={taskByCell.get(`${question.id}:${provider.id}:${repeat}`)} /></td>)}</tr>))}</tbody></table></div> : <div className="sy-batch-empty is-compact"><h2>这个批次没有任务</h2><p>批次父记录存在，但后台没有找到对应子任务。</p></div>}
      </section>
      {failedTasks.length ? <section className="sy-batch-failure-list"><h2>失败任务</h2>{failedTasks.map((task) => <article key={task.job_id}><div><b>{task.provider_label} · 第 {task.repeat_index} 次</b><span>{task.question_label}</span></div><p>{task.error_message || "后台未记录错误详情"}</p></article>)}</section> : null}
    </main>
  </div>;
}
