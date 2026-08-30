import Link from "next/link";
import type { Route } from "next";
import {
  createDeliveryShareAction,
  revokeDeliveryShareAction,
  rotateDeliveryConfirmationTokenAction
} from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import {
  getDeliveryAccessLogs,
  getDeliveryPackageMarkdownUrl,
  getDeliveryPackagePdfUrl,
  getDeliveryShares,
  getAlerts,
  getPlacementImpactMarkdownUrl,
  getPlacementImpactPdfUrl,
  getPlacementReviewArchive,
  getProject,
  type PlacementReviewArchiveItem
} from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ share?: string; revoked?: string; confirmation_rotated?: string }>;
};

const DELIVERABLE_STATUSES = new Set(["ready", "delivered", "accepted"]);

function statusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    insufficient_sample: "样本不足",
    positive: "正向",
    mixed: "部分改善",
    needs_optimization: "需优化"
  };
  return labels[status ?? ""] ?? status ?? "未生成";
}

function deliveryStatusLabel(value?: string | null) {
  const labels: Record<string, string> = {
    ready: "待交付",
    delivered: "已交付",
    accepted: "已确认"
  };
  return labels[value ?? ""] ?? "待交付";
}

function deltaPct(value?: number | null) {
  const normalized = value ?? 0;
  const sign = normalized > 0 ? "+" : "";
  return `${sign}${Math.round(normalized * 100)}%`;
}

function accessEventLabel(value: string) {
  const labels: Record<string, string> = {
    view_package: "打开交付包",
    export_markdown: "下载 Markdown",
    export_pdf: "下载 PDF",
    confirm_report: "确认阅读"
  };
  return labels[value] ?? value;
}

function isCustomerDeliverable(item: PlacementReviewArchiveItem) {
  const archiveMeta = item.impact?.review_report.archive;
  const visibility = archiveMeta?.visibility ?? item.placement.visibility;
  const deliveryStatus = archiveMeta?.delivery_status ?? item.placement.delivery_status;
  return visibility === "customer_visible" && DELIVERABLE_STATUSES.has(deliveryStatus ?? "");
}

function asRoute(value: string) {
  return value as Route;
}

export default async function DeliveryPackagePage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const queryParams = await searchParams;
  const [project, archive, shares, accessLogs, openFollowUps, acknowledgedFollowUps] = await Promise.all([
    getProject(id),
    getPlacementReviewArchive(id).catch(() => []),
    getDeliveryShares(id).catch(() => []),
    getDeliveryAccessLogs(id).catch(() => []),
    getAlerts("open", { projectId: id, limit: 50 }).catch(() => []),
    getAlerts("acknowledged", { projectId: id, limit: 50 }).catch(() => [])
  ]);
  const createShare = createDeliveryShareAction.bind(null, id);
  const packageMarkdownUrl = getDeliveryPackageMarkdownUrl(id);
  const packagePdfUrl = getDeliveryPackagePdfUrl(id);
  const deliverables = archive.filter(isCustomerDeliverable);
  const deliveredCount = deliverables.filter(({ placement, impact }) => {
    const status = impact?.review_report.archive?.delivery_status ?? placement.delivery_status;
    return status === "delivered" || status === "accepted";
  }).length;
  const acceptedCount = deliverables.filter(({ placement, impact }) => {
    const status = impact?.review_report.archive?.delivery_status ?? placement.delivery_status;
    return status === "accepted";
  }).length;
  const followUps = [...openFollowUps, ...acknowledgedFollowUps].filter(
    (alert) => alert.alert_type === "delivery.confirmed"
  );
  const activeShares = shares.filter((share) => share.status === "active");
  const latestActiveShare = activeShares[0];
  const publicSharePath = latestActiveShare ? `/share/delivery/${latestActiveShare.token}` : null;

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">客户交付包</div>
          <h1>{project.name}</h1>
          <p className="subtle">面向客户交付的 GEO 投放复盘清单，只展示已标记客户可见并进入交付流程的报告。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}/review-archive`}>
          复盘归档
        </Link>
        <a className="button secondary" href={packageMarkdownUrl}>
          导出汇总 Markdown
        </a>
        <a className="button secondary" href={packagePdfUrl}>
          导出汇总 PDF
        </a>
      </div>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>可交付报告</span>
          <strong>{deliverables.length}</strong>
        </div>
        <div className="panel metric">
          <span>已交付</span>
          <strong>{deliveredCount}</strong>
        </div>
        <div className="panel metric">
          <span>客户已确认</span>
          <strong>{acceptedCount}</strong>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>交付状态</h2>
            <p className="subtle">
              {deliverables.length === 0
                ? "暂无客户可见报告，先发布投放并进入待交付状态。"
                : latestActiveShare
                  ? "只读链接已就绪。如需让对方验收，还要通过另一渠道发送专用验收码。"
                  : "已有可交付报告，但还没有有效分享链接。"}
            </p>
          </div>
          <span className={deliverables.length > 0 && latestActiveShare ? "tag active" : "tag"}>
            {deliverables.length > 0 && latestActiveShare ? "ready" : "todo"}
          </span>
        </div>
        {publicSharePath ? (
          <div className="row">
            <div>
              <h3>外部只读链接</h3>
              <small>{publicSharePath}</small>
              <small>
                专用验收码：{latestActiveShare?.confirmation_token ?? "尚未生成，请在下方重新生成"}
              </small>
            </div>
            <Link className="button" href={asRoute(publicSharePath)}>
              打开客户视图
            </Link>
          </div>
        ) : deliverables.length > 0 ? (
          <form className="form inline-form" action={createShare}>
            <input name="name" type="hidden" value={`${project.name} 客户交付包`} />
            <SubmitButton pendingText="生成分享中...">一键生成客户分享链接</SubmitButton>
          </form>
        ) : (
          <Link className="button secondary" href={`/projects/${id}/sources`}>
            去发布投放
          </Link>
        )}
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>待跟进事项</h2>
            <p className="subtle">客户确认阅读后生成的内部跟进提醒，处理完成后可在系统告警中解决。</p>
          </div>
          <Link className="button secondary" href="/admin/alerts?status=open">
            系统告警
          </Link>
        </div>
        <div className="list">
          {followUps.length === 0 ? (
            <p className="subtle">暂无待跟进确认。</p>
          ) : (
            followUps.map((alert) => (
              <div className="row" key={alert.id}>
                <div>
                  <div className="meta-line">
                    <span className="tag">{alert.status === "open" ? "未处理" : "已确认"}</span>
                    <span>{alert.created_at}</span>
                    {typeof alert.detail_json.placement_id === "number" ? (
                      <span>报告 {alert.detail_json.placement_id}</span>
                    ) : null}
                    {typeof alert.detail_json.actor_name === "string" ? <span>{alert.detail_json.actor_name}</span> : null}
                  </div>
                  <h3>{alert.title}</h3>
                  <small>{alert.message}</small>
                </div>
                <div className="row-actions">
                  {typeof alert.detail_json.placement_id === "number" ? (
                    <Link
                      className="button secondary"
                      href={`/projects/${id}/placements/${alert.detail_json.placement_id}/impact`}
                    >
                      复盘报告
                    </Link>
                  ) : null}
                  <Link className="button secondary" href="/admin/alerts?status=open">
                    处理
                  </Link>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <h2>访问与确认记录</h2>
        <div className="list">
          {accessLogs.length === 0 ? (
            <p className="subtle">暂无客户访问记录。</p>
          ) : (
            accessLogs.slice(0, 12).map((log) => (
              <div className="row" key={log.id}>
                <div>
                  <div className="meta-line">
                    <span className="tag">{accessEventLabel(log.event_type)}</span>
                    <span>{log.created_at}</span>
                    <span>{log.placement_id ? `报告 ${log.placement_id}` : "交付包"}</span>
                    {log.actor_name ? <span>{log.actor_name}</span> : null}
                  </div>
                  <small>{log.comment ?? "暂无备注"}</small>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>分享链接</h2>
            <p className="subtle">生成外部只读链接后，客户可通过 token 查看当前客户可见的交付报告。</p>
          </div>
        </div>
        {queryParams.share ? (
          <div className="notice success">
            新分享链接已生成：
            <Link className="inline-link" href={`/share/delivery/${queryParams.share}`}>
              /share/delivery/{queryParams.share}
            </Link>
          </div>
        ) : null}
        {queryParams.revoked ? (
          <div className="notice warning">
            分享链接 #{queryParams.revoked} 已撤销，客户将无法继续通过该链接访问交付包。
          </div>
        ) : null}
        {queryParams.confirmation_rotated ? (
          <div className="notice success">专用验收码已重新生成，旧验收码立即失效。</div>
        ) : null}
        <form className="form inline-form" action={createShare}>
          <div className="field">
            <label htmlFor="name">链接名称</label>
            <input id="name" name="name" defaultValue={`${project.name} 客户交付包`} />
          </div>
          <div className="field">
            <label htmlFor="expires_at">过期时间</label>
            <input id="expires_at" name="expires_at" type="datetime-local" />
          </div>
          <SubmitButton pendingText="生成分享中...">生成链接</SubmitButton>
        </form>
        <div className="list">
          {shares.length === 0 ? (
            <p className="subtle">暂无分享链接。</p>
          ) : (
            shares.map((share) => (
              <div className="row" key={share.id}>
                <div>
                  <div className="meta-line">
                    <span className="tag">{share.status === "active" ? "有效" : "已撤销"}</span>
                    <span>{share.name}</span>
                    <span>{share.expires_at ? `过期 ${share.expires_at}` : "长期有效"}</span>
                    <span>{share.last_accessed_at ? `访问 ${share.last_accessed_at}` : "未访问"}</span>
                  </div>
                  <small>只读链接：/share/delivery/{share.token}</small>
                  <small>专用验收码：{share.confirmation_token ?? "未生成"}</small>
                </div>
                <div className="row-actions">
                  <Link className="button secondary" href={`/share/delivery/${share.token}`}>
                    打开
                  </Link>
                  {share.status === "active" ? (
                    <>
                      <form action={rotateDeliveryConfirmationTokenAction.bind(null, id, share.id)}>
                        <SubmitButton className="button secondary" pendingText="生成中...">
                          {share.confirmation_token ? "更换验收码" : "生成验收码"}
                        </SubmitButton>
                      </form>
                      <form action={revokeDeliveryShareAction.bind(null, id, share.id)}>
                        <SubmitButton className="button secondary" pendingText="撤销中...">
                          撤销
                        </SubmitButton>
                      </form>
                    </>
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
            <h2>交付报告清单</h2>
            <p className="subtle">报告按最新归档记录展示，客户可下载 Markdown 或 PDF 版本。</p>
          </div>
        </div>
        <div className="list">
          {deliverables.length === 0 ? (
            <p className="subtle">暂无客户可见报告。将复盘记录标记为客户可见，并把交付状态设为待交付、已交付或已确认后会出现在这里。</p>
          ) : (
            deliverables.map(({ placement, impact }) => {
              const report = impact?.review_report;
              const archiveMeta = report?.archive ?? {};
              const deltas = report?.metric_deltas ?? {};
              const deliveryStatus = archiveMeta.delivery_status ?? placement.delivery_status;
              return (
                <div className="row review-row" key={placement.id}>
                  <div>
                    <div className="meta-line">
                      <span className="tag">{deliveryStatusLabel(deliveryStatus)}</span>
                      <span>{statusLabel(report?.status)}</span>
                      <span>{archiveMeta.version ?? `PR-${placement.id}-v1`}</span>
                      <span>{placement.channel}</span>
                    </div>
                    <Link href={`/projects/${id}/placements/${placement.id}/impact`}>
                      <h3>{report?.conclusion ?? placement.notes ?? "待生成复盘结论"}</h3>
                    </Link>
                    <small>
                      {archiveMeta.archive_note ?? placement.archive_note ?? placement.notes ?? "暂无交付备注"}｜
                      样本变化 {deltas.sample_size_delta ?? 0}｜提及率 {deltaPct(deltas.company_mention_rate_delta)}｜
                      推荐率 {deltaPct(deltas.company_recommendation_rate_delta)}
                    </small>
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
