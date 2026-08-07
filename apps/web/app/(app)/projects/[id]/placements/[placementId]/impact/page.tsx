import Link from "next/link";
import {
  createDeliveryShareAction,
  createPlacementImpactActionGoalsAction,
  generatePlacementReviewReportAction,
  runCrawlAction,
  updatePlacementArchiveAction,
  updatePlacementStatusAction
} from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import {
  getPlacementImpact,
  getPlacementImpactMarkdownUrl,
  getPlacementImpactPdfUrl,
  getProject
} from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string; placementId: string }>;
  searchParams: Promise<{ placement_status?: string; archive_saved?: string; placement_impact_actions?: string }>;
};

function pct(value: number | undefined) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function deltaPct(value: number | undefined) {
  const normalized = value ?? 0;
  const sign = normalized > 0 ? "+" : "";
  return `${sign}${Math.round(normalized * 100)}%`;
}

function reportStatusLabel(status: string) {
  const labels: Record<string, string> = {
    insufficient_sample: "样本不足",
    positive: "正向",
    mixed: "部分改善",
    needs_optimization: "需优化"
  };
  return labels[status] ?? status;
}

function visibilityLabel(value?: string | null) {
  return value === "customer_visible" ? "客户可见" : "内部可见";
}

function deliveryStatusLabel(value?: string | null) {
  const labels: Record<string, string> = {
    not_delivered: "未交付",
    ready: "待交付",
    delivered: "已交付",
    accepted: "已确认"
  };
  return labels[value ?? ""] ?? "未交付";
}

export default async function PlacementImpactPage({ params, searchParams }: PageProps) {
  const { id, placementId } = await params;
  const queryParams = await searchParams;
  const runReviewCrawl = runCrawlAction.bind(null, id);
  const generateReviewReport = generatePlacementReviewReportAction.bind(null, id, Number(placementId));
  const createImpactGoals = createPlacementImpactActionGoalsAction.bind(null, id, Number(placementId));
  const updateArchive = updatePlacementArchiveAction.bind(null, id, Number(placementId));
  const publishPlacement = updatePlacementStatusAction.bind(null, id, Number(placementId), "published");
  const createDeliveryShare = createDeliveryShareAction.bind(null, id);
  const markdownUrl = getPlacementImpactMarkdownUrl(id, placementId);
  const pdfUrl = getPlacementImpactPdfUrl(id, placementId);
  const [project, impact] = await Promise.all([
    getProject(id),
    getPlacementImpact(id, placementId)
  ]);
  const afterSampleSize = Number(impact.review_report.evidence.after_sample_size ?? impact.after.total_answers ?? 0);
  const impactActionResult = queryParams.placement_impact_actions ?? "";
  const impactActionCreatedCount = Number(impactActionResult);
  const impactActionFeedback =
    impactActionResult === "existing"
      ? "这条投放复盘的下一轮目标已经存在，可直接进入阶段目标继续推进。"
      : Number.isFinite(impactActionCreatedCount) && impactActionCreatedCount > 0
        ? `已从这条投放复盘生成 ${impactActionCreatedCount} 个下一轮优化目标。`
        : "";
  const workflowSteps = [
    {
      title: "投放发布",
      done: impact.placement.status === "published",
      detail: impact.placement.published_at ? `已发布 ${impact.placement.published_at}` : impact.placement.status
    },
    {
      title: "复盘采集",
      done: afterSampleSize >= 5 || Boolean(impact.review_report.evidence.review_crawl_task_id),
      detail: impact.review_report.evidence.review_crawl_task_id
        ? `任务 #${impact.review_report.evidence.review_crawl_task_id}`
        : `投放后样本 ${afterSampleSize}`
    },
    {
      title: "客户可见",
      done: impact.placement.visibility === "customer_visible",
      detail: visibilityLabel(impact.placement.visibility)
    },
    {
      title: "交付确认",
      done: impact.placement.delivery_status === "accepted",
      detail: deliveryStatusLabel(impact.placement.delivery_status)
    }
  ];

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">投放复盘</div>
          <h1>{impact.placement.channel}</h1>
          <p className="subtle">{project.name}｜基准时间 {impact.baseline_time}</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}/sources`}>
          返回信源
        </Link>
        <Link className="button secondary" href={`/projects/${id}/review-archive`}>
          复盘归档
        </Link>
        <form action={runReviewCrawl}>
          <SubmitButton pendingText="采集中...">重新采集复盘</SubmitButton>
        </form>
        <form action={generateReviewReport}>
          <SubmitButton className="button secondary" pendingText="生成报告中...">
            生成复盘报告
          </SubmitButton>
        </form>
        <form action={createImpactGoals}>
          <SubmitButton pendingText="生成目标中...">生成下一轮目标</SubmitButton>
        </form>
        {impact.placement.status !== "published" ? (
          <form action={publishPlacement}>
            <SubmitButton pendingText="发布中...">发布并准备交付</SubmitButton>
          </form>
        ) : null}
        {impact.placement.visibility === "customer_visible" && impact.placement.delivery_status !== "not_delivered" ? (
          <form action={createDeliveryShare}>
            <input type="hidden" name="name" value={`${project.name} 客户交付包`} />
            <SubmitButton className="button secondary" pendingText="生成分享中...">
              生成客户分享链接
            </SubmitButton>
          </form>
        ) : null}
        <Link className="button secondary" href={`/projects/${id}/reports/compare`}>
          报告对比
        </Link>
        <a className="button secondary" href={markdownUrl}>
          导出 Markdown
        </a>
        <a className="button secondary" href={pdfUrl}>
          导出 PDF
        </a>
      </div>

      {queryParams.placement_status ? (
        <div className="notice success">
          投放状态已更新为 {queryParams.placement_status === "published" ? "已发布并准备交付" : queryParams.placement_status}。
          {queryParams.placement_status === "published" ? " 现在可以补采复盘样本，或生成客户分享链接。" : ""}
        </div>
      ) : null}

      {queryParams.archive_saved === "1" ? (
        <div className="notice success">交付信息已保存，客户交付包和复盘归档会使用最新可见范围与交付状态。</div>
      ) : null}

      {impactActionFeedback ? (
        <div className="notice success">
          {impactActionFeedback} <Link href={`/projects/${id}#stage-goals`}>查看阶段目标</Link>
        </div>
      ) : null}

      <section className="panel" id="delivery-management">
        <h2>复盘摘要</h2>
        <p className="subtle">{impact.summary}</p>
      </section>

      <section className="panel" id="delivery-workflow">
        <div className="section-head">
          <div>
            <h2>投放闭环进度</h2>
            <p className="subtle">从计划发布到复盘采集、客户可见和客户确认，形成投放后的交付闭环。</p>
          </div>
          <span className={workflowSteps.every((step) => step.done) ? "tag active" : "tag"}>
            {workflowSteps.filter((step) => step.done).length}/{workflowSteps.length}
          </span>
        </div>
        <div className="grid cols-4">
          {workflowSteps.map((step) => (
            <div className="metric" key={step.title}>
              <span>{step.title}</span>
              <strong>{step.done ? "完成" : "待办"}</strong>
              <small>{step.detail}</small>
            </div>
          ))}
        </div>
        <div className="row-actions">
          {impact.placement.status !== "published" ? (
            <form action={publishPlacement}>
              <SubmitButton pendingText="发布中...">发布并准备交付</SubmitButton>
            </form>
          ) : null}
          {impact.placement.visibility === "customer_visible" && impact.placement.delivery_status !== "not_delivered" ? (
            <form action={createDeliveryShare}>
              <input type="hidden" name="name" value={`${project.name} 客户交付包`} />
              <SubmitButton className="button secondary" pendingText="生成分享中...">
                生成客户分享链接
              </SubmitButton>
            </form>
          ) : null}
          {impact.placement.status === "published" && afterSampleSize < 5 ? (
            <form action={runReviewCrawl}>
              <SubmitButton className="button secondary" pendingText="补采中...">
                补采复盘样本
              </SubmitButton>
            </form>
          ) : null}
          {impact.placement.status === "published" && afterSampleSize >= 5 ? (
            <form action={generateReviewReport}>
              <SubmitButton className="button secondary" pendingText="生成报告中...">
                生成复盘后成熟度报告
              </SubmitButton>
            </form>
          ) : null}
          <form action={createImpactGoals}>
            <SubmitButton pendingText="生成目标中...">生成下一轮优化目标</SubmitButton>
          </form>
          {impact.placement.visibility !== "customer_visible" ? <span className="tag">下一步：设为客户可见</span> : null}
          <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
            查看交付包
          </Link>
        </div>
      </section>

      <section className="panel">
        <h2>复盘报告</h2>
        <div className="list">
          <div className="row">
            <div>
              <h3>{reportStatusLabel(impact.review_report.status)}</h3>
              <small>
                {impact.review_report.archive?.version ?? "v1"}｜
                {impact.review_report.archive?.archive_note ?? "暂无归档备注"}｜
                {visibilityLabel(impact.review_report.archive?.visibility)}｜
                {deliveryStatusLabel(impact.review_report.archive?.delivery_status)}｜
                {impact.review_report.conclusion}
              </small>
            </div>
            <span className="tag">{impact.review_report.evidence.review_task_status ?? "manual"}</span>
          </div>
          <div className="grid cols-3">
            <div className="metric">
              <span>样本变化</span>
              <strong>{impact.review_report.metric_deltas.sample_size_delta ?? 0}</strong>
            </div>
            <div className="metric">
              <span>提及率变化</span>
              <strong>{deltaPct(impact.review_report.metric_deltas.company_mention_rate_delta)}</strong>
            </div>
            <div className="metric">
              <span>推荐率变化</span>
              <strong>{deltaPct(impact.review_report.metric_deltas.company_recommendation_rate_delta)}</strong>
            </div>
          </div>
          {impact.review_report.evidence.review_crawl_task_id ? (
            <Link className="button secondary" href={`/projects/${id}/tasks/${impact.review_report.evidence.review_crawl_task_id}`}>
              查看自动复盘采集任务
            </Link>
          ) : null}
        </div>
      </section>

      <section className="panel">
        <h2>交付管理</h2>
        <form className="form" action={updateArchive}>
          <div className="field">
            <label htmlFor="archive_note">归档备注</label>
            <textarea
              id="archive_note"
              name="archive_note"
              defaultValue={impact.placement.archive_note ?? impact.placement.notes ?? ""}
              placeholder="记录客户交付口径、内部复盘说明或下一次跟进重点"
            />
          </div>
          <div className="grid cols-2">
            <div className="field">
              <label htmlFor="visibility">可见范围</label>
              <select id="visibility" name="visibility" defaultValue={impact.placement.visibility ?? "internal"}>
                <option value="internal">内部可见</option>
                <option value="customer_visible">客户可见</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="delivery_status">交付状态</label>
              <select
                id="delivery_status"
                name="delivery_status"
                defaultValue={impact.placement.delivery_status ?? "not_delivered"}
              >
                <option value="not_delivered">未交付</option>
                <option value="ready">待交付</option>
                <option value="delivered">已交付</option>
                <option value="accepted">已确认</option>
              </select>
            </div>
          </div>
          <SubmitButton pendingText="保存中...">保存交付信息</SubmitButton>
        </form>
      </section>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>投放后样本</span>
          <strong>{impact.after.total_answers ?? 0}</strong>
        </div>
        <div className="panel metric">
          <span>提及率</span>
          <strong>{pct(impact.after.company_mention_rate)}</strong>
        </div>
        <div className="panel metric">
          <span>信源出现</span>
          <strong>{impact.source_after_appearances}</strong>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>投放前</h2>
          <div className="list">
            <div className="row"><h3>答案样本</h3><span className="tag">{impact.before.total_answers ?? 0}</span></div>
            <div className="row"><h3>企业提及率</h3><span className="tag">{pct(impact.before.company_mention_rate)}</span></div>
            <div className="row"><h3>企业推荐率</h3><span className="tag">{pct(impact.before.company_recommendation_rate)}</span></div>
          </div>
        </div>
        <div className="panel">
          <h2>投放后</h2>
          <div className="list">
            <div className="row"><h3>答案样本</h3><span className="tag">{impact.after.total_answers ?? 0}</span></div>
            <div className="row"><h3>企业提及率</h3><span className="tag">{pct(impact.after.company_mention_rate)}</span></div>
            <div className="row"><h3>企业推荐率</h3><span className="tag">{pct(impact.after.company_recommendation_rate)}</span></div>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>下一步建议</h2>
        <div className="list">
          {impact.recommendations.map((item) => (
            <div className="row" key={item}>
              <h3>{item}</h3>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
