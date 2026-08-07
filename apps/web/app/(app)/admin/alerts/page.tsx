import Link from "next/link";
import {
  createAlertReportActionGoalsAction,
  retryCrawlTaskAction,
  runMonitoringAlertsAction,
  runPlacementRemindersAction,
  updateAlertAction
} from "@/app/actions";
import { getAlerts } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import { redirect } from "next/navigation";

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    open: "未处理",
    acknowledged: "已确认",
    resolved: "已解决"
  };
  return labels[status] ?? status;
}

function severityLabel(severity: string) {
  const labels: Record<string, string> = {
    critical: "严重",
    warning: "警告",
    info: "提示"
  };
  return labels[severity] ?? severity;
}

export default async function AlertsPage({
  searchParams
}: Readonly<{ searchParams: Promise<{ status?: string }> }>) {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin" && user?.role !== "company_admin") {
    redirect("/");
  }
  const params = await searchParams;
  const status = params.status ?? "open";
  const alerts = await getAlerts(status).catch(() => []);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">管理员后台</div>
          <h1>系统告警</h1>
          <p className="subtle">集中处理模型渠道测试失败、采集异常和后续任务运行风险。</p>
        </div>
        <div className="row-actions">
          <form action={runPlacementRemindersAction}>
            <button className="button" type="submit">
              扫描投放提醒
            </button>
          </form>
          <form action={runMonitoringAlertsAction}>
            <button className="button secondary" type="submit">
              扫描监测异常
            </button>
          </form>
          <Link className="button secondary" href="/admin/alerts?status=open">
            未处理
          </Link>
          <Link className="button secondary" href="/admin/alerts?status=acknowledged">
            已确认
          </Link>
          <Link className="button secondary" href="/admin/alerts?status=resolved">
            已解决
          </Link>
        </div>
      </div>

      <section className="panel">
        <h2>{statusLabel(status)}告警</h2>
        <div className="list">
          {alerts.length === 0 ? (
            <p className="subtle">暂无{statusLabel(status)}告警。</p>
          ) : (
            alerts.map((alert) => (
              <div className="row" key={alert.id}>
                <div>
                  <h3>{alert.title}</h3>
                  <small>
                    {alert.created_at}｜{alert.alert_type}｜{severityLabel(alert.severity)}
                    {alert.provider_id ? `｜Provider #${alert.provider_id}` : ""}
                    {alert.provider_test_run_id ? `｜测试 #${alert.provider_test_run_id}` : ""}
                  </small>
                <p className="subtle">{alert.message}</p>
                  {alert.project_id && typeof alert.detail_json.review_crawl_task_id === "number" ? (
                    <p className="subtle">
                      <Link href={`/projects/${alert.project_id}/tasks/${alert.detail_json.review_crawl_task_id}`}>
                        查看复盘采集任务 #{alert.detail_json.review_crawl_task_id}
                      </Link>
                    </p>
                  ) : null}
                  {alert.project_id && alert.alert_type === "delivery.confirmed" ? (
                    <p className="subtle">
                      <Link href={`/projects/${alert.project_id}/delivery-package`}>查看客户交付包</Link>
                      {typeof alert.detail_json.placement_id === "number" ? (
                        <>
                          {" ｜ "}
                          <Link href={`/projects/${alert.project_id}/placements/${alert.detail_json.placement_id}/impact`}>
                            查看复盘报告 #{alert.detail_json.placement_id}
                          </Link>
                        </>
                      ) : null}
                    </p>
                  ) : null}
                  {alert.project_id && typeof alert.detail_json.target_report_id === "number" ? (
                    <p className="subtle">
                      <Link href={`/projects/${alert.project_id}/reports/${alert.detail_json.target_report_id}`}>
                        查看触发报告 #{alert.detail_json.target_report_id}
                      </Link>
                      {Array.isArray(alert.detail_json.action_goal_ids) && alert.detail_json.action_goal_ids.length > 0 ? (
                        <>
                          {" ｜ "}
                          <Link href={`/projects/${alert.project_id}#stage-goals`}>
                            查看整改目标 {alert.detail_json.action_goal_ids.length} 个
                          </Link>
                        </>
                      ) : null}
                    </p>
                  ) : null}
                </div>
                <div className="row-actions">
                  <span className="tag">{statusLabel(alert.status)}</span>
                  {alert.status === "open" ? (
                    <form action={updateAlertAction.bind(null, alert.id, "acknowledged")}>
                      <button className="button secondary" type="submit">
                        确认
                      </button>
                    </form>
                  ) : null}
                  {alert.status !== "resolved" ? (
                    <form action={updateAlertAction.bind(null, alert.id, "resolved")}>
                      <button className="button" type="submit">
                        解决
                      </button>
                    </form>
                  ) : null}
                  {alert.project_id && typeof alert.detail_json.review_crawl_task_id === "number" ? (
                    <form action={retryCrawlTaskAction.bind(null, String(alert.project_id), alert.detail_json.review_crawl_task_id)}>
                      <button className="button secondary" type="submit">
                        重试采集
                      </button>
                    </form>
                  ) : null}
                  {alert.project_id &&
                  alert.alert_type.startsWith("monitoring.") &&
                  typeof alert.detail_json.target_report_id === "number" ? (
                    <form action={createAlertReportActionGoalsAction.bind(null, alert.id)}>
                      <button className="button secondary" type="submit">
                        生成整改目标
                      </button>
                    </form>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
