import Link from "next/link";
import type { Route } from "next";
import { createPlacementAction, updatePlacementStatusAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getArticleDrafts, getContentAssets, getPlacements, getProject, type PlacementRecord } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
};

function asRoute(value: string) {
  return value as Route;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    planned: "待投放",
    published: "已发布",
    paused: "已暂停"
  };
  return labels[status] ?? status;
}

function deliveryStatusLabel(status: string) {
  const labels: Record<string, string> = {
    not_delivered: "未交付",
    ready: "待交付",
    delivered: "已交付",
    accepted: "客户确认"
  };
  return labels[status] ?? status;
}

function placementTitle(item: PlacementRecord, draftMap: Map<number, string>, assetMap: Map<number, string>) {
  return (
    (item.article_draft_id ? draftMap.get(item.article_draft_id) : null) ??
    (item.content_asset_id ? assetMap.get(item.content_asset_id) : null) ??
    item.channel
  );
}

export default async function ProjectPlacementsPage({ params }: PageProps) {
  const { id } = await params;
  const [project, placements, assets, drafts] = await Promise.all([
    getProject(id),
    getPlacements(id).catch(() => []),
    getContentAssets(id).catch(() => []),
    getArticleDrafts(id).catch(() => [])
  ]);
  const createPlacement = createPlacementAction.bind(null, id);
  const assetMap = new Map(assets.map((asset) => [asset.id, asset.title]));
  const draftMap = new Map(drafts.map((draft) => [draft.id, draft.title]));
  const placedAssetIds = new Set(placements.map((item) => item.content_asset_id).filter(Boolean));
  const placedDraftIds = new Set(placements.map((item) => item.article_draft_id).filter(Boolean));
  const approvedAssets = assets.filter((asset) => asset.status === "approved" && !placedAssetIds.has(asset.id));
  const approvedDrafts = drafts.filter((draft) => draft.status === "approved" && !placedDraftIds.has(draft.id));
  const planned = placements.filter((item) => item.status === "planned");
  const published = placements.filter((item) => item.status === "published");
  const paused = placements.filter((item) => item.status === "paused");
  const customerVisible = placements.filter((item) => item.visibility === "customer_visible");
  const accepted = placements.filter((item) => item.delivery_status === "accepted");

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">投放计划</div>
          <h1>{project.name} 投放运营</h1>
          <p className="subtle">集中管理内容投放渠道、排期、发布、复盘和客户交付状态。</p>
        </div>
        <Link className="button secondary" href={asRoute(`/projects/${id}`)}>
          返回项目
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/calendar`)}>
          内容日历
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/delivery-package`)}>
          客户交付包
        </Link>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>待投放</span>
          <strong>{planned.length}</strong>
        </div>
        <div className="panel metric">
          <span>已发布</span>
          <strong>{published.length}</strong>
        </div>
        <div className="panel metric">
          <span>客户可见</span>
          <strong>{customerVisible.length}</strong>
        </div>
        <div className="panel metric">
          <span>客户确认</span>
          <strong>{accepted.length}</strong>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>新增投放记录</h2>
          <form action={createPlacement} className="form">
            <div className="grid cols-2">
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
            </div>
            <div className="grid cols-2">
              <div className="field">
                <label>投放渠道</label>
                <input name="channel" placeholder="官网 / 公众号 / 媒体 / 百科 / 行业报告" required />
              </div>
              <div className="field">
                <label>目标 URL</label>
                <input name="target_url" placeholder="https://example.com/article" />
              </div>
            </div>
            <div className="grid cols-2">
              <div className="field">
                <label>状态</label>
                <select name="status" defaultValue="planned">
                  <option value="planned">planned</option>
                  <option value="published">published</option>
                  <option value="paused">paused</option>
                </select>
              </div>
              <div className="field">
                <label>说明</label>
                <input name="notes" placeholder="投放目的、目标问题或优化动作" />
              </div>
            </div>
            <SubmitButton pendingText="保存中...">保存投放</SubmitButton>
          </form>
        </div>

        <div className="panel">
          <h2>待加入计划内容</h2>
          <div className="list">
            {approvedAssets.length + approvedDrafts.length === 0 ? (
              <p className="subtle">暂无新的已通过内容。稿件或内容资产人工审核通过后会出现在这里。</p>
            ) : (
              <>
                {approvedDrafts.slice(0, 4).map((draft) => (
                  <div className="row" key={`draft-${draft.id}`}>
                    <div>
                      <div className="meta-line">
                        <span className="tag">稿件</span>
                        <span>已通过</span>
                      </div>
                      <Link href={asRoute(`/projects/${id}/drafts/${draft.id}`)}>
                        <h3>{draft.title}</h3>
                      </Link>
                    </div>
                    <form action={createPlacement}>
                      <input name="article_draft_id" type="hidden" value={draft.id} />
                      <input name="channel" type="hidden" value="待定渠道" />
                      <input name="status" type="hidden" value="planned" />
                      <input name="notes" type="hidden" value="人工审核通过后加入投放计划。" />
                      <SubmitButton className="button secondary" pendingText="加入中...">加入计划</SubmitButton>
                    </form>
                  </div>
                ))}
                {approvedAssets.slice(0, 4).map((asset) => (
                  <div className="row" key={`asset-${asset.id}`}>
                    <div>
                      <div className="meta-line">
                        <span className="tag">内容资产</span>
                        <span>已通过</span>
                      </div>
                      <h3>{asset.title}</h3>
                      <small>{asset.source_url ?? "待安排目标 URL"}</small>
                    </div>
                    <form action={createPlacement}>
                      <input name="content_asset_id" type="hidden" value={asset.id} />
                      <input name="channel" type="hidden" value={asset.publish_channel ?? "待定渠道"} />
                      <input name="target_url" type="hidden" value={asset.source_url ?? ""} />
                      <input name="status" type="hidden" value="planned" />
                      <input name="notes" type="hidden" value="人工审核通过后加入投放计划。" />
                      <SubmitButton className="button secondary" pendingText="加入中...">加入计划</SubmitButton>
                    </form>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>投放记录</h2>
            <p className="subtle">发布后会自动标记客户可见和待交付，并进入投放复盘与客户交付包。</p>
          </div>
          <span className="tag">{placements.length} 条</span>
        </div>
        <div className="list">
          {placements.length === 0 ? (
            <p className="subtle">暂无投放记录。先把已通过稿件或内容资产加入计划。</p>
          ) : (
            placements.map((item) => (
              <div className="row" key={item.id}>
                <div>
                  <div className="meta-line">
                    <span className="tag">{statusLabel(item.status)}</span>
                    <span>{deliveryStatusLabel(item.delivery_status)}</span>
                    <span>{item.visibility === "customer_visible" ? "客户可见" : "内部"}</span>
                  </div>
                  <Link href={asRoute(`/projects/${id}/placements/${item.id}/impact`)}>
                    <h3>{placementTitle(item, draftMap, assetMap)}</h3>
                  </Link>
                  <small>
                    {item.channel}｜{item.target_url ?? item.notes ?? "未设置 URL 或说明"}
                  </small>
                </div>
                <div className="row-actions">
                  {item.status !== "published" ? (
                    <form action={updatePlacementStatusAction.bind(null, id, item.id, "published")}>
                      <SubmitButton pendingText="发布中...">发布并交付</SubmitButton>
                    </form>
                  ) : (
                    <Link className="button secondary" href={asRoute(`/projects/${id}/placements/${item.id}/impact`)}>
                      复盘
                    </Link>
                  )}
                  {item.status !== "paused" ? (
                    <form action={updatePlacementStatusAction.bind(null, id, item.id, "paused")}>
                      <SubmitButton className="button secondary" pendingText="暂停中...">暂停</SubmitButton>
                    </form>
                  ) : (
                    <form action={updatePlacementStatusAction.bind(null, id, item.id, "planned")}>
                      <SubmitButton className="button secondary" pendingText="恢复中...">恢复计划</SubmitButton>
                    </form>
                  )}
                  {item.visibility === "customer_visible" ? (
                    <Link className="button secondary" href={asRoute(`/projects/${id}/delivery-package`)}>
                      交付包
                    </Link>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </div>
        {paused.length > 0 ? <p className="subtle">已暂停 {paused.length} 条，可在列表中恢复为 planned。</p> : null}
      </section>
    </div>
  );
}
