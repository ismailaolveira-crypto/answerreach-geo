import Link from "next/link";
import { updatePlacementStatusAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getArticleDrafts, getContentAssets, getPlacements, getProject, type PlacementRecord } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
};

function dateKey(placement: PlacementRecord) {
  const raw = placement.planned_at ?? placement.published_at ?? placement.created_at ?? "";
  if (!raw) return "未排期";
  return raw.slice(0, 10);
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    planned: "待投放",
    published: "已发布",
    paused: "已暂停"
  };
  return labels[status] ?? status;
}

export default async function ContentCalendarPage({ params }: PageProps) {
  const { id } = await params;
  const [project, placements, assets, drafts] = await Promise.all([
    getProject(id),
    getPlacements(id).catch(() => []),
    getContentAssets(id).catch(() => []),
    getArticleDrafts(id).catch(() => [])
  ]);
  const assetMap = new Map(assets.map((asset) => [asset.id, asset.title]));
  const draftMap = new Map(drafts.map((draft) => [draft.id, draft.title]));
  const plannedCount = placements.filter((item) => item.status === "planned").length;
  const publishedCount = placements.filter((item) => item.status === "published").length;
  const pausedCount = placements.filter((item) => item.status === "paused").length;
  const grouped = placements.reduce<Record<string, PlacementRecord[]>>((acc, placement) => {
    const key = dateKey(placement);
    acc[key] = acc[key] ? [...acc[key], placement] : [placement];
    return acc;
  }, {});
  const days = Object.keys(grouped).sort((a, b) => {
    if (a === "未排期") return 1;
    if (b === "未排期") return -1;
    return a.localeCompare(b);
  });

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">内容日历</div>
          <h1>{project.name}</h1>
          <p className="subtle">按排期查看投放计划、发布状态和后续复盘入口。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}/sources`}>
          信源与投放
        </Link>
        <Link className="button secondary" href={`/projects/${id}/review-archive`}>
          复盘归档
        </Link>
      </div>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>待投放</span>
          <strong>{plannedCount}</strong>
        </div>
        <div className="panel metric">
          <span>已发布</span>
          <strong>{publishedCount}</strong>
        </div>
        <div className="panel metric">
          <span>已暂停</span>
          <strong>{pausedCount}</strong>
        </div>
      </section>

      <section className="panel">
        <h2>投放排期</h2>
        <div className="list">
          {days.length === 0 ? (
            <p className="subtle">暂无投放记录。先在信源与投放页把已通过内容加入计划。</p>
          ) : (
            days.map((day) => (
              <div className="calendar-day" key={day}>
                <div className="calendar-date">{day}</div>
                <div className="list">
                  {grouped[day].map((item) => {
                    const title =
                      (item.article_draft_id ? draftMap.get(item.article_draft_id) : null) ??
                      (item.content_asset_id ? assetMap.get(item.content_asset_id) : null) ??
                      item.channel;
                    return (
                      <div className="row" key={item.id}>
                        <div>
                          <div className="meta-line">
                            <span className="tag">{statusLabel(item.status)}</span>
                            <span>{item.channel}</span>
                          </div>
                          <Link href={`/projects/${id}/placements/${item.id}/impact`}>
                            <h3>{title}</h3>
                          </Link>
                          <small>
                            {item.target_url ?? item.notes ?? "待补充目标 URL 或投放说明"}｜{item.visibility}｜{item.delivery_status}
                          </small>
                        </div>
                        <div className="row-actions">
                          {item.status === "published" ? (
                            <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
                              交付包
                            </Link>
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
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
