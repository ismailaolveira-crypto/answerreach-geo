import { notFound } from "next/navigation";
import { confirmPublicDeliveryAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getPublicDeliveryExportUrl, getPublicDeliveryPackage } from "@/lib/api";

type PageProps = {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ confirmed?: string; confirmation_error?: string }>;
};

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

export default async function PublicDeliveryPackagePage({ params, searchParams }: PageProps) {
  const { token } = await params;
  const queryParams = await searchParams;
  const packageData = await getPublicDeliveryPackage(token).catch(() => null);
  if (!packageData) notFound();

  const acceptedCount = packageData.deliverables.filter(
    (item) => item.review_report.archive?.delivery_status === "accepted"
  ).length;

  return (
    <main className="main share-main">
      <div className="stack">
        <div className="topbar">
          <div>
            <div className="eyebrow">GEO 交付报告</div>
            <h1>{packageData.project.name}</h1>
            <p className="subtle">{packageData.project.description ?? packageData.share.name}</p>
          </div>
        </div>

        <section className="grid cols-3">
          <div className="panel metric">
            <span>交付报告</span>
            <strong>{packageData.deliverables.length}</strong>
          </div>
          <div className="panel metric">
            <span>已确认</span>
            <strong>{acceptedCount}</strong>
          </div>
          <div className="panel metric">
            <span>链接状态</span>
            <strong>{packageData.share.status === "active" ? "有效" : "失效"}</strong>
          </div>
        </section>

        <section className="panel">
          <h2>复盘报告</h2>
          {queryParams.confirmed ? (
            <div className="notice success">验收记录已保存，回到 GEO 工作台后可回读这条证据。</div>
          ) : null}
          {queryParams.confirmation_error ? (
            <div className="notice warning">未能完成验收。请检查验收码和确认人，或联系发送方重新生成验收码。</div>
          ) : null}
          <div className="list">
            {packageData.deliverables.length === 0 ? (
              <p className="subtle">暂无可交付报告。</p>
            ) : (
              packageData.deliverables.map((item) => {
                const report = item.review_report;
                const archive = report.archive ?? {};
                const deltas = report.metric_deltas ?? {};
                const isAccepted = archive.delivery_status === "accepted";
                return (
                  <div className="row review-row" key={item.placement.id}>
                    <div>
                      <div className="meta-line">
                        <span className="tag">{deliveryStatusLabel(archive.delivery_status)}</span>
                        <span>{statusLabel(report.status)}</span>
                        <span>{archive.version ?? `PR-${item.placement.id}-v1`}</span>
                        <span>{item.placement.channel}</span>
                      </div>
                      <h3>{report.conclusion}</h3>
                      <small>
                        {archive.archive_note ?? item.placement.archive_note ?? "暂无交付备注"}｜
                        样本变化 {deltas.sample_size_delta ?? 0}｜提及率 {deltaPct(deltas.company_mention_rate_delta)}｜
                        推荐率 {deltaPct(deltas.company_recommendation_rate_delta)}
                      </small>
                      {isAccepted ? (
                        <p className="subtle">已通过专用验收码保存确认记录。</p>
                      ) : (
                        <form
                          className="archive-inline-form"
                          action={confirmPublicDeliveryAction.bind(null, token, item.placement.id)}
                        >
                          <input name="confirmation_token" placeholder="专用验收码" required minLength={20} autoComplete="one-time-code" />
                          <input name="actor_name" placeholder="确认人姓名" required />
                          <input name="comment" placeholder="备注，可选" />
                          <SubmitButton className="button secondary" pendingText="确认中...">
                            提交验收确认
                          </SubmitButton>
                        </form>
                      )}
                    </div>
                    <div className="row-actions">
                      <a className="button secondary" href={getPublicDeliveryExportUrl(item.exports.markdown)}>
                        Markdown
                      </a>
                      <a className="button secondary" href={getPublicDeliveryExportUrl(item.exports.pdf)}>
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
    </main>
  );
}
