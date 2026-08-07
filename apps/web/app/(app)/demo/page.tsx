import fs from "node:fs/promises";
import path from "node:path";
import type { Route } from "next";
import Link from "next/link";

import { getLatestProjectMvpStatus, type ProjectMvpStatus } from "@/lib/api";

type DemoAction = {
  action_type: string;
  status: string;
  message: string;
  resource_type?: string | null;
  resource_id?: number | null;
  resource_url?: string | null;
  detail: Record<string, unknown>;
};

type DemoSummary = {
  run_label: string;
  generated_at: string;
  login: {
    email: string;
    password?: string | null;
  };
  company_id: number;
  project_id: number;
  project_url: string;
  crawl_task_id: number;
  report_ids: number[];
  latest_report_url: string;
  compare_url: string;
  delivery_package_url: string;
  public_share_url: string;
  provider_summary?: ProjectMvpStatus["provider_summary"];
  providers?: ProjectMvpStatus["providers"];
  stage_goal: {
    goal_id: number;
    goal_status: string;
    action_results: DemoAction[];
    placement_id: number;
    share_id: number;
    share_token: string;
    access_log_id: number;
    processed_jobs: Array<{
      job_id: number;
      job_type: string;
      status: string;
      error_message?: string | null;
    }>;
    weakened_baseline_count: number;
    review_status: string;
    metric_deltas: {
      sample_size_delta: number;
      company_mention_rate_delta: number;
      company_recommendation_rate_delta: number;
      source_after_appearances: number;
    };
    delivery_status: string;
  };
  output_path: string;
};

type VerificationSummary = {
  ok: boolean;
  project_id: number;
  report_id: number;
  placement_id: number;
  goal_id: number;
  public_share_url: string;
  checks: Array<{
    check: string;
    ok: boolean;
    total_score?: number;
    maturity_level?: string;
    status?: string;
    event_count?: number;
    deliverable_count?: number;
    marker_count?: number;
    metric_deltas?: {
      sample_size_delta: number;
      company_mention_rate_delta: number;
      company_recommendation_rate_delta: number;
      source_after_appearances: number;
    };
  }>;
};

type ContentDeliveryLoopSummary = {
  ok: boolean;
  verification_method: string;
  project_id: number;
  topic: string;
  draft: {
    id: number;
    status: string;
    title: string;
  };
  ai_review: {
    id: number;
    score: number;
    grade: string;
  };
  human_review: {
    id: number;
    status: string;
  };
  placement: {
    id: number;
    status: string;
    visibility: string;
    delivery_status: string;
    published_at_set: boolean;
  };
  share: {
    id: number;
    status: string;
    token_length: number;
    public_path: string;
  };
  public_package: {
    deliverable_count: number;
    temporary_placement_visible: boolean;
  };
};

const summaryPath = path.resolve(process.cwd(), "..", "..", "outputs", "latest_e2e_demo.json");
const verificationPath = path.resolve(
  process.cwd(),
  "..",
  "..",
  "outputs",
  "latest_mvp_verification.json"
);
const contentDeliveryLoopPath = path.resolve(
  process.cwd(),
  "..",
  "..",
  "outputs",
  "latest_content_delivery_loop_testclient.json"
);

async function readDemoSummary(): Promise<DemoSummary | null> {
  try {
    const raw = await fs.readFile(summaryPath, "utf-8");
    return JSON.parse(raw) as DemoSummary;
  } catch {
    return null;
  }
}

async function readVerificationSummary(): Promise<VerificationSummary | null> {
  try {
    const raw = await fs.readFile(verificationPath, "utf-8");
    return JSON.parse(raw) as VerificationSummary;
  } catch {
    return null;
  }
}

async function readContentDeliveryLoopSummary(): Promise<ContentDeliveryLoopSummary | null> {
  try {
    const raw = await fs.readFile(contentDeliveryLoopPath, "utf-8");
    return JSON.parse(raw) as ContentDeliveryLoopSummary;
  } catch {
    return null;
  }
}

function numericMetric(value: unknown) {
  return typeof value === "number" ? value : 0;
}

function apiStatusToDemoSummary(status: ProjectMvpStatus): DemoSummary {
  const metricDeltas = status.stage_goal.metric_deltas ?? {};
  return {
    run_label: "api-live",
    generated_at: status.generated_at,
    login: {
      email: status.user_email,
      password: null
    },
    company_id: status.company_id,
    project_id: status.project_id,
    project_url: status.project_url,
    crawl_task_id: status.crawl_task_id ?? 0,
    report_ids: status.report_ids,
    latest_report_url: status.latest_report_url ?? status.project_url,
    compare_url: status.compare_url ?? status.project_url,
    delivery_package_url: status.delivery_package_url,
    public_share_url: status.public_share_url ?? status.delivery_package_url,
    provider_summary: status.provider_summary,
    providers: status.providers,
    stage_goal: {
      goal_id: status.stage_goal.goal_id ?? 0,
      goal_status: status.stage_goal.goal_status,
      action_results: status.stage_goal.action_results,
      placement_id: status.stage_goal.placement_id ?? 0,
      share_id: status.stage_goal.share_id ?? 0,
      share_token: status.stage_goal.share_token ?? "",
      access_log_id: status.stage_goal.access_log_id ?? 0,
      processed_jobs: [],
      weakened_baseline_count: 0,
      review_status: status.stage_goal.review_status,
      metric_deltas: {
        sample_size_delta: numericMetric(metricDeltas.sample_size_delta),
        company_mention_rate_delta: numericMetric(metricDeltas.company_mention_rate_delta),
        company_recommendation_rate_delta: numericMetric(metricDeltas.company_recommendation_rate_delta),
        source_after_appearances: numericMetric(metricDeltas.source_after_appearances)
      },
      delivery_status: status.stage_goal.delivery_status
    },
    output_path: "api:/api/projects/mvp-status/latest"
  };
}

function apiStatusToVerificationSummary(status: ProjectMvpStatus): VerificationSummary {
  return {
    ok: status.ok,
    project_id: status.project_id,
    report_id: status.report_ids.at(-1) ?? 0,
    placement_id: status.stage_goal.placement_id ?? 0,
    goal_id: status.stage_goal.goal_id ?? 0,
    public_share_url: status.public_share_url ?? "",
    checks: status.checks.map((check) => ({
      check: check.check,
      ok: check.ok,
      total_score: check.total_score ?? undefined,
      maturity_level: check.maturity_level ?? undefined,
      status: check.status ?? undefined,
      event_count: check.event_count ?? undefined,
      deliverable_count: check.deliverable_count ?? undefined,
      metric_deltas: check.metric_deltas
        ? {
            sample_size_delta: numericMetric(check.metric_deltas.sample_size_delta),
            company_mention_rate_delta: numericMetric(check.metric_deltas.company_mention_rate_delta),
            company_recommendation_rate_delta: numericMetric(
              check.metric_deltas.company_recommendation_rate_delta
            ),
            source_after_appearances: numericMetric(check.metric_deltas.source_after_appearances)
          }
        : undefined
    }))
  };
}

function apiStatusToContentDeliveryLoopSummary(status: ProjectMvpStatus): ContentDeliveryLoopSummary | null {
  const contentDelivery = status.content_delivery;
  if (!contentDelivery) {
    return null;
  }
  return {
    ok: contentDelivery.ok,
    verification_method: "api:/api/projects/{id}/mvp-status content_delivery",
    project_id: status.project_id,
    topic: "项目最新内容交付状态",
    draft: {
      id: contentDelivery.latest_draft_id ?? 0,
      status: contentDelivery.approved_draft_count > 0 ? "approved" : "pending",
      title: "最新稿件"
    },
    ai_review: {
      id: contentDelivery.latest_review_id ?? 0,
      score: contentDelivery.latest_review_score ?? 0,
      grade: contentDelivery.latest_review_grade ?? "-"
    },
    human_review: {
      id: 0,
      status: contentDelivery.approved_draft_count > 0 ? "approved" : "pending"
    },
    placement: {
      id: contentDelivery.latest_placement_id ?? 0,
      status: contentDelivery.published_delivery_count > 0 ? "published" : "pending",
      visibility: contentDelivery.published_delivery_count > 0 ? "customer_visible" : "internal",
      delivery_status: contentDelivery.accepted_delivery_count > 0 ? "accepted" : "pending",
      published_at_set: contentDelivery.published_delivery_count > 0
    },
    share: {
      id: contentDelivery.latest_share_id ?? 0,
      status: contentDelivery.active_share_count > 0 ? "active" : "pending",
      token_length: contentDelivery.latest_share_token?.length ?? 0,
      public_path: contentDelivery.latest_share_token ? `/share/delivery/${contentDelivery.latest_share_token}` : ""
    },
    public_package: {
      deliverable_count: contentDelivery.published_delivery_count,
      temporary_placement_visible: contentDelivery.published_delivery_count > 0
    }
  };
}

async function readApiDemoStatus() {
  try {
    const status = await getLatestProjectMvpStatus();
    return {
      summary: apiStatusToDemoSummary(status),
      verification: apiStatusToVerificationSummary(status),
      contentDeliveryLoop: apiStatusToContentDeliveryLoopSummary(status)
    };
  } catch {
    return null;
  }
}

function pct(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${Math.round(value * 100)}%`;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    accepted: "已确认",
    completed: "已完成",
    created: "已创建",
    positive: "正向效果",
    success: "成功"
  };
  return labels[value] ?? value;
}

function actionLabel(value: string) {
  const labels: Record<string, string> = {
    run_crawl: "搜索采集",
    generate_draft: "撰稿评分",
    approve_and_create_placement: "人工审核投放",
    publish_prepare_delivery: "发布交付",
    create_delivery_followup: "交付跟进"
  };
  return labels[value] ?? value;
}

function checkLabel(value: string) {
  const labels: Record<string, string> = {
    "auth.me": "登录态",
    "project.detail": "项目详情",
    "provider.real_collection_ready": "真实渠道",
    "crawl.health": "搜索采集",
    "crawl.schedule_ready": "每小时监测",
    maturity_report: "成熟度报告",
    "stage_goal.completed": "阶段目标完成",
    "stage_goal.timeline": "阶段目标时间线",
    "placement.impact.positive": "投放复盘正向",
    public_delivery_package: "公开交付包",
    "content_delivery.loop": "内容交付闭环",
    frontend_pages: "前端页面"
  };
  return labels[value] ?? value;
}

function providerModeLabel(value?: string) {
  const labels: Record<string, string> = {
    real: "真实渠道",
    mock: "Mock 演示",
    not_ready: "待配置"
  };
  return labels[value ?? ""] ?? "待确认";
}

function searchAccessLabel(value?: string) {
  const labels: Record<string, string> = {
    api_ready_no_live_search: "普通 API",
    needs_config: "待配置",
    ready_for_collection: "联网可采集",
    ready_for_demo: "演示可用"
  };
  return labels[value ?? ""] ?? "待确认";
}

function asRoute(value: string) {
  return value as Route;
}

export default async function DemoOverviewPage() {
  const [apiStatus, fileSummary, fileVerification] = await Promise.all([
    readApiDemoStatus(),
    readDemoSummary(),
    readVerificationSummary()
  ]);
  const fileContentDeliveryLoop = await readContentDeliveryLoopSummary();
  const summary = apiStatus?.summary ?? fileSummary;
  const verification = apiStatus?.verification ?? fileVerification;
  const contentDeliveryLoop = apiStatus?.contentDeliveryLoop ?? fileContentDeliveryLoop;

  if (!summary) {
    return (
      <div className="stack">
        <div className="topbar">
          <div>
            <div className="eyebrow">演示总览</div>
            <h1>暂无端到端演示数据</h1>
            <p className="subtle">运行后端演示脚本后，这里会展示最新闭环演示摘要。</p>
          </div>
        </div>
        <section className="panel">
          <h2>演示摘要文件</h2>
          <p className="subtle">{summaryPath}</p>
        </section>
      </div>
    );
  }

  const projectUrl = asRoute(summary.project_url);
  const publicShareUrl = asRoute(summary.public_share_url);
  const latestReportUrl = asRoute(summary.latest_report_url);
  const deliveryPackageUrl = asRoute(summary.delivery_package_url);
  const impactUrl = asRoute(
    `/projects/${summary.project_id}/placements/${summary.stage_goal.placement_id}/impact`
  );
  const draftAction = summary.stage_goal.action_results.find(
    (item) => item.action_type === "generate_draft"
  );
  const draftUrl = asRoute(draftAction?.resource_url ?? `/projects/${summary.project_id}`);
  const reviewScore = draftAction?.detail.review_score;
  const reviewGrade = draftAction?.detail.review_grade;
  const providerSummary = summary.provider_summary;
  const providers = summary.providers ?? [];
  const firstBlockedProvider = providers.find((provider) => provider.provider_type !== "mock" && !provider.collection_ready);
  const realCollectionProviders = providers
    .filter(
      (provider) =>
        provider.provider_type !== "mock" &&
        ((provider.project_result_count ?? 0) > 0 ||
          (provider.project_success_task_count ?? 0) > 0 ||
          (provider.project_failed_task_count ?? 0) > 0)
    )
    .sort((left, right) => {
      if ((right.project_result_count ?? 0) !== (left.project_result_count ?? 0)) {
        return (right.project_result_count ?? 0) - (left.project_result_count ?? 0);
      }
      return (right.project_total_tokens ?? 0) - (left.project_total_tokens ?? 0);
    });

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">演示总览</div>
          <h1>GEO MVP 闭环演示</h1>
          <p className="subtle">
            运行批次 {summary.run_label}｜项目 {summary.project_id}｜生成时间 {summary.generated_at}
          </p>
        </div>
        <div className="row-actions">
          <Link className="button" href={projectUrl}>
            打开项目
          </Link>
          <Link className="button secondary" href={publicShareUrl}>
            公开交付包
          </Link>
        </div>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>MVP 验收</span>
          <strong>{verification?.ok ? "通过" : "待验证"}</strong>
        </div>
        <div className="panel metric">
          <span>复盘结论</span>
          <strong>{statusLabel(summary.stage_goal.review_status)}</strong>
        </div>
        <div className="panel metric">
          <span>提及率变化</span>
          <strong>{pct(summary.stage_goal.metric_deltas.company_mention_rate_delta)}</strong>
        </div>
        <div className="panel metric">
          <span>推荐率变化</span>
          <strong>{pct(summary.stage_goal.metric_deltas.company_recommendation_rate_delta)}</strong>
        </div>
        <div className="panel metric">
          <span>目标信源出现</span>
          <strong>{summary.stage_goal.metric_deltas.source_after_appearances}</strong>
        </div>
      </section>

      {providerSummary ? (
        <section className="panel">
          <div className="section-head">
            <div>
              <h2>真实检索接入</h2>
              <p className="subtle">
                演示闭环可用不等于真实大模型搜索已接通；真实渠道必须配置完整并通过测试调用。
              </p>
            </div>
            <span className={providerSummary.has_real_provider ? "tag active" : "tag"}>
              {providerModeLabel(String(providerSummary.mode ?? ""))}
            </span>
          </div>
          <div className="grid cols-4">
            <div className="metric">
              <span>真实可采集</span>
              <strong>{Number(providerSummary.real_collection_ready ?? 0)}</strong>
              <small>已测通真实 Provider</small>
            </div>
            <div className="metric">
              <span>联网搜索</span>
              <strong>{Number(providerSummary.web_search_ready ?? 0)}</strong>
              <small>Kimi/联网工具类渠道</small>
            </div>
            <div className="metric">
              <span>Mock 渠道</span>
              <strong>{Number(providerSummary.mock_ready ?? 0)}</strong>
              <small>用于产品闭环演示</small>
            </div>
            <div className="metric">
              <span>下一步</span>
              <strong>{providerSummary.has_real_provider ? "可实采" : "补渠道"}</strong>
              <small>
                {firstBlockedProvider?.collection_blocker ?? "配置并测试真实 Provider 后再跑真实采集"}
              </small>
            </div>
          </div>
          {realCollectionProviders.length > 0 ? (
            <>
              <div className="section-head">
                <div>
                  <h3>真实模型实采证据</h3>
                  <p className="subtle">来自当前演示项目的真实 Provider 采集任务，不含答案原文和 API Key。</p>
                </div>
                <Link className="button secondary" href={asRoute(`/projects/${summary.project_id}/dashboard`)}>
                  项目驾驶舱
                </Link>
              </div>
              <div className="grid cols-3">
                {realCollectionProviders.slice(0, 6).map((provider) => (
                  <Link
                    className="panel metric"
                    href={asRoute(
                      provider.project_latest_task_id
                        ? `/projects/${summary.project_id}/tasks/${provider.project_latest_task_id}`
                        : `/admin/providers/${provider.provider_id}/test?return_to=/demo`
                    )}
                    key={`collection-${provider.provider_id}`}
                  >
                    <span>{provider.name}</span>
                    <strong>{provider.project_result_count}</strong>
                    <small>
                      成功 {provider.project_success_task_count}｜失败 {provider.project_failed_task_count}｜tokens{" "}
                      {provider.project_total_tokens}
                    </small>
                    {provider.project_latest_task_error_message ? (
                      <small className="danger-text">{provider.project_latest_task_error_message}</small>
                    ) : (
                      <small>最近任务 {statusLabel(provider.project_latest_task_status ?? "unknown")}</small>
                    )}
                  </Link>
                ))}
              </div>
            </>
          ) : null}
          {providers.length > 0 ? (
            <div className="list">
              {providers
                .sort((left, right) => {
                  if (Number(right.collection_ready) !== Number(left.collection_ready)) {
                    return Number(right.collection_ready) - Number(left.collection_ready);
                  }
                  return (right.project_result_count ?? 0) - (left.project_result_count ?? 0);
                })
                .slice(0, 4)
                .map((provider) => (
                  <Link
                    className="row"
                    href={asRoute(`/admin/providers/${provider.provider_id}/test?return_to=/demo`)}
                    key={provider.provider_id}
                  >
                    <div>
                      <h3>{provider.name}</h3>
                      <small>
                        {provider.provider_type}｜{searchAccessLabel(provider.search_access_status)}｜
                        {provider.collection_ready ? "可采集" : provider.collection_blocker ?? "不可采集"}
                      </small>
                    </div>
                    <span className={provider.collection_ready ? "tag active" : "tag"}>
                      {provider.collection_ready ? "ready" : "check"}
                    </span>
                  </Link>
                ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>MVP 验收状态</h2>
            <p className="subtle">
              最新自动验收覆盖登录、项目、成熟度报告、阶段目标、投放复盘、交付包和关键页面。
            </p>
          </div>
          <span className={verification?.ok ? "tag active" : "tag"}>
            {verification?.ok ? "全部通过" : "等待验收"}
          </span>
        </div>
        {verification ? (
          <div className="grid cols-4">
            {verification.checks.map((check) => (
              <div className="metric" key={check.check}>
                <span>{checkLabel(check.check)}</span>
                <strong>{check.ok ? "通过" : "失败"}</strong>
                <small>
                  {typeof check.total_score === "number"
                    ? `${check.total_score} 分｜${check.maturity_level ?? ""}`
                    : null}
                  {typeof check.event_count === "number" ? `${check.event_count} 个事件` : null}
                  {typeof check.deliverable_count === "number"
                    ? `${check.deliverable_count} 份交付`
                    : null}
                  {typeof check.marker_count === "number" ? `${check.marker_count} 个页面标记` : null}
                  {check.metric_deltas
                    ? `提及 ${pct(check.metric_deltas.company_mention_rate_delta)}｜推荐 ${pct(
                        check.metric_deltas.company_recommendation_rate_delta
                      )}`
                    : null}
                </small>
              </div>
            ))}
          </div>
        ) : (
          <p className="subtle">尚未生成验收结果。运行 `scripts/verify_mvp_demo.py` 后这里会自动展示。</p>
        )}
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>内容交付闭环验收</h2>
            <p className="subtle">
              无端口专项验证：报告选题、稿件评分、人工通过、投放发布、客户分享和公开确认。
            </p>
          </div>
          <span className={contentDeliveryLoop?.ok ? "tag active" : "tag"}>
            {contentDeliveryLoop?.ok ? "已验证" : "待验证"}
          </span>
        </div>
        {contentDeliveryLoop ? (
          <div className="grid cols-4">
            <div className="metric">
              <span>稿件评分</span>
              <strong>{contentDeliveryLoop.ai_review.score}</strong>
              <small>{contentDeliveryLoop.ai_review.grade}｜{contentDeliveryLoop.draft.status}</small>
            </div>
            <div className="metric">
              <span>人工审核</span>
              <strong>{statusLabel(contentDeliveryLoop.human_review.status)}</strong>
              <small>{contentDeliveryLoop.topic}</small>
            </div>
            <div className="metric">
              <span>投放交付</span>
              <strong>{statusLabel(contentDeliveryLoop.placement.delivery_status)}</strong>
              <small>
                {contentDeliveryLoop.placement.status}｜{contentDeliveryLoop.placement.visibility}
              </small>
            </div>
            <div className="metric">
              <span>公开包</span>
              <strong>{contentDeliveryLoop.public_package.deliverable_count}</strong>
              <small>
                {contentDeliveryLoop.public_package.temporary_placement_visible ? "临时投放可见" : "未覆盖临时投放"}
              </small>
            </div>
          </div>
        ) : (
          <p className="subtle">
            尚未生成专项验收结果。运行 `scripts/verify_content_delivery_loop_testclient.py` 后这里会自动展示。
          </p>
        )}
      </section>

      <section className="grid cols-3">
        <div className="panel">
          <h2>演示账号</h2>
          <div className="list">
            <div className="row">
              <div>
                <h3>{summary.login.email}</h3>
                <small>{summary.login.password ? `密码 ${summary.login.password}` : "当前登录账号"}</small>
              </div>
              <span className="tag">demo</span>
            </div>
          </div>
        </div>
        <div className="panel">
          <h2>报告与审核</h2>
          <div className="list">
            <Link className="row" href={latestReportUrl}>
              <div>
                <h3>成熟度报告</h3>
                <small>报告 ID {summary.report_ids.at(-1)}</small>
              </div>
              <span className="tag active">L4</span>
            </Link>
            <Link className="row" href={draftUrl}>
              <div>
                <h3>稿件审核</h3>
                <small>
                  评分 {typeof reviewScore === "number" ? reviewScore : "-"}｜评级{" "}
                  {typeof reviewGrade === "string" ? reviewGrade : "-"}
                </small>
              </div>
              <span className="tag">AI</span>
            </Link>
          </div>
        </div>
        <div className="panel">
          <h2>交付状态</h2>
          <div className="list">
            <Link className="row" href={deliveryPackageUrl}>
              <div>
                <h3>内部交付包</h3>
                <small>Share {summary.stage_goal.share_id}</small>
              </div>
              <span className="tag">{statusLabel(summary.stage_goal.delivery_status)}</span>
            </Link>
            <Link className="row" href={impactUrl}>
              <div>
                <h3>投放复盘</h3>
                <small>Placement {summary.stage_goal.placement_id}</small>
              </div>
              <span className="tag active">{statusLabel(summary.stage_goal.review_status)}</span>
            </Link>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>闭环动作</h2>
            <p className="subtle">
              搜索采集、撰稿评分、人工审核、投放发布、交付跟进已经在同一阶段目标下串联。
            </p>
          </div>
          <span className="tag active">{statusLabel(summary.stage_goal.goal_status)}</span>
        </div>
        <div className="list">
          {summary.stage_goal.action_results.map((action) => (
            <Link
              className="row review-row"
              href={asRoute(action.resource_url ?? summary.project_url)}
              key={`${action.action_type}-${action.resource_id ?? "none"}`}
            >
              <div>
                <div className="meta-line">
                  <span>{actionLabel(action.action_type)}</span>
                  <span>{action.resource_type ?? "resource"}</span>
                  <span>ID {action.resource_id ?? "-"}</span>
                </div>
                <h3>{action.message}</h3>
              </div>
              <span className="tag">{statusLabel(action.status)}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>验证摘要</h2>
        <div className="grid cols-4">
          <div className="metric">
            <span>批量采集任务</span>
            <strong>{summary.crawl_task_id}</strong>
          </div>
          <div className="metric">
            <span>复盘任务</span>
            <strong>{summary.stage_goal.processed_jobs[0]?.status ?? "idle"}</strong>
          </div>
          <div className="metric">
            <span>弱基线样本</span>
            <strong>{summary.stage_goal.weakened_baseline_count}</strong>
          </div>
          <div className="metric">
            <span>客户确认记录</span>
            <strong>{summary.stage_goal.access_log_id}</strong>
          </div>
        </div>
      </section>
    </div>
  );
}
