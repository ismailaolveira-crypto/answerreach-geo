import Link from "next/link";
import { getOfficialProviderObservationBatches } from "@/lib/cleanroom-v1-api";

type Props = {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<{ page?: string }>;
};

const STATUS_LABELS = {
  pending: "等待中",
  running: "运行中",
  success: "已成功",
  partial: "部分失败",
  failed: "已失败",
};

function batchStatusLabel(batch: { status: keyof typeof STATUS_LABELS; dispatch_enabled: boolean }) {
  if (!batch.dispatch_enabled && batch.status === "pending") return "历史保留";
  return STATUS_LABELS[batch.status];
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function batchSourceLabel(sourceType: string) {
  if (sourceType === "official_api") return "官方 API";
  if (sourceType === "official_api_single") return "单次 API";
  if (sourceType === "browser_profile") return "网页采样";
  if (sourceType === "legacy_import") return "历史迁移";
  if (sourceType.startsWith("yao_")) return "授权导入";
  return "统一台账";
}

export default async function ObservationBatchesPage({ params, searchParams }: Props) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const requestedPage = Number(query.page);
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const result = await getOfficialProviderObservationBatches(workspaceId, { page, pageSize: 20 });
  const { pagination } = result;

  return <div className="sy-page">
    <header className="sy-topbar">
      <Link className="sy-brand" href={`/geo/${workspaceId}`}><span>◈</span><b>春秋元泉 GEO</b></Link>
      <Link className="sy-back" href={`/geo/${workspaceId}`}>← 返回决策地图</Link>
    </header>
    <main className="sy-work-main sy-batches-main">
      <header><p>真实观测任务归档</p><h1>历史批次</h1><span>按创建时间倒序展示统一观测台账中的全部批次，覆盖 API、网页采样和授权导入。</span></header>
      {result.items.length ? <section className="sy-batch-list" aria-label="历史采样批次">
        <div className="sy-batch-list-head"><span>批次与创建时间</span><span>任务矩阵</span><span>执行结果</span><span>整体状态</span></div>
        {result.items.map((batch) => <Link key={batch.batch_id} href={`/geo/${workspaceId}/batches/${batch.batch_id}`} className={`sy-batch-list-row is-${batch.status}`}>
          <div><b>批次 #{batch.batch_id}</b><small>{formatDate(batch.created_at)} · {batchSourceLabel(batch.source_type)}</small></div>
          <div><b>{batch.provider_count} 模型 × {batch.question_count} 问题</b><small>{batch.repeat_count} 次，共 {batch.total} 条任务</small></div>
          <div><b>{batch.succeeded} 成功 · {batch.failed} 失败</b><small>已完成 {batch.succeeded + batch.failed}/{batch.total}</small></div>
          <div><em className={`is-${batch.status}`}>{batchStatusLabel(batch)}</em><span className="sy-runtime-progress" role="progressbar" aria-label={`批次 ${batch.batch_id} 完成进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={batch.progress_percent}><i style={{ width: `${batch.progress_percent}%` }} /></span><small>{batch.progress_percent}%</small></div>
        </Link>)}
      </section> : <section className="sy-batch-empty"><span>◇</span><h2>还没有采样批次</h2><p>从决策地图开始第一轮真实模型观测后，批次会自动出现在这里。</p><Link className="sy-primary" href={`/geo/${workspaceId}`}>返回决策地图</Link></section>}
      {pagination.total_pages > 1 ? <nav className="sy-batch-pagination" aria-label="批次列表分页">
        {pagination.page > 1 ? <Link href={`?page=${pagination.page - 1}`}>← 上一页</Link> : <span>← 上一页</span>}
        <b>第 {pagination.page} / {pagination.total_pages} 页</b>
        {pagination.page < pagination.total_pages ? <Link href={`?page=${pagination.page + 1}`}>下一页 →</Link> : <span>下一页 →</span>}
      </nav> : null}
    </main>
  </div>;
}
