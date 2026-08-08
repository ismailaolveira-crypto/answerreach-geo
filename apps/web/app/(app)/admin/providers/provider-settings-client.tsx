"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { createProviderAction, saveOfficialProviderAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { BrandLogo } from "@/components/brand-logo";
import type { LLMProvider, LLMProviderReadiness } from "@/lib/api";
import { PROVIDER_CATALOG, isOfficialProvider, providerMatchesCatalog, type ProviderCatalogKey } from "@/lib/provider-catalog";

type Props = {
  providers: LLMProvider[];
  readinessRows: LLMProviderReadiness[];
  initialKey: ProviderCatalogKey;
};

function readableTime(value?: string | null) {
  if (!value) return "尚未测试";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function channelState(readiness?: LLMProviderReadiness) {
  if (readiness?.collection_ready) return { label: "健康", className: "is-ready" };
  if (readiness?.latest_test?.ok === false) return { label: "测试失败", className: "is-failed" };
  if (readiness?.diagnostic.auth_ready) return { label: "待测试", className: "is-pending" };
  return { label: "未配置", className: "is-muted" };
}

function officialProviderForModel(
  providers: LLMProvider[],
  key: ProviderCatalogKey,
) {
  const model = PROVIDER_CATALOG.find((item) => item.key === key);
  const official = providers.filter(
    (provider) => providerMatchesCatalog(provider, key) && isOfficialProvider(provider, key),
  );
  return official.find(
    (provider) => provider.provider_type === model?.defaultProviderType && provider.status === "active",
  ) ?? official.find((provider) => provider.status === "active") ?? official[0];
}

function officialModelState(provider: LLMProvider | undefined, readiness?: LLMProviderReadiness) {
  if (!provider || !readiness?.diagnostic.auth_ready) return { label: "未配置", className: "is-muted" };
  if (readiness.collection_ready) return { label: "已连接", className: "is-ready" };
  if (readiness.latest_test?.ok === false) return { label: "测试失败", className: "is-failed" };
  return { label: "待测试", className: "is-pending" };
}

export default function ProviderSettingsClient({ providers, readinessRows, initialKey }: Props) {
  const [selectedKey, setSelectedKey] = useState(initialKey);
  const readinessByProvider = useMemo(() => new Map(readinessRows.map((item) => [item.provider_id, item])), [readinessRows]);
  const selectedModel = PROVIDER_CATALOG.find((item) => item.key === selectedKey) ?? PROVIDER_CATALOG[0];
  const selectedProviders = providers.filter((provider) => providerMatchesCatalog(provider, selectedKey));
  const officialProviders = selectedProviders.filter((provider) => isOfficialProvider(provider, selectedKey));
  const primaryProvider = officialProviders.find((provider) => provider.provider_type === selectedModel.defaultProviderType && provider.status === "active")
    ?? officialProviders.find((provider) => provider.status === "active")
    ?? officialProviders[0];
  const volcengineProvider = selectedModel.defaultProviderType === "volcengine_ark" ? undefined : selectedProviders.find((provider) => provider.provider_type === "volcengine_ark" && provider.status === "active");
  const visibleProviders = [primaryProvider, volcengineProvider].filter((provider): provider is LLMProvider => Boolean(provider));
  const customProviders = selectedProviders.filter((provider) => !visibleProviders.some((visible) => visible.id === provider.id) && String(provider.cost_rule?.channel_role ?? "") !== "archived_duplicate");
  const primaryReadiness = primaryProvider ? readinessByProvider.get(primaryProvider.id) : undefined;
  const primaryState = channelState(primaryReadiness);
  const healthyCount = PROVIDER_CATALOG.filter((item) => {
    const provider = officialProviderForModel(providers, item.key);
    return provider ? readinessByProvider.get(provider.id)?.collection_ready : false;
  }).length;

  function selectModel(key: ProviderCatalogKey) {
    setSelectedKey(key);
  }

  return <div className="provider-hub">
    <header className="provider-hub-heading">
      <div><p>运营设置</p><h1>模型与渠道</h1><span>统一维护模型、API 渠道和联网能力。切换模型只切换视图，不会执行测试。</span></div>
      <div className={`provider-overall-state ${healthyCount ? "is-ready" : "is-pending"}`}><i />整体连接状态：{healthyCount ? `${healthyCount} 个渠道可观测` : "待完成测试"}</div>
    </header>

    <section className="provider-hub-models" aria-label="选择模型">
      <div className="provider-hub-section-title"><b>选择模型</b><small>点击仅切换下方配置</small></div>
      <div className="provider-hub-model-grid">
        {PROVIDER_CATALOG.map((item) => {
          const officialProvider = officialProviderForModel(providers, item.key);
          const status = officialModelState(
            officialProvider,
            officialProvider ? readinessByProvider.get(officialProvider.id) : undefined,
          );
          return <button type="button" key={item.key} onClick={() => selectModel(item.key)} className={selectedKey === item.key ? "is-selected" : ""} aria-pressed={selectedKey === item.key}>
            <BrandLogo brand={item.brand} label={item.label} />
            <span><b>{item.label}</b><small className={status.className}><i />{status.label}</small></span>
            {selectedKey === item.key ? <em>当前</em> : null}
          </button>;
        })}
      </div>
    </section>

    <div className="provider-hub-main-grid">
      <section className="provider-config-panel">
        <header><div><h2>渠道配置 <span>·</span> {selectedModel.label}</h2><p>主路径只保留官方渠道；保存 Key 不会自动测试。</p></div><span className={`provider-status-pill ${primaryState.className}`}><i />{primaryState.label}</span></header>

        {visibleProviders.length ? <div className="provider-config-channels">
          {visibleProviders.map((provider) => {
            const readiness = readinessByProvider.get(provider.id);
            const state = channelState(readiness);
            return <article key={provider.id} className={primaryProvider?.id === provider.id ? "is-primary" : ""}>
              <div><i className={state.className} /><span><b>{provider === volcengineProvider ? "火山引擎渠道" : `${selectedModel.label} 官方渠道`}</b><small>{provider.model_name} · {provider.api_base_url || "默认官方端点"}</small></span></div>
              <span className={`provider-status-pill ${state.className}`}><i />{state.label}</span>
              <Link href={`/admin/providers/${provider.id}/test?return_to=/admin/providers%3Fmodel%3D${selectedKey}`}>配置 / 测试</Link>
            </article>;
          })}
        </div> : <div className="provider-config-empty"><BrandLogo brand={selectedModel.brand} label={selectedModel.label} /><div><b>还没有 {selectedModel.label} 渠道</b><p>填写下方必要信息即可创建；创建后由你决定何时测试。</p></div></div>}

        <form action={saveOfficialProviderAction} className="provider-quick-form">
          <input type="hidden" name="provider_type" value={selectedModel.defaultProviderType} />
          <input type="hidden" name="status" value="active" />
          <input type="hidden" name="platform_key" value={selectedKey} />
          <input type="hidden" name="channel_role" value="official" />
          <input type="hidden" name="enable_search" value="on" />
          <input type="hidden" name="api_base_url" value={selectedModel.defaultBaseUrl} />
          <input type="hidden" name="timeout_seconds" value="45" />
          <input type="hidden" name="currency" value="CNY" />
          <div className="provider-quick-fields">
            <label><span>官方模型</span><select name="model_name" defaultValue={primaryProvider?.model_name || selectedModel.defaultModel}>{selectedModel.modelOptions.map((model) => <option key={model.value} value={model.value}>{model.label}</option>)}</select></label>
            <label><span>API Key</span><input name="api_key" type="password" autoComplete="off" placeholder={primaryReadiness?.diagnostic.auth_ready ? "已保存；留空保持不变" : "粘贴官方 API Key"} /></label>
          </div>
          <details className="provider-quick-advanced"><summary>技术设置 <span>{selectedKey === "qwen" ? "千问 Workspace" : "展开"}</span></summary><div>{selectedKey === "qwen" ? <label><span>百炼业务空间 ID</span><input name="workspace_id" defaultValue={String(primaryProvider?.cost_rule?.workspace_id ?? "")} placeholder="ws-...（Workspace Key 必填）" /></label> : <label><span>API 端点</span><input value={selectedModel.defaultBaseUrl} readOnly /></label>}<p>{selectedKey === "qwen" ? "北京地域的 Responses API 需要业务空间专属域名；普通 Key 可留空，Workspace Key 请填写 ws- 开头的业务空间 ID。" : "模型 ID、端点与联网方式只属于当前模型；保存后如有修改，可在具体渠道内调整。"}</p></div></details>
          <div className="provider-quick-actions"><p>保存只写入后端，不调用外部模型。</p><SubmitButton className="provider-save-button" pendingText="正在保存配置...">保存官方渠道</SubmitButton></div>
        </form>

        <details className="provider-custom-channels">
          <summary><span>自定义渠道</span><small>{customProviders.length ? `${customProviders.length} 个已收起` : "按需手动添加"}</small><i>＋</i></summary>
          <div>
            {customProviders.length ? <div className="provider-config-channels">{customProviders.map((provider) => <article key={provider.id}><div><span><b>{provider.name}</b><small>{provider.model_name} · {provider.api_base_url || "自定义端点"}</small></span></div><Link href={`/admin/providers/${provider.id}/test?return_to=/admin/providers%3Fmodel%3D${selectedKey}`}>配置 / 测试</Link></article>)}</div> : null}
            <form action={createProviderAction} className="provider-custom-form">
              <input type="hidden" name="platform_key" value={selectedKey} /><input type="hidden" name="channel_role" value="custom" /><input type="hidden" name="status" value="active" /><input type="hidden" name="timeout_seconds" value="45" />
              <label><span>渠道名称</span><input name="name" required placeholder="例如：企业代理渠道" /></label>
              <label><span>渠道类型</span><select name="provider_type" defaultValue="openai_compatible"><option value="openai_compatible">OpenAI Compatible</option><option value="volcengine_ark">火山引擎</option><option value="qwen_compatible">千问兼容接口</option><option value="kimi_web_search">Kimi 联网接口</option></select></label>
              <label><span>模型 ID</span><input name="model_name" required placeholder="服务商提供的模型 ID" /></label>
              <label><span>API Base URL</span><input name="api_base_url" required placeholder="https://.../v1" /></label>
              <label className="is-wide"><span>API Key</span><input name="api_key" type="password" autoComplete="off" required placeholder="粘贴该渠道的 API Key" /></label>
              <div className="is-wide"><SubmitButton className="button secondary" pendingText="正在添加...">添加自定义渠道</SubmitButton></div>
            </form>
          </div>
        </details>
      </section>

      <section className="provider-health-panel">
        <header><div><h2>渠道健康</h2><p>{primaryProvider?.name || `${selectedModel.label} 官方渠道`}</p></div><span className={`provider-status-pill ${primaryState.className}`}><i />{primaryState.label}</span></header>
        <dl>
          <div><dt>最近测试</dt><dd>{readableTime(primaryReadiness?.latest_test?.created_at)}<em className={primaryReadiness?.latest_test?.ok ? "is-good" : ""}>{primaryReadiness?.latest_test ? primaryReadiness.latest_test.ok ? "成功" : "失败" : "未执行"}</em></dd></div>
          <div><dt>最近延迟</dt><dd>{primaryReadiness?.latest_test?.latency_ms ? `${primaryReadiness.latest_test.latency_ms} ms` : "—"}<em>{primaryReadiness?.latest_test?.latency_ms && primaryReadiness.latest_test.latency_ms < 5000 ? "正常" : "待测"}</em></dd></div>
          <div><dt>联网搜索能力</dt><dd>{primaryReadiness?.diagnostic.supports_web_search ? "已声明支持" : "尚未验证"}<em className={primaryReadiness?.diagnostic.supports_web_search ? "is-good" : ""}>{primaryReadiness?.diagnostic.supports_web_search ? "✓" : "—"}</em></dd></div>
          <div><dt>来源归档门禁</dt><dd>{primaryReadiness?.collection_ready ? "可进入决策地图" : "测试后确认"}<em className={primaryReadiness?.collection_ready ? "is-good" : ""}>{primaryReadiness?.collection_ready ? "✓" : "—"}</em></dd></div>
          <div><dt>当前阻塞</dt><dd>{primaryProvider ? primaryReadiness?.diagnostic.auth_ready ? primaryReadiness?.collection_blocker || "无" : "API Key 尚未配置" : "尚未创建官方渠道"}<em className={primaryProvider && primaryReadiness?.diagnostic.auth_ready && !primaryReadiness?.collection_blocker ? "is-good" : ""}>{primaryProvider && primaryReadiness?.diagnostic.auth_ready && !primaryReadiness?.collection_blocker ? "正常" : "待处理"}</em></dd></div>
        </dl>
        {primaryProvider ? <Link className="provider-test-explicit" href={`/admin/providers/${primaryProvider.id}/test?return_to=/admin/providers%3Fmodel%3D${selectedKey}`}>打开渠道设置与测试 <span>→</span></Link> : <span className="provider-test-explicit is-disabled">保存渠道后即可测试</span>}
        <small>只有你在下一页主动点击“测试渠道”时，系统才会产生真实 API 请求。</small>
      </section>
    </div>

    <section className="provider-observation-link">
      <div><p>观测工作台</p><h2>渠道准备好后，再去决策地图发起观测</h2><span>推荐问题、自定义问题、模型和运行次数都在同一个紧凑面板内完成。</span></div>
      <Link href={`/geo/1?model=${selectedKey}`}>前往决策地图 <span>→</span></Link>
    </section>
  </div>;
}
