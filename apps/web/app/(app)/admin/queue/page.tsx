import Link from "next/link";
import type { Route } from "next";
import { redirect } from "next/navigation";
import { retryCrawlTaskAction, runNextQueueJobAction, runReadyQueueJobsAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getQueueJobs } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "等待中",
    running: "执行中",
    success: "成功",
    failed: "失败"
  };
  return labels[status] ?? status;
}

function payloadNumber(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asRoute(value: string) {
  return value as Route;
}

export default async function QueuePage({
  searchParams
}: Readonly<{
  searchParams: Promise<{
    status?: string;
    job_ran?: string;
    job_status?: string;
    ready_created?: string;
    ready_ran?: string;
    ready_success?: string;
    ready_failed?: string;
    ready_pending?: string;
  }>;
}>) {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin" && user?.role !== "company_admin") {
    redirect("/");
  }
  const params = await searchParams;
  const status = params.status || undefined;
  const data = await getQueueJobs(status).catch(() => ({
    summary: { total: 0, pending: 0, running: 0, success: 0, failed: 0 },
    jobs: []
  }));
  const readyRan = params.ready_ran ? Number(params.ready_ran) : null;
  const readyFailed = params.ready_failed ? Number(params.ready_failed) : 0;
  const readyPending = params.ready_pending ? Number(params.ready_pending) : 0;
  const jobRan = params.job_ran === "1";

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">管理员后台</div>
          <h1>队列运维</h1>
          <p className="subtle">查看定时采集、手动入队任务和 worker 执行结果，必要时手动执行下一条到期任务。</p>
        </div>
        <div className="row-actions">
          <form action={runReadyQueueJobsAction}>
            <SubmitButton pendingText="推进中...">推进到期任务</SubmitButton>
          </form>
          <form action={runNextQueueJobAction}>
            <SubmitButton pendingText="执行中...">执行下一条</SubmitButton>
          </form>
          <Link className="button secondary" href={asRoute("/admin/queue")}>
            全部
          </Link>
          <Link className="button secondary" href={asRoute("/admin/queue?status=pending")}>
            等待中
          </Link>
          <Link className="button secondary" href={asRoute("/admin/queue?status=failed")}>
            失败
          </Link>
        </div>
      </div>

      {readyRan !== null ? (
        <div className={readyFailed > 0 ? "notice danger" : readyPending > 0 ? "notice warning" : "notice success"}>
          已创建 {params.ready_created ?? 0} 个到期采集任务，执行 {params.ready_ran ?? 0} 个队列任务，成功{" "}
          {params.ready_success ?? 0} 个，失败 {params.ready_failed ?? 0} 个
          {readyPending > 0 ? `，仍有 ${readyPending} 个到期任务待执行` : "。"}
        </div>
      ) : null}

      {params.job_ran ? (
        <div className={jobRan && params.job_status !== "failed" ? "notice success" : "notice warning"}>
          {jobRan ? `已执行下一条队列任务，状态：${statusLabel(params.job_status ?? "unknown")}。` : "当前没有可执行的队列任务。"}
        </div>
      ) : null}

      <section className="grid cols-4">
        <div className="panel metric">
          <span>总任务</span>
          <strong>{data.summary.total}</strong>
        </div>
        <div className="panel metric">
          <span>等待中</span>
          <strong>{data.summary.pending}</strong>
        </div>
        <div className="panel metric">
          <span>执行中</span>
          <strong>{data.summary.running}</strong>
        </div>
        <div className="panel metric">
          <span>失败</span>
          <strong>{data.summary.failed}</strong>
        </div>
      </section>

      <section className="panel">
        <h2>{status ? statusLabel(status) : "全部"}队列任务</h2>
        <div className="list">
          {data.jobs.length === 0 ? (
            <p className="subtle">暂无队列任务。</p>
          ) : (
            data.jobs.map((job) => {
              const projectId = payloadNumber(job.payload_json, "project_id");
              const taskId = payloadNumber(job.payload_json, "task_id");
              return (
                <div className="row" key={job.id}>
                  <div>
                    <h3>
                      #{job.id} {job.job_type}
                    </h3>
                    <small>
                      {statusLabel(job.status)}｜尝试 {job.attempts}/{job.max_attempts}｜计划 {job.scheduled_at ?? "-"}｜
                      创建 {job.created_at}
                    </small>
                    {job.error_message ? <p className="subtle">{job.error_message}</p> : null}
                    {projectId && taskId ? (
                      <p className="subtle">
                        <Link href={asRoute(`/projects/${projectId}/tasks/${taskId}`)}>查看采集任务 #{taskId}</Link>
                      </p>
                    ) : null}
                  </div>
                  <div className="row-actions">
                    <span className={job.status === "success" ? "tag active" : "tag"}>{statusLabel(job.status)}</span>
                    {projectId ? (
                      <Link className="button secondary" href={asRoute(`/projects/${projectId}`)}>
                        项目
                      </Link>
                    ) : null}
                    {job.status === "failed" && projectId && taskId ? (
                      <form action={retryCrawlTaskAction.bind(null, String(projectId), taskId)}>
                        <SubmitButton pendingText="重试中...">重试采集任务</SubmitButton>
                      </form>
                    ) : null}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
