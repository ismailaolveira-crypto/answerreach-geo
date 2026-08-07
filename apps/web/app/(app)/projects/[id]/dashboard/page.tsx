import {
  generateDraftAction,
  generateReportAction,
  runCrawlAction,
  runDueCrawlSchedulesAction,
  runProjectStageGoalActionAction,
  retryCrawlTaskAction
} from "@/app/actions";
import {
  getAlerts,
  getArticleDrafts,
  getCrawlTasks,
  getMaturityReports,
  getPlacements,
  getProject,
  getProjectMvpStatus,
  getProjectOperatingTrends,
  getProjectStageGoals,
  type ProjectMvpStatus
} from "@/lib/api";
import { SubmitButton } from "@/app/(app)/submit-button";
import Link from "next/link";
import type { Route } from "next";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ action_error?: string }>;
};

function asRoute(value: string) {
  return value as Route;
}

function statusLabel(value?: string | null) {
  const labels: Record<string, string> = {
    accepted: "已确认",
    active: "进行中",
    acknowledged: "已确认",
    archived: "已归档",
    completed: "已完成",
    created: "已创建",
    delivered: "已交付",
    failed: "失败",
    missing: "待补齐",
    needs_hourly: "待每小时监测",
    not_delivered: "未交付",
    open: "待处理",
    pending: "排队中",
    planned: "待投放",
    positive: "正向效果",
    ready: "待交付",
    resolved: "已解决",
    running: "执行中",
    success: "成功",
    unavailable: "待复盘",
    unknown: "待确认"
  };
  return labels[value ?? ""] ?? value ?? "待确认";
}

function checkLabel(value: string) {
  const labels: Record<string, string> = {
    "project.detail": "项目配置",
    "crawl.health": "搜索采集",
    "crawl.schedule_ready": "每小时监测",
    "provider.real_collection_ready": "真实渠道",
    maturity_report: "成熟度报告",
    "stage_goal.completed": "阶段目标",
    "stage_goal.timeline": "闭环时间线",
    "placement.impact.positive": "投放复盘",
    public_delivery_package: "客户交付包",
    "content_delivery.loop": "内容交付闭环"
  };
  return labels[value] ?? value;
}

function priorityLabel(priority: number) {
  if (priority >= 90) return "最高";
  if (priority >= 70) return "高";
  if (priority >= 45) return "中";
  return "低";
}

function pct(value?: number | null) {
  const actual = value ?? 0;
  const sign = actual > 0 ? "+" : "";
  return `${sign}${Math.round(actual * 100)}%`;
}

function formatDate(value?: string | null) {
  if (!value) return "暂无";
  return new Date(value).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function providerModeLabel(value?: string) {
  const labels: Record<string, string> = {
    real: "真实渠道",
    mock: "Mock 演示",
    not_ready: "待配置"
  };
  return labels[value ?? ""] ?? "待确认";
}

function actionHref(projectId: string, actionType?: string | null, actionUrl?: string | null) {
  if (actionUrl) return actionUrl;
  if (actionType === "open_provider_config") return "/admin/providers";
  if (actionType === "open_delivery_package") return `/projects/${projectId}/delivery-package`;
  if (actionType === "open_report") return `/projects/${projectId}/reports/compare`;
  if (actionType === "open_crawl_schedules" || actionType === "create_crawl_schedule") {
    return `/projects/${projectId}#crawl-schedules`;
  }
  return `/projects/${projectId}`;
}

function priorityActions(projectId: string, status: ProjectMvpStatus) {
  const actions: Array<{
    key: string;
    title: string;
    detail: string;
    priority: number;
    href?: string;
    form?: "generate_report" | "run_due" | "run_crawl" | "retry_crawl" | "run_full_loop" | "generate_draft";
  }> = [];
  const crawlHealth = status.crawl_health;
  const scheduleStatus = status.schedule_status;
  const contentDelivery = status.content_delivery;
  const stageGoalId = status.stage_goal.goal_id;
  const failedCheck = status.checks.find((check) => !check.ok);

  if ((status.provider_summary.real_collection_ready ?? 0) === 0) {
    actions.push({
      key: "provider",
      title: "先把真实模型渠道测通",
      detail: "没有真实可采集 Provider 时，客户报告只能停留在 Mock 或历史样本演示。",
      priority: 100,
      href: "/admin/providers"
    });
  }
  if (crawlHealth?.status === "failed" && crawlHealth.latest_task_id) {
    actions.push({
      key: "retry_crawl",
      title: "重试最近失败采集",
      detail: crawlHealth.reason ?? "最近一次采集失败，会影响报告样本可信度。",
      priority: 95,
      form: "retry_crawl"
    });
  }
  if ((scheduleStatus?.due_schedule_count ?? 0) > 0) {
    actions.push({
      key: "run_due",
      title: "执行到期监测计划",
      detail: `当前有 ${scheduleStatus?.due_schedule_count ?? 0} 个到期计划，执行后会进入采集任务和队列。`,
      priority: 88,
      form: "run_due"
    });
  }
  if (!crawlHealth?.ok) {
    actions.push({
      key: "run_crawl",
      title: "补齐搜索采集样本",
      detail: crawlHealth?.reason ?? "成熟度报告需要足够的 AI 答案样本支撑。",
      priority: 82,
      form: "run_crawl"
    });
  }
  if (!status.latest_report_url) {
    actions.push({
      key: "report",
      title: "生成成熟度报告",
      detail: "报告是撰稿、审核、行动项和客户交付的共同依据。",
      priority: 78,
      form: "generate_report"
    });
  }
  if (failedCheck?.next_action_type === "run_full_loop" && stageGoalId) {
    actions.push({
      key: "run_full_loop",
      title: "一键跑通阶段目标闭环",
      detail: failedCheck.reason ?? "阶段目标尚未形成采集、稿件、审核、投放、交付的完整证据链。",
      priority: 72,
      form: "run_full_loop"
    });
  }
  if ((contentDelivery?.approved_draft_count ?? 0) === 0 && status.latest_report_url) {
    actions.push({
      key: "draft",
      title: "基于报告建议生成稿件",
      detail: "先形成一篇可审核、可投放的 GEO 友好内容，推动内容生产闭环。",
      priority: 62,
      form: "generate_draft"
    });
  }
  if ((contentDelivery?.published_delivery_count ?? 0) > 0 && (contentDelivery?.active_share_count ?? 0) === 0) {
    actions.push({
      key: "delivery",
      title: "生成客户交付分享",
      detail: "已有客户可见投放，需要进入交付包形成可分享证据。",
      priority: 58,
      href: `/projects/${projectId}/delivery-package`
    });
  }
  for (const check of status.checks.filter((item) => !item.ok && item.next_action_url)) {
    actions.push({
      key: `check-${check.check}`,
      title: check.next_action_label ?? checkLabel(check.check),
      detail: check.reason ?? `${checkLabel(check.check)}仍需补齐。`,
      priority: 50,
      href: actionHref(projectId, check.next_action_type, check.next_action_url)
    });
  }
  return actions
    .filter((action, index, list) => list.findIndex((item) => item.key === action.key) === index)
    .sort((a, b) => b.priority - a.priority)
    .slice(0, 6);
}

export default async function ProjectDashboardPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const queryParams = await searchParams;
  const [
    project,
    mvpStatus,
    trends,
    stageGoals,
    reports,
    crawlTasks,
    drafts,
    placements,
    openAlerts,
    acknowledgedAlerts
  ] = await Promise.all([
    getProject(id),
    getProjectMvpStatus(id),
    getProjectOperatingTrends(id, 14).catch(() => ({ project_id: Number(id), days: 14, points: [] })),
    getProjectStageGoals(id).catch(() => []),
    getMaturityReports(id).catch(() => []),
    getCrawlTasks(id).catch(() => []),
    getArticleDrafts(id).catch(() => []),
    getPlacements(id).catch(() => []),
    getAlerts("open", { projectId: id, limit: 8 }).catch(() => []),
    getAlerts("acknowledged", { projectId: id, limit: 8 }).catch(() => [])
  ]);

  const latestTrend = trends.points.at(-1);
  const firstTrend = trends.points[0];
  const healthDelta = latestTrend && firstTrend ? latestTrend.health_score - firstTrend.health_score : 0;
  const recommendationDelta =
    latestTrend && firstTrend ? latestTrend.recommendation_rate - firstTrend.recommendation_rate : 0;
  const latestReport = reports[0];
  const activeGoals = stageGoals.filter((goal) => goal.status === "active");
  const recentAlerts = [...openAlerts, ...acknowledgedAlerts].slice(0, 6);
  const actions = priorityActions(id, mvpStatus);
  const maxTrendValue = Math.max(
    1,
    ...trends.points.map((point) => Math.max(point.health_score, point.maturity_score, point.answer_count))
  );
  const draftReadyCount = drafts.filter((draft) => draft.status === "approved").length;
  const plannedPlacementCount = placements.filter((placement) => placement.status === "planned").length;
  const publishedPlacementCount = placements.filter((placement) => placement.status === "published").length;
  const projectProviderEvidence = mvpStatus.providers
    .filter(
      (provider) =>
        provider.project_result_count > 0 ||
        provider.project_success_task_count > 0 ||
        provider.project_failed_task_count > 0
    )
    .sort((left, right) => {
      if (right.project_result_count !== left.project_result_count) {
        return right.project_result_count - left.project_result_count;
      }
      return right.project_total_task_count - left.project_total_task_count;
    })
    .slice(0, 4);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">项目交付驾驶舱</div>
          <h1>{project.name}</h1>
          <p className="subtle">把采集、报告、撰稿审核、投放复盘和客户交付聚合到一个运营入口。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          项目详情
        </Link>
        <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
          客户交付包
        </Link>
        <Link className="button secondary" href="/admin/alerts">
          系统告警
        </Link>
      </div>

      {queryParams.action_error ? (
        <div className="notice danger">
          操作没有完成：{queryParams.action_error}
        </div>
      ) : null}

      <section className="panel dashboard-hero">
        <div>
          <div className="eyebrow">GEO 经营健康度</div>
          <strong>{latestTrend?.health_score ?? 0}</strong>
          <small>
            14 日变化 {healthDelta >= 0 ? "+" : ""}
            {Math.round(healthDelta)}｜推荐率 {pct(latestTrend?.recommendation_rate)}
          </small>
        </div>
        <div className="grid cols-4 dashboard-summary">
          <div className="metric">
            <span>闭环状态</span>
            <strong>{mvpStatus.ok ? "已跑通" : "待补齐"}</strong>
            <small>{mvpStatus.checks.filter((check) => check.ok).length}/{mvpStatus.checks.length} 项通过</small>
          </div>
          <div className="metric">
            <span>真实渠道</span>
            <strong>{mvpStatus.provider_summary.real_collection_ready ?? 0}</strong>
            <small>{providerModeLabel(mvpStatus.provider_summary.mode)}</small>
          </div>
          <div className="metric">
            <span>AI 答案样本</span>
            <strong>{mvpStatus.crawl_health?.total_result_count ?? latestTrend?.answer_count ?? 0}</strong>
            <small>{statusLabel(mvpStatus.crawl_health?.status)}</small>
          </div>
          <div className="metric">
            <span>客户确认</span>
            <strong>{mvpStatus.content_delivery?.accepted_delivery_count ?? latestTrend?.accepted_delivery_count ?? 0}</strong>
            <small>发布交付 {mvpStatus.content_delivery?.published_delivery_count ?? publishedPlacementCount}</small>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>下一步优先动作</h2>
            <p className="subtle">按阻塞程度、交付影响和闭环缺口自动排序。</p>
          </div>
          <span className={actions.length === 0 ? "tag active" : "tag"}>{actions.length === 0 ? "暂无阻塞" : `${actions.length} 项`}</span>
        </div>
        <div className="list compact">
          {actions.length === 0 ? (
            <p className="subtle">当前关键闭环均已通过，可继续扩大真实 Provider 样本和网页端观测覆盖。</p>
          ) : (
            actions.map((action) => (
              <div className="row review-row" key={action.key}>
                <div>
                  <div className="meta-line">
                    <span>优先级 {priorityLabel(action.priority)}</span>
                    <span>{action.priority}</span>
                  </div>
                  <h3>{action.title}</h3>
                  <small>{action.detail}</small>
                </div>
                <div className="row-actions">
                  {action.form === "generate_report" ? (
                    <form action={generateReportAction.bind(null, id)}>
                      <SubmitButton pendingText="生成中...">生成报告</SubmitButton>
                    </form>
                  ) : null}
                  {action.form === "run_due" ? (
                    <form action={runDueCrawlSchedulesAction.bind(null, id)}>
                      <SubmitButton pendingText="推进中...">推进监测</SubmitButton>
                    </form>
                  ) : null}
                  {action.form === "run_crawl" ? (
                    <form action={runCrawlAction.bind(null, id)}>
                      <SubmitButton pendingText="采集中...">发起采集</SubmitButton>
                    </form>
                  ) : null}
                  {action.form === "retry_crawl" && mvpStatus.crawl_health?.latest_task_id ? (
                    <form action={retryCrawlTaskAction.bind(null, id, mvpStatus.crawl_health.latest_task_id)}>
                      <SubmitButton pendingText="重试中...">重试采集</SubmitButton>
                    </form>
                  ) : null}
                  {action.form === "run_full_loop" && mvpStatus.stage_goal.goal_id ? (
                    <form
                      action={runProjectStageGoalActionAction.bind(null, id, mvpStatus.stage_goal.goal_id, "run_full_loop")}
                    >
                      <SubmitButton pendingText="执行中...">一键闭环</SubmitButton>
                    </form>
                  ) : null}
                  {action.form === "generate_draft" ? (
                    <form action={generateDraftAction.bind(null, id)}>
                      <SubmitButton pendingText="生成中...">生成稿件</SubmitButton>
                    </form>
                  ) : null}
                  {action.href ? (
                    <Link className="button secondary" href={asRoute(action.href)}>
                      打开
                    </Link>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>14 日趋势</h2>
            <p className="subtle">健康度、成熟度和答案样本量按天汇总，用于观察运营动作是否带来持续变化。</p>
          </div>
          <div className="meta-line">
            <span>健康 {healthDelta >= 0 ? "+" : ""}{Math.round(healthDelta)}</span>
            <span>推荐 {pct(recommendationDelta)}</span>
          </div>
        </div>
        <div className="trend-chart">
          {trends.points.map((point) => (
            <div className="trend-day" key={point.date}>
              <div className="trend-bars">
                <span className="trend-bar health" style={{ height: `${Math.max(8, (point.health_score / maxTrendValue) * 130)}px` }} />
                <span className="trend-bar maturity" style={{ height: `${Math.max(8, (point.maturity_score / maxTrendValue) * 130)}px` }} />
                <span className="trend-bar volume" style={{ height: `${Math.max(8, (point.answer_count / maxTrendValue) * 130)}px` }} />
              </div>
              <small>{formatDate(point.date)}</small>
            </div>
          ))}
        </div>
        <div className="meta-line">
          <span>绿色 健康度</span>
          <span>蓝色 成熟度</span>
          <span>黄色 答案样本</span>
        </div>
      </section>

      <section className="grid cols-3">
        <div className="panel">
          <div className="section-head">
            <div>
              <h2>监测</h2>
              <p className="subtle">定时采集和真实 Provider 状态。</p>
            </div>
            <span className={mvpStatus.crawl_health?.ok ? "tag active" : "tag"}>{statusLabel(mvpStatus.crawl_health?.status)}</span>
          </div>
          <div className="list compact">
            <div className="row">
              <div>
                <h3>每小时监测</h3>
                <small>
                  活跃 {mvpStatus.schedule_status?.active_schedule_count ?? 0}｜到期{" "}
                  {mvpStatus.schedule_status?.due_schedule_count ?? 0}
                </small>
              </div>
              <Link className="button secondary" href={`/projects/${id}#crawl-schedules`}>
                查看
              </Link>
            </div>
            <div className="row">
              <div>
                <h3>最近采集任务</h3>
                <small>
                  {crawlTasks[0] ? `#${crawlTasks[0].id}｜${statusLabel(crawlTasks[0].status)}` : "暂无任务"}
                </small>
              </div>
              {crawlTasks[0] ? (
                <Link className="button secondary" href={`/projects/${id}/tasks/${crawlTasks[0].id}`}>
                  打开
                </Link>
              ) : null}
            </div>
            <div className="row">
              <div>
                <h3>模型渠道</h3>
                <small>
                  可采集 {mvpStatus.provider_summary.ready ?? 0}/{mvpStatus.provider_summary.total ?? 0}｜真实{" "}
                  {mvpStatus.provider_summary.real_collection_ready ?? 0}
                </small>
              </div>
              <Link className="button secondary" href="/admin/providers">
                配置
              </Link>
            </div>
            {projectProviderEvidence.map((provider) => (
              <div className="row" key={provider.provider_id}>
                <div>
                  <h3>{provider.name}</h3>
                  <small>
                    结果 {provider.project_result_count}｜成功 {provider.project_success_task_count}｜失败{" "}
                    {provider.project_failed_task_count}｜tokens {provider.project_total_tokens}
                  </small>
                  {provider.project_latest_task_error_message ? (
                    <small className="danger-text">{provider.project_latest_task_error_message}</small>
                  ) : null}
                </div>
                {provider.project_latest_task_id ? (
                  <Link className="button secondary" href={`/projects/${id}/tasks/${provider.project_latest_task_id}`}>
                    {statusLabel(provider.project_latest_task_status)}
                  </Link>
                ) : (
                  <span className={provider.collection_ready ? "tag active" : "tag"}>
                    {provider.collection_ready ? "已测通" : "待测试"}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="section-head">
            <div>
              <h2>报告与内容</h2>
              <p className="subtle">成熟度研判到稿件审核。</p>
            </div>
            <span className={latestReport ? "tag active" : "tag"}>{latestReport ? `${latestReport.total_score} 分` : "待报告"}</span>
          </div>
          <div className="list compact">
            <div className="row">
              <div>
                <h3>最新成熟度报告</h3>
                <small>{latestReport ? `${latestReport.maturity_level}｜${latestReport.title}` : "尚未生成"}</small>
              </div>
              {latestReport ? (
                <Link className="button secondary" href={`/projects/${id}/reports/${latestReport.id}`}>
                  打开
                </Link>
              ) : null}
            </div>
            <div className="row">
              <div>
                <h3>稿件状态</h3>
                <small>
                  总稿件 {drafts.length}｜已通过 {draftReadyCount}
                </small>
              </div>
              <Link className="button secondary" href="/reviews">
                审核台
              </Link>
            </div>
            <div className="row">
              <div>
                <h3>阶段目标</h3>
                <small>
                  进行中 {activeGoals.length}｜全部 {stageGoals.length}
                </small>
              </div>
              <Link className="button secondary" href={`/projects/${id}#stage-goals`}>
                查看
              </Link>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="section-head">
            <div>
              <h2>投放交付</h2>
              <p className="subtle">从 planned 投放到客户确认。</p>
            </div>
            <span className={mvpStatus.content_delivery?.ok ? "tag active" : "tag"}>
              {mvpStatus.content_delivery?.ok ? "已验证" : "待推进"}
            </span>
          </div>
          <div className="list compact">
            <div className="row">
              <div>
                <h3>投放记录</h3>
                <small>
                  待投放 {plannedPlacementCount}｜已发布 {publishedPlacementCount}
                </small>
              </div>
              <Link className="button secondary" href={`/projects/${id}/sources`}>
                投放
              </Link>
            </div>
            <div className="row">
              <div>
                <h3>客户交付包</h3>
                <small>
                  分享 {mvpStatus.content_delivery?.active_share_count ?? 0}｜确认{" "}
                  {mvpStatus.content_delivery?.accepted_delivery_count ?? 0}
                </small>
              </div>
              <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
                打开
              </Link>
            </div>
            <div className="row">
              <div>
                <h3>最近告警</h3>
                <small>{recentAlerts.length > 0 ? `${recentAlerts.length} 条待跟进` : "暂无待跟进"}</small>
              </div>
              <Link className="button secondary" href="/admin/alerts">
                查看
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>闭环检查</h2>
            <p className="subtle">这些检查项决定项目是否能作为客户交付样板。</p>
          </div>
          <span className={mvpStatus.ok ? "tag active" : "tag"}>{mvpStatus.ok ? "全部通过" : "存在缺口"}</span>
        </div>
        <div className="grid cols-3">
          {mvpStatus.checks.map((check) => (
            <div className="row review-row" key={check.check}>
              <div>
                <div className="meta-line">
                  <span>{check.ok ? "通过" : "待补齐"}</span>
                  {check.status ? <span>{statusLabel(check.status)}</span> : null}
                </div>
                <h3>{checkLabel(check.check)}</h3>
                <small>{check.reason ?? check.next_action_label ?? "已满足当前交付要求"}</small>
              </div>
              <span className={check.ok ? "tag active" : "tag"}>{check.ok ? "OK" : "TODO"}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>最近待跟进</h2>
            <p className="subtle">客户确认、阶段目标风险、Provider 失败和监测异常会聚合到这里。</p>
          </div>
          <Link className="button secondary" href="/admin/alerts">
            告警中心
          </Link>
        </div>
        <div className="list compact">
          {recentAlerts.length === 0 ? (
            <p className="subtle">暂无待处理告警。</p>
          ) : (
            recentAlerts.map((alert) => (
              <Link className="row" href="/admin/alerts" key={alert.id}>
                <div>
                  <div className="meta-line">
                    <span>{alert.alert_type}</span>
                    <span>{statusLabel(alert.status)}</span>
                    <span>{alert.severity}</span>
                  </div>
                  <h3>{alert.title}</h3>
                  <small>{alert.message}</small>
                </div>
                <span className="tag">{formatDate(alert.created_at)}</span>
              </Link>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
