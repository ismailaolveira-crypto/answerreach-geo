import Link from "next/link";
import type { Route } from "next";
import { getLLMProviderReadiness, getLLMProviders, type LLMProvider, type LLMProviderReadiness } from "@/lib/geo-provider-api";
import { BrandLogo } from "@/components/brand-logo";
import { getCleanroomEvidence, getOfficialProviderObservationBatches } from "@/lib/cleanroom-v1-api";

type Props = { params: Promise<{ workspaceId: string }> };
type PlatformDefinition = {
  key: string;
  label: string;
  providerTypes: string[];
  platformKey: string;
  note: string;
};

const PLATFORMS: PlatformDefinition[] = [
  { key: "deepseek", label: "DeepSeek", providerTypes: ["deepseek_web_search"], platformKey: "deepseek", note: "DeepSeek 官方 API · Web Search" },
  { key: "qwen", label: "通义千问", providerTypes: ["bailian_qwen_responses"], platformKey: "qianwen", note: "阿里云百炼官方 API · 联网搜索" },
  { key: "doubao", label: "豆包", providerTypes: ["volcengine_ark"], platformKey: "doubao", note: "火山方舟官方 API · 联网搜索" },
  { key: "glm", label: "智谱 GLM", providerTypes: ["volcengine_ark"], platformKey: "glm", note: "火山方舟官方 API · 联网搜索" },
  { key: "kimi", label: "Kimi", providerTypes: ["kimi_web_search"], platformKey: "kimi", note: "Moonshot 官方工具 · 联网搜索" },
  { key: "hunyuan", label: "腾讯混元", providerTypes: ["hunyuan_web_search"], platformKey: "hunyuan", note: "腾讯混元官方 API · 强制搜索增强" },
];

const BATCH_STATUS_LABELS = {
  pending: "等待中",
  running: "运行中",
  success: "已成功",
  partial: "部分失败",
  failed: "已失败",
};

function formatOperationTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function providerFor(definition: PlatformDefinition, providers: LLMProvider[]) {
  const matches = (item: LLMProvider) => {
    if (!definition.providerTypes.includes(item.provider_type)) return false;
    const configuredKey = String(item.cost_rule?.platform_key ?? "").toLowerCase();
    if (configuredKey) return (configuredKey === "qwen" ? "qianwen" : configuredKey) === definition.platformKey;
    if (item.provider_type === "volcengine_ark") {
      const value = `${item.name} ${item.model_name}`.toLowerCase();
      return definition.key === "glm" ? value.includes("glm") : definition.key === "doubao" ? value.includes("doubao") : false;
    }
    return true;
  };
  for (const providerType of definition.providerTypes) {
    const active = providers.find((item) => item.provider_type === providerType && matches(item) && item.status === "active");
    if (active) return active;
    const configured = providers.find((item) => item.provider_type === providerType && matches(item));
    if (configured) return configured;
  }
  return undefined;
}

function connectionState(provider: LLMProvider | undefined, readiness?: LLMProviderReadiness | null) {
  if (!provider) return { tone: "waiting", label: "待接入", hint: "尚未创建 API 连接" };
  const diagnostic = readiness?.diagnostic ?? null;
  const latestTest = readiness?.latest_test ?? null;
  if (!diagnostic?.auth_ready) return { tone: "needs-key", label: "需要 API Key", hint: "连接已创建，密钥尚未配置" };
  if (readiness?.collection_ready) return { tone: "verified", label: "联网门禁可用", hint: "当前配置已通过真实联网测试" };
  if (readiness && !readiness.test_fresh && latestTest) return { tone: "unverified", label: "需要重新测试", hint: readiness.collection_blocker || "配置已变更，旧测试不再证明当前渠道可用" };
  if (latestTest?.ok === false) return { tone: "unverified", label: "测试未通过", hint: latestTest.error_message || "模型未通过联网证据门禁" };
  if (!latestTest) return { tone: "unverified", label: "待真实测试", hint: "需通过联网调用、来源 URL 与最终回答三项验证" };
  if (diagnostic.auth_ready) return { tone: "unverified", label: "尚未达到门禁", hint: readiness?.collection_blocker || diagnostic.last_blocker || "普通 API 可用，但不计入联网观测" };
  return { tone: "waiting", label: "待配置", hint: "完成连接后即可测试" };
}

export default async function OperationsPage({ params }: Props) {
  const { workspaceId } = await params;
  const [evidence, providers, readinessRows, recentBatches] = await Promise.all([
    getCleanroomEvidence(workspaceId),
    getLLMProviders(),
    getLLMProviderReadiness(),
    getOfficialProviderObservationBatches(workspaceId, { page: 1, pageSize: 5 }),
  ]);
  const readinessByProvider = new Map(readinessRows.map((item) => [item.provider_id, item]));
  const rows = PLATFORMS.map((definition) => {
    const provider = providerFor(definition, providers);
    const readiness = provider ? readinessByProvider.get(provider.id) : null;
    const diagnostic = readiness?.diagnostic ?? null;
    const latestTest = readiness?.latest_test ?? null;
    const providerUpdatedAt = provider?.updated_at ? Date.parse(provider.updated_at) : 0;
    const providerEvidence = provider ? evidence.find((item) =>
      item.collection_method === "official_api_web_search"
      && item.is_real_provider_evidence
      && Number(item.sampling_environment.provider_id) === provider.id
      && item.sampling_environment.search_verified === true
      && Number(item.sampling_environment.search_event_count) > 0
      && item.source_items.length > 0
      && Boolean(item.raw_artifact_uri)
      && (!providerUpdatedAt || Date.parse(item.captured_at) >= providerUpdatedAt)
    ) : undefined;
    const connection = connectionState(provider, readiness);
    const accepted = connection.tone === "verified" && Boolean(providerEvidence);
    const state = accepted
      ? { tone: "verified", label: "产品闭环通过", hint: `真实回答、联网来源和原始工件已归档（证据 #${providerEvidence?.id}）` }
      : connection.tone === "verified"
        ? { tone: "unverified", label: "待完成观测", hint: "API 联网测试已通过，还需从决策地图生成一条完整证据" }
        : connection;
    return { definition, provider, diagnostic, latestTest, providerEvidence, accepted, testedAvailable: readiness?.collection_ready === true, state };
  });
  const testedAvailableCount = rows.filter((item) => item.testedAvailable).length;
  const needsConfigurationCount = rows.length - testedAvailableCount;

  return <div className="sy-page">
    <header className="sy-topbar"><Link className="sy-brand" href={`/geo/${workspaceId}`}><span>◈</span><b>春秋元泉 GEO</b></Link><Link className="sy-back" href={`/geo/${workspaceId}`}>← 返回决策地图</Link></header>
    <main className="sy-work-main sy-api-settings">
      <header><p>运营设置</p><h1>模型连接</h1><span>统一配置官方 API。只有能证明执行过联网搜索的回答，才会进入决策地图。</span></header>

      <section className="sy-api-summary" aria-label="模型连接摘要">
        <div className="is-total"><span>模型平台</span><strong>{PLATFORMS.length}</strong><small>家已纳入观测</small></div>
        <div className="is-ready"><span>可发起观测</span><strong>{testedAvailableCount}</strong><small>家当前通过联网门禁</small></div>
        <div className="is-config"><span>需要处理</span><strong>{needsConfigurationCount}</strong><small>家需配置、重测或排障</small></div>
      </section>

      <section className="sy-provider-section">
        <div className="sy-section-heading"><div><h2>API 连接</h2><p>日常只需要维护 Key。模型、地址和搜索能力可在高级配置中调整。</p></div><Link href="/admin/providers">管理全部连接</Link></div>
        <div className="sy-provider-grid">
          {rows.map(({ definition, provider, diagnostic, providerEvidence, state }) => {
            const href = provider
              ? `/admin/providers/${provider.id}/test?return_to=/geo/${workspaceId}/operations`
              : `/admin/providers?model=${definition.key}`;
            return <article className={`sy-provider-card is-${state.tone}`} data-provider-key={definition.key} key={definition.key}>
              <header><BrandLogo brand={definition.key} label={definition.label} className="sy-provider-mark" /><div><h3>{definition.label}</h3><p>{definition.note}</p></div><i>{state.label}</i></header>
              <div className="sy-provider-facts"><span><small>当前模型</small><b>{provider?.model_name || "尚未配置"}</b></span><span><small>API Key</small><b>{diagnostic?.auth_ready ? "已安全配置" : "未配置"}</b></span><span><small>闭环证据</small><b>{providerEvidence ? `#${providerEvidence.id} 已归档` : "尚未生成"}</b></span></div>
              <p className="sy-provider-hint">{state.hint}</p>
              <Link className="sy-provider-action" href={href as Route}>{provider ? "配置并测试" : "配置 API"}<span>→</span></Link>
            </article>;
          })}
        </div>
      </section>

      <section className="sy-runtime-section" aria-labelledby="recent-runtime-heading">
        <div className="sy-section-heading">
          <div><h2 id="recent-runtime-heading">最近真实运行</h2><p>来自后台任务队列的持久化批次；进度、失败数与证据在刷新后仍可恢复。</p></div>
          <Link href={`/geo/${workspaceId}/batches`}>查看全部 {recentBatches.pagination.total} 个批次</Link>
        </div>
        {recentBatches.items.length ? <div className="sy-batch-list sy-runtime-list" aria-label="最近真实观测批次">
          <div className="sy-batch-list-head"><span>批次与创建时间</span><span>任务矩阵</span><span>执行结果</span><span>整体状态</span></div>
          {recentBatches.items.map((batch) => <Link
            aria-label={`查看批次 ${batch.batch_id} 的任务、失败原因与证据`}
            className={`sy-batch-list-row is-${batch.status}`}
            href={`/geo/${workspaceId}/batches/${batch.batch_id}`}
            key={batch.batch_id}
          >
            <div><b>批次 #{batch.batch_id}</b><small>{formatOperationTime(batch.created_at)}</small></div>
            <div><b>{batch.provider_count} 模型 × {batch.question_count} 问题</b><small>{batch.repeat_count} 次，共 {batch.total} 条真实任务</small></div>
            <div><b>{batch.succeeded} 成功 · {batch.failed} 失败</b><small>已完成 {batch.succeeded + batch.failed}/{batch.total}</small></div>
            <div><em className={`is-${batch.status}`}>{BATCH_STATUS_LABELS[batch.status]}</em><span className="sy-runtime-progress" role="progressbar" aria-label={`批次 ${batch.batch_id} 完成进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={batch.progress_percent}><i style={{ width: `${batch.progress_percent}%` }} /></span><small>{batch.progress_percent}% · 查看任务详情</small></div>
          </Link>)}
        </div> : <div className="sy-runtime-empty"><b>还没有真实观测批次</b><span>从决策地图发起第一轮联网观测后，后台任务会显示在这里。</span><Link href={`/geo/${workspaceId}`}>返回决策地图开始观测 →</Link></div>}
      </section>

      <details className="sy-advanced-settings">
        <summary><span><b>高级说明</b><small>联网门禁如何保护数据可信度</small></span><i>⌄</i></summary>
        <div><p>系统不会仅凭回答里出现链接就认定“已联网”。一次观测必须同时保存搜索工具调用、搜索结果块、可打开的来源 URL 和原始 API 响应；缺少任一项都会显示失败，不进入指标。</p><p>普通 Chat Completions 即使能回答问题，也只算连接测试，不算 GEO 联网观测。</p></div>
      </details>
    </main>
  </div>;
}
