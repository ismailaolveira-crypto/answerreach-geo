import Link from "next/link";
import type { Route } from "next";
import { generateDraftAndReviewAction, reviewDraftAction, reviseDraftFromReviewAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import {
  getArticleDrafts,
  getArticleReviews,
  getContentAssets,
  getMaturityReports,
  getPlacements,
  getProject
} from "@/lib/api";

function asRoute(value: string) {
  return value as Route;
}

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    bulk_generated?: string;
    bulk_reviewed?: string;
    action_error?: string;
  }>;
};

function contextText(value: unknown, fallback = "未绑定") {
  return value == null || value === "" ? fallback : String(value);
}

export default async function ProjectDraftsPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const queryParams = await searchParams;
  const [project, drafts, reports, assets, placements] = await Promise.all([
    getProject(id),
    getArticleDrafts(id).catch(() => []),
    getMaturityReports(id).catch(() => []),
    getContentAssets(id).catch(() => []),
    getPlacements(id).catch(() => [])
  ]);
  const generateDraftAndReview = generateDraftAndReviewAction.bind(null, id);
  const latestReport = reports[0];
  const reportDraftTopics = [
    ...(latestReport?.report_json.next_content_topics ?? []),
    ...(latestReport?.report_json.question_gaps ?? []).map((gap) => gap.question_text),
    ...(latestReport?.report_json.keyword_gaps ?? []).map((gap) => `${gap.keyword}怎么做 GEO 优化`)
  ].filter((topic, index, list) => topic && list.indexOf(topic) === index);
  const reviewEntries = await Promise.all(
    drafts.slice(0, 40).map(async (draft) => ({
      draftId: draft.id,
      reviews: await getArticleReviews(id, draft.id).catch(() => [])
    }))
  );
  const reviewMap = new Map(reviewEntries.map((entry) => [entry.draftId, entry.reviews]));
  const reviewedCount = drafts.filter((draft) => (reviewMap.get(draft.id)?.length ?? 0) > 0).length;
  const approvedCount = drafts.filter((draft) => draft.status === "approved").length;
  const revisionCount = drafts.filter((draft) => draft.draft_type === "revision").length;
  const placedDraftIds = new Set(placements.map((placement) => placement.article_draft_id).filter(Boolean));
  const assetDraftTitles = new Set(assets.filter((asset) => asset.publish_channel === "AI 稿件入库").map((asset) => asset.title));
  const sourcedCount = drafts.filter((draft) => draft.source_context?.source_report_id || draft.source_context?.stage_goal_id).length;
  const approvedUnplacedCount = drafts.filter((draft) => draft.status === "approved" && !placedDraftIds.has(draft.id)).length;

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">AI 撰稿工作台</div>
          <h1>{project.name} 稿件</h1>
          <p className="subtle">集中管理报告选题、AI 初稿、审核评分、优化版、内容入库和投放承接。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
        <Link className="button secondary" href="/reviews">
          审核工作台
        </Link>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>稿件总数</span>
          <strong>{drafts.length}</strong>
        </div>
        <div className="panel metric">
          <span>已评分</span>
          <strong>{reviewedCount}</strong>
        </div>
        <div className="panel metric">
          <span>人工通过</span>
          <strong>{approvedCount}</strong>
          <small>待投放 {approvedUnplacedCount}</small>
        </div>
        <div className="panel metric">
          <span>报告/目标承接</span>
          <strong>{sourcedCount}</strong>
        </div>
      </section>

      {queryParams.bulk_generated ? (
        <div className="notice success">
          已从成熟度报告批量生成 {queryParams.bulk_generated} 篇稿件，并完成 {queryParams.bulk_reviewed ?? queryParams.bulk_generated} 篇 AI 评分。
        </div>
      ) : null}

      {queryParams.action_error ? (
        <div className="notice danger">
          操作没有完成：{queryParams.action_error}
        </div>
      ) : null}

      <section className="grid cols-2">
        <div className="panel">
          <div className="section-head">
            <div>
              <h2>生成新稿</h2>
              <p className="subtle">优先使用最新成熟度报告的推荐选题、问题缺口和关键词缺口。</p>
            </div>
            <span className={latestReport ? "tag active" : "tag"}>{latestReport ? `报告 #${latestReport.id}` : "无报告"}</span>
          </div>
          <form action={generateDraftAndReview} className="form">
            {reportDraftTopics.length > 0 ? (
              <div className="field">
                <label>报告建议选题</label>
                <select name="suggested_topic" defaultValue={reportDraftTopics[0]}>
                  {reportDraftTopics.slice(0, 10).map((topic) => (
                    <option key={topic} value={topic}>
                      {topic}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="field">
              <label>自定义选题</label>
              <input name="topic" placeholder={reportDraftTopics[0] ?? "围绕目标问题生成 GEO 优化稿"} />
            </div>
            <SubmitButton pendingText="生成并评分中...">生成并评分</SubmitButton>
          </form>
        </div>

        <div className="panel">
          <h2>工作台状态</h2>
          <div className="grid cols-2">
            <div className="metric">
              <span>优化版</span>
              <strong>{revisionCount}</strong>
              <small>来自审核建议的重写稿</small>
            </div>
            <div className="metric">
              <span>已投放</span>
              <strong>{placedDraftIds.size}</strong>
              <small>
                {approvedUnplacedCount > 0 ? (
                  <Link href={`/projects/${id}/placements`}>还有 {approvedUnplacedCount} 篇待加入计划</Link>
                ) : (
                  "绑定 article_draft_id 的投放记录"
                )}
              </small>
            </div>
            <div className="metric">
              <span>已入库</span>
              <strong>{drafts.filter((draft) => assetDraftTitles.has(draft.title)).length}</strong>
              <small>沉淀为内容资产</small>
            </div>
            <div className="metric">
              <span>待评分</span>
              <strong>{Math.max(0, drafts.length - reviewedCount)}</strong>
              <small>可在列表中逐条 AI 评分</small>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>稿件列表</h2>
            <p className="subtle">按最近更新时间排序，展示每篇稿件的来源承接、审核结果、入库和投放状态。</p>
          </div>
          <span className="tag">{drafts.length} 篇</span>
        </div>
        <div className="list">
          {drafts.length === 0 ? (
            <p className="subtle">还没有稿件。可以先基于成熟度报告推荐选题生成第一篇。</p>
          ) : (
            drafts.map((draft) => {
              const latestReview = reviewMap.get(draft.id)?.[0];
              const reviewDraft = reviewDraftAction.bind(null, id, draft.id);
              const reviseDraft = reviseDraftFromReviewAction.bind(null, id, draft.id);
              const sourceContext = draft.source_context ?? {};
              const sourceReportId = sourceContext.source_report_id;
              const stageGoalId = sourceContext.stage_goal_id;
              const placed = placedDraftIds.has(draft.id);
              const assetCreated = assetDraftTitles.has(draft.title);
              return (
                <div className="row" key={draft.id}>
                  <div>
                    <Link className="title-link" href={asRoute(`/projects/${id}/drafts/${draft.id}`)}>
                      <h3>{draft.title}</h3>
                    </Link>
                    <small>
                      {draft.status}｜{draft.draft_type}｜{contextText(sourceContext.topic_source, "项目关键词")}
                      {sourceReportId ? `｜报告 #${sourceReportId}` : ""}
                      {stageGoalId ? `｜阶段目标 #${stageGoalId}` : ""}
                    </small>
                    <small>
                      {latestReview ? `审核 ${latestReview.total_score} 分 ${latestReview.grade}` : "待 AI 评分"}
                      {assetCreated ? "｜已入库" : ""}
                      {placed ? "｜已投放" : ""}
                    </small>
                  </div>
                  <div className="row-actions">
                    {latestReview ? (
                      <form action={reviseDraft}>
                        <SubmitButton className="button secondary" pendingText="优化复评中...">优化复评</SubmitButton>
                      </form>
                    ) : (
                      <form action={reviewDraft}>
                        <SubmitButton className="button secondary" pendingText="审核中...">审核打分</SubmitButton>
                      </form>
                    )}
                    <Link className="button secondary" href={asRoute(`/projects/${id}/drafts/${draft.id}`)}>
                      查看稿件
                    </Link>
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
