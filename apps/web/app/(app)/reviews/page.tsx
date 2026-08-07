import Link from "next/link";
import type { Route } from "next";
import {
  bulkApproveHighScoreDraftsAction,
  bulkReviewQueueAction,
  decideContentAssetReviewAction,
  decideDraftReviewAction,
  reviseDraftFromReviewAction,
  reviewContentAssetAction,
  reviewDraftAction
} from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getReviewQueue } from "@/lib/api";

function asRoute(value: string) {
  return value as Route;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    draft: "待评分",
    pending_review: "待人工审核",
    needs_revision: "已退回",
    rejected: "已拒绝"
  };
  return labels[status] ?? status;
}

export default async function ReviewWorkbenchPage({
  searchParams
}: Readonly<{
  searchParams: Promise<{
    bulk_scored?: string;
    bulk_approved?: string;
    bulk_projects?: string;
    action_error?: string;
  }>;
}>) {
  const params = await searchParams;
  const queue = await getReviewQueue().catch(() => []);
  const missingAiReviewCount = queue.filter((item) => item.latest_score == null).length;
  const highScoreDraftCount = queue.filter(
    (item) => item.type === "draft" && item.status !== "approved" && Number(item.latest_score ?? 0) >= 85
  ).length;
  const revisionCount = queue.filter((item) => item.status === "needs_revision" || item.status === "rejected").length;
  const bulkScored = Number(params.bulk_scored ?? 0);
  const bulkApproved = Number(params.bulk_approved ?? 0);
  const bulkProjectIds = String(params.bulk_projects ?? "")
    .split(",")
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item) && item > 0);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">审核工作台</div>
          <h1>集中处理稿件和内容资产</h1>
          <p className="subtle">先用 AI 评分识别问题，再由人工确认通过或退回，形成可追踪的 GEO 内容生产流。</p>
        </div>
        <div className="row-actions">
          <form action={bulkReviewQueueAction}>
            <SubmitButton disabled={missingAiReviewCount === 0} pendingText="批量评分中...">
              批量 AI 评分
            </SubmitButton>
          </form>
          <form action={bulkApproveHighScoreDraftsAction}>
            <SubmitButton className="button secondary" disabled={highScoreDraftCount === 0} pendingText="批量通过中...">
              批量通过高分稿
            </SubmitButton>
          </form>
          <span className="tag">最多 20 条</span>
          <Link className="button secondary" href="/projects">
            查看项目
          </Link>
        </div>
      </div>

      {bulkScored > 0 ? (
        <section className="panel">
          <h2>批量评分已完成</h2>
          <p className="subtle">本次已为 {bulkScored} 条待审核内容生成 AI 评分。请继续查看分数、问题和建议，再做人工通过或退回。</p>
        </section>
      ) : null}

      {bulkApproved > 0 ? (
        <section className="panel">
          <h2>批量通过已完成</h2>
          <p className="subtle">本次已人工确认通过 {bulkApproved} 篇高分稿件。下一步可把通过稿件加入投放计划。</p>
          {bulkProjectIds.length > 0 ? (
            <div className="row-actions">
              {bulkProjectIds.map((projectId) => (
                <Link className="button secondary" href={`/projects/${projectId}/placements`} key={projectId}>
                  进入项目 #{projectId} 投放运营
                </Link>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {params.action_error ? (
        <section className="notice danger">
          操作没有完成：{params.action_error}
        </section>
      ) : null}

      <section className="grid cols-4">
        <div className="panel metric">
          <span>待处理</span>
          <strong>{queue.length}</strong>
        </div>
        <div className="panel metric">
          <span>待 AI 评分</span>
          <strong>{missingAiReviewCount}</strong>
        </div>
        <div className="panel metric">
          <span>退回待优化</span>
          <strong>{revisionCount}</strong>
        </div>
        <div className="panel metric">
          <span>高分待通过</span>
          <strong>{highScoreDraftCount}</strong>
        </div>
      </section>

      <section className="panel">
        <h2>审核队列</h2>
        <div className="list">
          {queue.length === 0 ? (
            <p className="subtle">暂无待审核内容。新的稿件或内容资产会出现在这里。</p>
          ) : (
            queue.map((item) => {
              const projectId = String(item.project_id);
              const isDraft = item.type === "draft";
              const reviewAction = isDraft
                ? reviewDraftAction.bind(null, projectId, item.id)
                : reviewContentAssetAction.bind(null, projectId, item.id);
              const approveAction = isDraft
                ? decideDraftReviewAction.bind(null, projectId, item.id, "approved")
                : decideContentAssetReviewAction.bind(null, projectId, item.id, "approved");
              const rejectAction = isDraft
                ? decideDraftReviewAction.bind(null, projectId, item.id, "rejected")
                : decideContentAssetReviewAction.bind(null, projectId, item.id, "rejected");
              const reviseAction = reviseDraftFromReviewAction.bind(null, projectId, item.id);
              const href = isDraft
                ? `/projects/${projectId}/drafts/${item.id}`
                : `/projects/${projectId}/assets`;
              const detailRoute = asRoute(href);

              return (
                <div className="row review-row" key={`${item.type}-${item.project_id}-${item.id}`}>
                  <div>
                    <div className="meta-line">
                      <span className="tag">{isDraft ? "稿件" : "内容资产"}</span>
                      <span>{item.project_name}</span>
                      <span>{statusLabel(item.status)}</span>
                    </div>
                    <Link className="title-link" href={detailRoute}>
                      <h3>{item.title}</h3>
                    </Link>
                    <small>
                      {item.latest_score == null
                        ? "还没有 AI 评分"
                        : `最近评分 ${item.latest_score} 分 ${item.latest_grade ?? ""}｜${item.latest_review_type ?? "ai"} ${item.latest_review_status ?? ""}`}
                    </small>
                  </div>
                  <div className="row-actions">
                    <Link className="button secondary" href={detailRoute}>
                      查看
                    </Link>
                    <form action={reviewAction}>
                      <SubmitButton className="button secondary" pendingText="评分中...">
                        AI 评分
                      </SubmitButton>
                    </form>
                    <form action={approveAction}>
                      <input name="comment" type="hidden" value="审核台人工确认通过。" />
                      <SubmitButton pendingText="通过中...">
                        通过
                      </SubmitButton>
                    </form>
                    <form action={rejectAction}>
                      <input name="comment" type="hidden" value="审核台人工退回修改。" />
                      <SubmitButton className="button secondary" pendingText="退回中...">
                        退回
                      </SubmitButton>
                    </form>
                    {isDraft && item.latest_score != null ? (
                      <form action={reviseAction}>
                        <SubmitButton className="button secondary" pendingText="优化复评中...">
                          优化复评
                        </SubmitButton>
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
