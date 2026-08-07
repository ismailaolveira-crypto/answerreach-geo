import Link from "next/link";
import { updatePlacementArchiveAction } from "@/app/actions";
import {
  getPlacementImpactMarkdownUrl,
  getPlacementImpactPdfUrl,
  getPlacementReviewArchive,
  getProject,
  type PlacementReviewArchiveItem
} from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ q?: string; status?: string }>;
};

const REVIEW_STATUS_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "positive", label: "正向" },
  { value: "mixed", label: "部分改善" },
  { value: "needs_optimization", label: "需优化" },
  { value: "insufficient_sample", label: "样本不足" },
  { value: "unreviewed", label: "未自动复盘" }
];

function statusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    insufficient_sample: "样本不足",
    positive: "正向",
    mixed: "部分改善",
    needs_optimization: "需优化"
  };
  return labels[status ?? ""] ?? status ?? "未生成";
}

function deltaPct(value?: number | null) {
  const normalized = value ?? 0;
  const sign = normalized > 0 ? "+" : "";
  return `${sign}${Math.round(normalized * 100)}%`;
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

function normalizeQuery(value?: string) {
  return (value ?? "").trim().toLowerCase();
}

function reviewStatus(item: PlacementReviewArchiveItem) {
  const report = item.impact?.review_report;
  return report?.evidence.review_crawl_task_id ? report.status : "unreviewed";
}

function matchesArchiveQuery(item: PlacementReviewArchiveItem, query: string) {
  if (!query) return true;
  const { placement, impact } = item;
  const report = impact?.review_report;
  const archiveMeta = report?.archive;
  const haystack = [
    placement.channel,
    placement.target_url,
    placement.notes,
    placement.status,
    placement.visibility,
    placement.delivery_status,
    placement.archive_note,
    report?.status,
    report?.conclusion,
    archiveMeta?.version,
    archiveMeta?.archive_note,
    archiveMeta?.visibility,
    archiveMeta?.delivery_status
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function filterHref(projectId: string, status: string, query: string) {
  const params = new URLSearchParams();
  if (status !== "all") params.set("status", status);
  if (query) params.set("q", query);
  const suffix = params.toString();
  return `/projects/${projectId}/review-archive${suffix ? `?${suffix}` : ""}`;
}

export default async function PlacementReviewArchivePage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const queryParams = await searchParams;
  const rawStatus = queryParams.status ?? "all";
  const selectedStatus = REVIEW_STATUS_OPTIONS.some((option) => option.value === rawStatus) ? rawStatus : "all";
  const queryText = queryParams.q?.trim() ?? "";
  const normalizedQuery = normalizeQuery(queryText);
  const [project, archive] = await Promise.all([
    getProject(id),
    getPlacementReviewArchive(id).catch(() => [])
  ]);
  const reviewedCount = archive.filter((item) => item.impact?.review_report.evidence.review_crawl_task_id).length;
  const positiveCount = archive.filter((item) => item.impact?.review_report.status === "positive").length;
  const filteredArchive = archive.filter((item) => {
    const statusMatched = selectedStatus === "all" || reviewStatus(item) === selectedStatus;
    return statusMatched && matchesArchiveQuery(item, normalizedQuery);
  });

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">复盘归档</div>
          <h1>{project.name}</h1>
          <p className="subtle">集中查看已发布投放的复盘结论、自动采集证据和客户交付导出。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}/sources`}>
          信源与投放
        </Link>
        <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
          客户交付包
        </Link>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>已发布投放</span>
          <strong>{archive.length}</strong>
        </div>
        <div className="panel metric">
          <span>当前筛选</span>
          <strong>{filteredArchive.length}</strong>
        </div>
        <div className="panel metric">
          <span>已自动复盘</span>
          <strong>{reviewedCount}</strong>
        </div>
        <div className="panel metric">
          <span>正向复盘</span>
          <strong>{positiveCount}</strong>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>筛选复盘归档</h2>
            <p className="subtle">按复盘状态和关键词定位已交付报告，关键词会匹配渠道、链接、备注、结论和归档版本。</p>
          </div>
          {(selectedStatus !== "all" || queryText) && (
            <Link className="button secondary" href={`/projects/${id}/review-archive`}>
              清除
            </Link>
          )}
        </div>
        <form className="form inline-form" action={`/projects/${id}/review-archive`}>
          <div className="field">
            <label htmlFor="q">关键词</label>
            <input id="q" name="q" defaultValue={queryText} placeholder="搜索渠道、链接、备注、结论或版本" />
          </div>
          <div className="field">
            <label htmlFor="status">复盘状态</label>
            <select id="status" name="status" defaultValue={selectedStatus}>
              {REVIEW_STATUS_OPTIONS.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <button className="button" type="submit">
            搜索
          </button>
        </form>
        <div className="filter-links">
          {REVIEW_STATUS_OPTIONS.map((option) => (
            <a
              className={`tag ${selectedStatus === option.value ? "active" : ""}`}
              href={filterHref(id, option.value, queryText)}
              key={option.value}
            >
              {option.label}
            </a>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>复盘报告归档</h2>
        <div className="list">
          {archive.length === 0 ? (
            <p className="subtle">暂无已发布投放。投放发布后会进入复盘归档。</p>
          ) : filteredArchive.length === 0 ? (
            <p className="subtle">没有匹配的复盘记录。调整关键词或状态后再查看。</p>
          ) : (
            filteredArchive.map(({ placement, impact }) => {
              const report = impact?.review_report;
              const deltas = report?.metric_deltas ?? {};
              const evidence = report?.evidence ?? {};
              const archiveMeta = report?.archive ?? {};
              return (
                <div className="row review-row" key={placement.id}>
                  <div>
                    <div className="meta-line">
                      <span className="tag">{statusLabel(report?.status)}</span>
                      <span>{archiveMeta.version ?? `PR-${placement.id}-v1`}</span>
                      <span>{placement.channel}</span>
                      <span>{placement.published_at ?? "未记录发布时间"}</span>
                    </div>
                    <Link href={`/projects/${id}/placements/${placement.id}/impact`}>
                      <h3>{report?.conclusion ?? placement.notes ?? "待生成复盘结论"}</h3>
                    </Link>
                    <small>
                      备注 {archiveMeta.archive_note ?? placement.notes ?? "暂无"}｜
                      {visibilityLabel(archiveMeta.visibility ?? placement.visibility)}｜
                      {deliveryStatusLabel(archiveMeta.delivery_status ?? placement.delivery_status)}｜
                      样本变化 {deltas.sample_size_delta ?? 0}｜提及率 {deltaPct(deltas.company_mention_rate_delta)}｜
                      推荐率 {deltaPct(deltas.company_recommendation_rate_delta)}｜
                      复盘任务 {evidence.review_crawl_task_id ?? "暂无"} {evidence.review_task_status ?? ""}
                    </small>
                    <form className="archive-inline-form" action={updatePlacementArchiveAction.bind(null, id, placement.id)}>
                      <input
                        name="archive_note"
                        defaultValue={placement.archive_note ?? placement.notes ?? ""}
                        placeholder="归档备注"
                      />
                      <select name="visibility" defaultValue={placement.visibility ?? "internal"}>
                        <option value="internal">内部可见</option>
                        <option value="customer_visible">客户可见</option>
                      </select>
                      <select name="delivery_status" defaultValue={placement.delivery_status ?? "not_delivered"}>
                        <option value="not_delivered">未交付</option>
                        <option value="ready">待交付</option>
                        <option value="delivered">已交付</option>
                        <option value="accepted">已确认</option>
                      </select>
                      <button className="button secondary" type="submit">
                        保存
                      </button>
                    </form>
                  </div>
                  <div className="row-actions">
                    <Link className="button secondary" href={`/projects/${id}/placements/${placement.id}/impact`}>
                      查看
                    </Link>
                    <a className="button secondary" href={getPlacementImpactMarkdownUrl(id, String(placement.id))}>
                      Markdown
                    </a>
                    <a className="button secondary" href={getPlacementImpactPdfUrl(id, String(placement.id))}>
                      PDF
                    </a>
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
