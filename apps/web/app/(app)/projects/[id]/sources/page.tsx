import Link from "next/link";
import { createPlacementAction, updatePlacementStatusAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getArticleDrafts, getContentAssets, getPlacements, getProject, getSourceInsights } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
};

function readinessLabel(value: string) {
  const labels: Record<string, string> = {
    excellent: "优秀",
    good: "良好",
    needs_optimization: "待优化",
    poor: "较差",
    unknown: "未知"
  };
  return labels[value] ?? value;
}

export default async function SourcesPage({ params }: PageProps) {
  const { id } = await params;
  const [project, sources, placements, assets, drafts] = await Promise.all([
    getProject(id),
    getSourceInsights(id).catch(() => []),
    getPlacements(id).catch(() => []),
    getContentAssets(id).catch(() => []),
    getArticleDrafts(id).catch(() => [])
  ]);
  const createPlacement = createPlacementAction.bind(null, id);
  const placedAssetIds = new Set(placements.map((item) => item.content_asset_id).filter(Boolean));
  const placedDraftIds = new Set(placements.map((item) => item.article_draft_id).filter(Boolean));
  const approvedAssets = assets.filter((asset) => asset.status === "approved" && !placedAssetIds.has(asset.id));
  const approvedDrafts = drafts.filter((draft) => draft.status === "approved" && !placedDraftIds.has(draft.id));
  const pendingPlacementCount = placements.filter((item) => item.status === "planned").length;

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">信源与投放</div>
          <h1>{project.name}</h1>
          <p className="subtle">分析 AI 答案中的信源线索，并记录企业内容投放状态。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
        <Link className="button secondary" href={`/projects/${id}/calendar`}>
          内容日历
        </Link>
        <Link className="button secondary" href={`/projects/${id}/review-archive`}>
          复盘归档
        </Link>
      </div>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>识别信源</span>
          <strong>{sources.length}</strong>
        </div>
        <div className="panel metric">
          <span>投放记录</span>
          <strong>{placements.length}</strong>
        </div>
        <div className="panel metric">
          <span>待投放</span>
          <strong>{approvedAssets.length + approvedDrafts.length + pendingPlacementCount}</strong>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>新增投放记录</h2>
          <form action={createPlacement} className="form">
            <div className="field">
              <label>绑定内容资产</label>
              <select name="content_asset_id" defaultValue="">
                <option value="">不绑定</option>
                {assets.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.title}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>绑定审核稿件</label>
              <select name="article_draft_id" defaultValue="">
                <option value="">不绑定</option>
                {drafts
                  .filter((draft) => draft.status === "approved")
                  .map((draft) => (
                    <option key={draft.id} value={draft.id}>
                      {draft.title}
                    </option>
                  ))}
              </select>
            </div>
            <div className="field">
              <label>投放渠道</label>
              <input name="channel" placeholder="官网 / 公众号 / 媒体 / 百科 / 行业报告" required />
            </div>
            <div className="field">
              <label>目标 URL</label>
              <input name="target_url" placeholder="https://example.com/article" />
            </div>
            <div className="field">
              <label>状态</label>
              <select name="status" defaultValue="planned">
                <option value="planned">planned</option>
                <option value="published">published</option>
                <option value="paused">paused</option>
              </select>
            </div>
            <div className="field">
              <label>备注</label>
              <textarea name="notes" placeholder="记录投放目的、目标问题或优化动作。" />
            </div>
            <button className="button" type="submit">
              保存投放
            </button>
          </form>
        </div>

        <div className="panel">
          <h2>投放记录</h2>
          <div className="list">
            {placements.length === 0 ? (
              <p className="subtle">暂无投放记录。</p>
            ) : (
              placements.map((item) => (
                <div className="row" key={item.id}>
                  <div>
                    <Link href={`/projects/${id}/placements/${item.id}/impact`}>
                      <h3>{item.channel}</h3>
                    </Link>
                    <small>
                      {item.target_url ?? "未设置 URL"}｜{item.visibility}｜{item.delivery_status}
                    </small>
                  </div>
                  <div className="row-actions">
                    <span className="tag">{item.status}</span>
                    {item.status === "published" ? (
                      <>
                        <Link className="button secondary" href={`/projects/${id}/placements/${item.id}/impact`}>
                          复盘
                        </Link>
                        <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
                          交付包
                        </Link>
                      </>
                    ) : null}
                    {item.status !== "published" ? (
                      <form action={updatePlacementStatusAction.bind(null, id, item.id, "published")}>
                        <SubmitButton pendingText="发布中...">发布并交付</SubmitButton>
                      </form>
                    ) : null}
                    {item.status !== "paused" ? (
                      <form action={updatePlacementStatusAction.bind(null, id, item.id, "paused")}>
                        <SubmitButton className="button secondary" pendingText="暂停中...">暂停</SubmitButton>
                      </form>
                    ) : (
                      <form action={updatePlacementStatusAction.bind(null, id, item.id, "planned")}>
                        <SubmitButton className="button secondary" pendingText="恢复中...">恢复计划</SubmitButton>
                      </form>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>待投放内容</h2>
        <div className="list">
          {approvedAssets.length + approvedDrafts.length === 0 ? (
            <p className="subtle">暂无新的已通过内容。人工审核通过后，可在这里加入投放计划。</p>
          ) : (
            <>
              {approvedDrafts.map((draft) => (
                <div className="row" key={`draft-${draft.id}`}>
                  <div>
                    <div className="meta-line">
                      <span className="tag">稿件</span>
                      <span>已通过</span>
                    </div>
                    <Link href={`/projects/${id}/drafts/${draft.id}`}>
                      <h3>{draft.title}</h3>
                    </Link>
                    <small>{draft.summary ?? "待安排投放渠道和目标 URL"}</small>
                  </div>
                  <form action={createPlacement}>
                    <input name="article_draft_id" type="hidden" value={draft.id} />
                    <input name="channel" type="hidden" value="待定渠道" />
                    <input name="status" type="hidden" value="planned" />
                    <input name="notes" type="hidden" value="人工审核通过后加入投放计划。" />
                    <button className="button" type="submit">
                      加入计划
                    </button>
                  </form>
                </div>
              ))}
              {approvedAssets.map((asset) => (
                <div className="row" key={`asset-${asset.id}`}>
                  <div>
                    <div className="meta-line">
                      <span className="tag">内容资产</span>
                      <span>已通过</span>
                    </div>
                    <h3>{asset.title}</h3>
                    <small>{asset.source_url ?? "待安排投放渠道和目标 URL"}</small>
                  </div>
                  <form action={createPlacement}>
                    <input name="content_asset_id" type="hidden" value={asset.id} />
                    <input name="channel" type="hidden" value={asset.publish_channel ?? "待定渠道"} />
                    <input name="target_url" type="hidden" value={asset.source_url ?? ""} />
                    <input name="status" type="hidden" value="planned" />
                    <input name="notes" type="hidden" value="人工审核通过后加入投放计划。" />
                    <button className="button" type="submit">
                      加入计划
                    </button>
                  </form>
                </div>
              ))}
            </>
          )}
        </div>
      </section>

      <section className="panel">
        <h2>AI 信源洞察</h2>
        <div className="list">
          {sources.length === 0 ? (
            <p className="subtle">暂无明确 URL 信源。接入真实联网搜索 Provider 后，这里会显示更多来源证据。</p>
          ) : (
            sources.map((source) => (
              <div className="row" key={`${source.source_domain}-${source.source_url}`}>
                <div>
                  <Link
                    href={`/projects/${id}/sources/detail?${
                      source.source_url
                        ? `source_url=${encodeURIComponent(source.source_url)}`
                        : `source_domain=${encodeURIComponent(source.source_domain ?? "")}`
                    }`}
                  >
                    <h3>{source.source_domain ?? source.source_url ?? "未知来源"}</h3>
                  </Link>
                  <small>
                    出现 {source.appearances} 次｜投放 {source.placement_count} 次｜已发布{" "}
                    {source.published_placement_count} 次｜{source.placement_frequency_label}
                  </small>
                  <small>
                    可抓取 {source.crawlable_score}（{readinessLabel(source.crawlability_status)}）｜AI 适配{" "}
                    {source.ai_readiness_score}（{readinessLabel(source.ai_readiness_status)}）
                  </small>
                </div>
                <span className="tag">
                  {source.is_placed ? "已投放" : source.has_content_asset ? "有资产" : "缺口"}
                </span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
