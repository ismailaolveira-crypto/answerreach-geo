import Link from "next/link";
import {
  bulkCreatePlacementsFromAssetsAction,
  bulkReviewContentAssetsAction,
  createContentAssetAction,
  createContentAssetRemediationGoalsAction,
  decideContentAssetReviewAction,
  reviewContentAssetAction
} from "@/app/actions";
import { getContentAssetReviews, getContentAssets, getProject } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ bulk_scored?: string; created_asset?: string; remediation_goals?: string }>;
};

export default async function ContentAssetsPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const query = await searchParams;
  const [project, assets] = await Promise.all([getProject(id), getContentAssets(id).catch(() => [])]);
  const createAsset = createContentAssetAction.bind(null, id, project.company_id);
  const bulkReviewAssets = bulkReviewContentAssetsAction.bind(null, id);
  const bulkCreatePlacements = bulkCreatePlacementsFromAssetsAction.bind(null, id);
  const createRemediationGoals = createContentAssetRemediationGoalsAction.bind(null, id);
  const reviewPairs = await Promise.all(
    assets.map(async (asset) => ({
      assetId: asset.id,
      reviews: await getContentAssetReviews(id, asset.id).catch(() => [])
    }))
  );
  const reviewMap = new Map(reviewPairs.map((item) => [item.assetId, item.reviews]));
  const missingReviewCount = reviewPairs.filter((item) => item.reviews.length === 0).length;
  const promotableAssetCount = assets.filter((asset) => {
    const latestReview = reviewMap.get(asset.id)?.[0];
    return asset.status === "approved" || Number(latestReview?.total_score ?? 0) >= 85;
  }).length;
  const bulkScored = Number(query.bulk_scored ?? 0);
  const createdAssetId = Number(query.created_asset ?? 0);
  const remediationGoals = Number(query.remediation_goals ?? 0);
  const remediationCandidateCount = assets.filter((asset) => {
    const latestReview = reviewMap.get(asset.id)?.[0];
    return !latestReview || asset.status === "needs_revision" || asset.status === "rejected" || Number(latestReview.total_score ?? 0) < 85;
  }).length;

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">内容资产库</div>
          <h1>{project.name}</h1>
          <p className="subtle">沉淀官网、媒体、公众号、FAQ、案例等可被 AI 采信的内容资产。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
      </div>

      {(bulkScored > 0 || createdAssetId > 0 || remediationGoals > 0) ? (
        <section className="panel">
          <h2>处理完成</h2>
          <p className="subtle">
            {bulkScored > 0 ? `本次已为 ${bulkScored} 条内容资产生成 AI 评分。` : ""}
            {createdAssetId > 0 ? ` 已创建内容资产 #${createdAssetId}。` : ""}
            {remediationGoals > 0 ? ` 已创建 ${remediationGoals} 个内容整改阶段目标。` : ""}
          </p>
        </section>
      ) : null}

      <section className="grid cols-3">
        <div className="panel metric">
          <span>内容资产</span>
          <strong>{assets.length}</strong>
        </div>
        <div className="panel metric">
          <span>待 AI 评分</span>
          <strong>{missingReviewCount}</strong>
        </div>
        <div className="panel metric">
          <span>可推进投放</span>
          <strong>{promotableAssetCount}</strong>
        </div>
        <div className="panel metric">
          <span>待整改</span>
          <strong>{remediationCandidateCount}</strong>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>批量运营</h2>
            <p className="subtle">先批量补齐历史内容评分，再把已通过或高分内容资产推进到 planned 投放计划。</p>
          </div>
          <div className="row-actions">
            <form action={bulkReviewAssets}>
              <button className="button secondary" disabled={missingReviewCount === 0} type="submit">
                批量 AI 评分
              </button>
            </form>
            <form action={bulkCreatePlacements}>
              <button className="button" disabled={promotableAssetCount === 0} type="submit">
                批量加入投放
              </button>
            </form>
            <form action={createRemediationGoals}>
              <button className="button secondary" disabled={remediationCandidateCount === 0} type="submit">
                生成整改目标
              </button>
            </form>
          </div>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>新增内容资产</h2>
          <form action={createAsset} className="form">
            <div className="field">
              <label>标题</label>
              <input name="title" placeholder="例如：企业如何选择网络安全培训服务商？" required />
            </div>
            <div className="field">
              <label>内容类型</label>
              <select name="content_type" defaultValue="article">
                <option value="article">文章</option>
                <option value="faq">FAQ</option>
                <option value="case">案例</option>
                <option value="solution">解决方案页</option>
                <option value="press">媒体稿</option>
              </select>
            </div>
            <div className="field">
              <label>来源 URL</label>
              <input name="source_url" placeholder="https://example.com/article" />
            </div>
            <div className="field">
              <label>发布渠道</label>
              <input name="publish_channel" placeholder="官网 / 公众号 / 媒体 / 百科" />
            </div>
            <div className="field">
              <label>正文或摘要</label>
              <textarea name="body_text" placeholder="粘贴历史稿件正文，后续会用于 GEO 评分。" />
            </div>
            <button className="button" type="submit">
              保存资产
            </button>
          </form>
        </div>

        <div className="panel">
          <h2>资产列表</h2>
          <div className="list">
            {assets.length === 0 ? (
              <p className="subtle">暂无内容资产。</p>
            ) : (
              assets.map((asset) => (
                <div className="row" key={asset.id}>
                  <div>
                    <h3>{asset.title}</h3>
                    <small>
                      {asset.content_type}｜{asset.publish_channel ?? "未设置渠道"}｜{asset.status}
                      {reviewMap.get(asset.id)?.[0]
                        ? `｜评分 ${reviewMap.get(asset.id)?.[0].total_score} ${reviewMap.get(asset.id)?.[0].grade}`
                        : ""}
                    </small>
                  </div>
                  <div className="row-actions">
                    <form action={reviewContentAssetAction.bind(null, id, asset.id)}>
                      <button className="button secondary" type="submit">
                        评分
                      </button>
                    </form>
                    <form action={decideContentAssetReviewAction.bind(null, id, asset.id, "approved")}>
                      <input name="comment" type="hidden" value="人工确认可进入投放计划。" />
                      <button className="button" type="submit">
                        通过
                      </button>
                    </form>
                    <form action={decideContentAssetReviewAction.bind(null, id, asset.id, "rejected")}>
                      <input name="comment" type="hidden" value="人工退回修改。" />
                      <button className="button secondary" type="submit">
                        退回
                      </button>
                    </form>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
