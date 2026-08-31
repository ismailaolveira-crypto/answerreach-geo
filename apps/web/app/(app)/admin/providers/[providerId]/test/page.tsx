import { testProviderAction, updateProviderAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { BrandLogo } from "@/components/brand-logo";
import { getLLMProvider, getLLMProviderDiagnostic, getLLMProviderTestRuns } from "@/lib/api";
import { catalogForProvider } from "@/lib/provider-catalog";
import { getCurrentUser } from "@/lib/session";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { Route } from "next";
import { SecretKeyField } from "./secret-key-field";
import { ProviderTestExperience } from "./provider-test-experience";

type PageProps = {
  params: Promise<{ providerId: string }>;
  searchParams: Promise<{
    ok?: string;
    prompt?: string;
    summary?: string;
    preview?: string;
    error?: string;
    return_to?: string;
    updated?: string;
    created?: string;
  }>;
};

function accessMethodLabel(value: string) {
  const labels: Record<string, string> = {
    browser_automation: "浏览器自动化观测",
    official_api_with_web_search: "官方 API + 搜索",
    aggregate_api_with_web_search: "聚合 API + 搜索",
    builtin_web_search_api: "内置联网 API",
    chat_completion_api: "Chat Completions API",
    mock: "Mock 演示"
  };
  return labels[value] ?? value;
}

function searchAccessLabel(value: string) {
  const labels: Record<string, string> = {
    api_ready_no_live_search: "API 可用但未证明联网",
    needs_config: "待补配置",
    ready_for_observation: "可用于网页端观测",
    ready_for_official_search: "可用于官方联网采集",
    ready_for_collection: "可用于联网采集",
    ready_for_demo: "可用于演示"
  };
  return labels[value] ?? value;
}

function asRoute(value: string) {
  return value as Route;
}

function providerHubRoute(returnTo: string) {
  if (returnTo.startsWith("/admin/providers")) return returnTo;
  const workspaceId = returnTo.match(/^\/geo\/(\d+)(?:\/|$)/)?.[1];
  return workspaceId ? `/admin/providers?workspace=${workspaceId}` : "/admin/providers";
}

function numberDefault(value: unknown, fallback = 0) {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function providerProbeCommand(providerId: string, inactive: boolean) {
  const inactiveFlags = inactive ? " --allow-inactive --activate-on-success" : "";
  return `pnpm run probe:providers -- --project-id 1 --provider-ids ${providerId}${inactiveFlags}`;
}

const QUICK_CONNECTORS: Record<string, {
  brand: "deepseek" | "qwen" | "kimi" | "doubao" | "glm" | "hunyuan";
  label: string;
  subtitle: string;
  keyLabel: string;
  placeholder: string;
  searchMethod: string;
  assurance: string;
  caveat: string;
}> = {
  deepseek_web_search: {
    brand: "deepseek",
    label: "DeepSeek",
    subtitle: "用于春秋元泉 GEO 的官方联网观测",
    keyLabel: "DeepSeek API Key",
    placeholder: "粘贴 sk- 开头的 API Key",
    searchMethod: "官方 Web Search",
    assurance: "联网搜索已固定开启，缺少回答或来源时不会写入决策地图。",
    caveat: "此通道记录 DeepSeek 官方 API 搜索链，不能代表消费级网页端的个性化排序。",
  },
  qwen_compatible: {
    brand: "qwen",
    label: "通义千问",
    subtitle: "百炼官方模型 · 强制联网搜索与来源归档",
    keyLabel: "DashScope API Key",
    placeholder: "粘贴百炼 API Key",
    searchMethod: "DashScope 强制联网",
    assurance: "系统固定强制搜索并要求 search_info 来源；未执行搜索时验证会直接失败。",
    caveat: "此通道模拟千问的官方联网回答链，但不复制网页账号记忆、推荐策略或界面实验。",
  },
  bailian_qwen_responses: {
    brand: "qwen",
    label: "通义千问 3.7 Plus",
    subtitle: "百炼官方 Responses API · 原生联网搜索与来源归档",
    keyLabel: "百炼 API Key",
    placeholder: "粘贴百炼 API Key",
    searchMethod: "Responses API Web Search",
    assurance: "系统固定调用官方 web_search；没有搜索事件、来源 URL 或最终回答时不会写入决策地图。",
    caveat: "此通道记录百炼官方联网回答链，不继承千问消费级网页账号的记忆与个性化排序。",
  },
  kimi_web_search: {
    brand: "kimi",
    label: "Kimi",
    subtitle: "Kimi 官方工具 · 搜索执行与原始工件归档",
    keyLabel: "Kimi API Key",
    placeholder: "粘贴 Kimi 开放平台 API Key",
    searchMethod: "Official Formula Web Search",
    assurance: "系统实际执行 Kimi 官方搜索工具；没有工具结果、来源 URL 或最终回答时验证失败。",
    caveat: "此通道使用 Kimi 官方工具链，不继承网页端账号记忆，因此更适合干净基线观测。",
  },
  hunyuan_web_search: {
    brand: "hunyuan",
    label: "腾讯混元",
    subtitle: "腾讯混元官方 API · 强制搜索增强与来源归档",
    keyLabel: "腾讯混元 API Key",
    placeholder: "粘贴腾讯混元 API Key",
    searchMethod: "强制搜索增强 + search_info",
    assurance: "系统固定开启搜索增强、强制搜索、search_info 和引用；没有来源 URL 或最终回答时验证失败。",
    caveat: "此通道记录腾讯混元官方搜索增强链；不继承消费级网页账号的记忆或个性化排序。",
  },
  volcengine_ark: {
    brand: "doubao",
    label: "豆包",
    subtitle: "火山方舟官方 Responses API · 内置联网搜索",
    keyLabel: "火山方舟 API Key",
    placeholder: "粘贴 ark- 开头的 API Key",
    searchMethod: "Responses API Web Search",
    assurance: "系统要求同时返回搜索事件、来源 URL 和最终回答；缺少任一项都不会进入决策地图。",
    caveat: "此通道尽可能复现豆包的联网回答链，但不继承消费级网页账号记忆。当前使用已开通的 Seed 2.1 Pro；免费额度以火山方舟控制台为准。",
  },
  xiaoma_domestic_web_search: {
    brand: "qwen",
    label: "小马 API · 千问",
    subtitle: "聚合 API · 强制联网搜索与来源归档",
    keyLabel: "小马 API Key",
    placeholder: "粘贴小马 API Key",
    searchMethod: "Responses API Web Search",
    assurance: "系统强制声明联网搜索；只有搜索事件、来源 URL 和最终回答齐全时才会写入决策地图。",
    caveat: "这是小马聚合 API，不是千问官方直连。切换到其他国内模型时，必须分别通过联网验证。",
  },
};

function resolveQuickConnector(provider: { provider_type: string; name: string; model_name: string; cost_rule: Record<string, unknown> }) {
  const catalog = catalogForProvider(provider);
  if (provider.provider_type !== "volcengine_ark") {
    const connector = QUICK_CONNECTORS[provider.provider_type];
    if (!connector || !catalog) return catalog ? connector : undefined;
    return {
      ...connector,
      brand: catalog.brand,
      label: catalog.label,
      subtitle: provider.provider_type === "xiaoma_domestic_web_search"
        ? `${catalog.label} · 聚合 API 联网搜索与来源归档`
        : catalog.description,
      keyLabel: `${catalog.label} API Key`,
    };
  }
  const platformKey = String(provider.cost_rule.platform_key ?? "").toLowerCase();
  const value = `${provider.name} ${provider.model_name}`.toLowerCase();
  if (platformKey === "glm" || value.includes("glm") || value.includes("智谱")) {
    return {
      ...QUICK_CONNECTORS.volcengine_ark,
      brand: "glm" as const,
      label: "智谱 GLM",
      subtitle: "火山方舟官方 Responses API · GLM 联网搜索",
      caveat: "此通道使用火山方舟中的 GLM 模型；是否可调用及免费额度以方舟控制台为准。",
    };
  }
  return QUICK_CONNECTORS.volcengine_ark;
}

export default async function ProviderTestPage({ params, searchParams }: PageProps) {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin") {
    redirect("/");
  }
  const { providerId } = await params;
  const result = await searchParams;
  const [provider, diagnostic, runs] = await Promise.all([
    getLLMProvider(providerId),
    getLLMProviderDiagnostic(providerId).catch(() => null),
    getLLMProviderTestRuns(providerId).catch(() => [])
  ]);
  const testProvider = testProviderAction.bind(null, providerId);
  const updateProvider = updateProviderAction.bind(null, providerId);
  const hasResult = typeof result.ok === "string";
  const ok = result.ok === "1";
  const returnTo = result.return_to?.startsWith("/") ? result.return_to : "";
  const providerHub = providerHubRoute(returnTo);
  const updated = result.updated === "1";
  const createdFromTemplate = result.created === "template";
  const promptText = result.prompt ?? "网络安全培训公司哪家好？";
  const quickConnector = resolveQuickConnector(provider);
  const currentCatalog = catalogForProvider(provider);
  const quickPrompt = currentCatalog?.key === "qwen"
    ? "今天杭州天气如何？请联网搜索并列出来源。"
    : "企业级大模型治理平台怎么选？";

  if (quickConnector) {
    const latestTestAt = runs[0]?.created_at ? new Date(runs[0].created_at).getTime() : 0;
    const providerUpdatedAt = provider.updated_at ? new Date(provider.updated_at).getTime() : 0;
    const testFresh = Boolean(runs[0] && latestTestAt >= providerUpdatedAt);
    const latestTestPassed = runs[0]?.ok === true && testFresh;
    const configured = Boolean(diagnostic?.auth_ready);
    const connected = Boolean(diagnostic?.ready && diagnostic.supports_web_search && latestTestPassed);
    const connectionLabel = connected ? "已连接" : configured ? "已配置，待测试" : "未配置";
    return <div className="sy-connect-page">
      <header className="sy-connect-topbar">
        <Link href={asRoute(returnTo || providerHub)}><i>←</i> 返回</Link>
        <span><i className={connected ? "is-connected" : configured ? "is-configured" : ""} />{connectionLabel}</span>
      </header>
      <main className="sy-connect-main">
        <section className="sy-connect-hero">
          <div><p>连接模型</p><h1>连接 {quickConnector.label}</h1><span>{quickConnector.subtitle}</span></div>
          <div className="sy-connect-brand-corner">
            <BrandLogo brand={quickConnector.brand} label={quickConnector.label} />
            <i className={connected ? "is-connected" : configured ? "is-configured" : ""}><span />{connectionLabel}</i>
          </div>
        </section>

        <section className="sy-connect-card">
          <div className="sy-connect-copy"><span>1</span><div><h2>配置 {quickConnector.label}</h2><p>先保存 Key 和模型，再按需测试渠道；保存操作不会等待模型回答。</p></div></div>
          <form action={updateProvider} className="sy-connect-form">
            {returnTo ? <input type="hidden" name="return_to" value={returnTo} /> : null}
            <input type="hidden" name="name" value={provider.name} />
            <input type="hidden" name="provider_type" value={provider.provider_type} />
            <input type="hidden" name="platform_key" value={currentCatalog?.key ?? "other"} />
            <input type="hidden" name="api_base_url" value={provider.api_base_url ?? ""} />
            <input type="hidden" name="status" value="active" />
            <input type="hidden" name="prompt_text" value={quickPrompt} />
            <input type="hidden" name="existing_cost_rule" value={JSON.stringify(provider.cost_rule)} />
            <input type="hidden" name="input_per_1k" value={numberDefault(provider.cost_rule.input_per_1k)} />
            <input type="hidden" name="output_per_1k" value={numberDefault(provider.cost_rule.output_per_1k)} />
            <input type="hidden" name="currency" value={String(provider.cost_rule.currency ?? "USD")} />
            <input type="hidden" name="timeout_seconds" value="180" />
            {provider.provider_type === "volcengine_ark" ? <input type="hidden" name="monthly_search_limit" value={numberDefault(provider.cost_rule.monthly_search_limit, 19000)} /> : null}
            {provider.provider_type === "qwen_compatible" ? <input type="hidden" name="enable_search" value="on" /> : null}
            <label htmlFor="provider-model-name">选择模型</label>
            <select id="provider-model-name" name="model_name" defaultValue={provider.model_name}>
              {(currentCatalog?.modelOptions ?? [{ value: provider.model_name, label: provider.model_name }]).map((model) => <option value={model.value} key={model.value}>{model.label} · {model.value}</option>)}
            </select>
            <label htmlFor="provider-api-key">{quickConnector.keyLabel}</label>
            <SecretKeyField required={!configured} placeholder={configured ? "输入新 Key 可替换；留空将保留当前 Key" : quickConnector.placeholder} />
            <div className={`sy-key-state ${configured ? "is-configured" : "is-missing"}`} role="status">
              <span>{configured ? "✓" : "!"}</span>
              <div>
                <b>{updated && configured ? "API Key 刚刚保存成功" : configured ? "API Key 已安全保存" : "尚未保存 API Key"}</b>
                <small>{configured ? "出于安全原因不回显原文。以后保存时留空，不会删除当前 Key。" : `请粘贴${quickConnector.keyLabel}后保存。`}</small>
              </div>
            </div>
            <div className="sy-connect-assurance"><span>♙</span><p>Key 仅用于后端调用。{quickConnector.assurance}{provider.provider_type === "volcengine_ark" ? " 系统默认每月最多调用 19,000 次，避免超过官方免费额度。" : ""}</p></div>
            <SubmitButton className="sy-connect-submit" pendingText="正在保存配置...">{configured ? "保存修改" : "保存配置"}</SubmitButton>
          </form>
        </section>

        <ProviderTestExperience
          providerId={providerId}
          promptText={quickPrompt}
          disabled={!configured}
          initialTest={runs[0] ? {
            ok: runs[0].ok && testFresh,
            latencyMs: runs[0].latency_ms,
            createdAt: runs[0].created_at,
            error: testFresh ? runs[0].error_message : "配置已变更，请重新测试渠道。",
          } : null}
        />

        {hasResult ? <section className={`sy-connect-result ${ok ? "is-success" : "is-failed"}`}><span>{ok ? "✓" : "!"}</span><div><b>{ok ? "连接验证成功" : "连接验证未通过"}</b><p>{result.error || result.summary || "已完成本次连接检查。"}</p>{result.preview ? <details><summary>查看回答预览</summary><p>{result.preview}</p></details> : null}</div></section> : null}

        <details className="sy-connect-details">
          <summary><b>⚙</b><span>{quickConnector.label} 技术设置</span><small>只对当前模型生效</small><i>⌄</i></summary>
          <div><dl><div><dt>模型</dt><dd>{provider.model_name}</dd></div><div><dt>接口</dt><dd>{diagnostic?.endpoint_path ?? "官方搜索接口"}</dd></div><div><dt>联网方式</dt><dd>{quickConnector.searchMethod}</dd></div></dl><p>{quickConnector.caveat}</p><Link href={asRoute(providerHub)}>管理全部渠道</Link></div>
        </details>
      </main>
    </div>;
  }

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">渠道测试</div>
          <h1>{provider.name}</h1>
          <p className="subtle">
            {provider.provider_type}｜{provider.model_name}
          </p>
          {createdFromTemplate ? <p className="subtle">已从模板创建，请补充 API Key 或确认环境变量后执行测试调用。</p> : null}
        </div>
        <div className="row-actions">
          {returnTo ? (
            <Link className="button" href={asRoute(returnTo)}>
              返回来源
            </Link>
          ) : null}
          <Link className="button secondary" href={asRoute(providerHub)}>
            返回渠道
          </Link>
        </div>
      </div>

      {diagnostic ? (
        <section className="panel">
          <div className="row">
            <div>
              <h2>接入诊断</h2>
              <small>
                {diagnostic.base_url ?? "未配置 Base URL"}
                {diagnostic.endpoint_path}｜认证：{diagnostic.auth_ready ? "已就绪" : "缺失"}｜联网搜索：
                {diagnostic.supports_web_search ? "支持" : "未声明"}
              </small>
            </div>
            <span className="tag">{diagnostic.ready ? "ready" : "needs config"}</span>
          </div>
          <div className="grid cols-3">
            <div className="metric">
              <span>接入方式</span>
              <strong>{accessMethodLabel(diagnostic.access_method)}</strong>
              <small>{diagnostic.endpoint_path}</small>
            </div>
            <div className="metric">
              <span>搜索模式</span>
              <strong>{searchAccessLabel(diagnostic.search_access_status)}</strong>
              <small>{diagnostic.search_mode}</small>
            </div>
            <div className="metric">
              <span>采集结论</span>
              <strong>{diagnostic.supports_web_search ? "真实联网" : "需验证"}</strong>
              <small>{diagnostic.auth_source}</small>
            </div>
          </div>
          {diagnostic.missing.length > 0 ? (
            <p className="subtle">缺失：{diagnostic.missing.join("、")}</p>
          ) : null}
          {diagnostic.setup_steps.length > 0 ? (
            <div className="list">
              {diagnostic.setup_steps.map((item) => (
                <div className="row" key={item}>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          ) : null}
          {diagnostic.warnings.map((item) => (
            <p className="subtle" key={item}>
              {item}
            </p>
          ))}
          {diagnostic.recommendations.length > 0 ? (
            <div className="list">
              {diagnostic.recommendations.map((item) => (
                <div className="row" key={item}>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          ) : null}
          {provider.provider_type !== "mock" ? (
            <div className="notice warning">
              恢复探针：<code>{providerProbeCommand(providerId, provider.status !== "active")}</code>
              <br />
              探针成功后运行 <code>pnpm run verify:yuanquan</code>，确认多平台真实采集是否达到最终验收标准。
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>接入配置</h2>
            <p className="subtle">补齐 Base URL、模型名和 API Key 后，再执行测试调用确认真实采集可用。</p>
          </div>
          {updated ? <span className="tag active">已更新</span> : null}
        </div>
        <form action={updateProvider} className="form">
          {returnTo ? <input type="hidden" name="return_to" value={returnTo} /> : null}
          <input type="hidden" name="prompt" value={promptText} />
          <div className="grid cols-2">
            <div className="field">
              <label>渠道名称</label>
              <input name="name" defaultValue={provider.name} required />
            </div>
            <div className="field">
              <label>渠道类型</label>
              <select name="provider_type" defaultValue={provider.provider_type}>
                <option value="mock">Mock</option>
                <option value="openai_compatible">OpenAI Compatible</option>
                <option value="deepseek_web_search">DeepSeek 官方 API + Web Search</option>
                <option value="kimi_web_search">Kimi Web Search</option>
                <option value="hunyuan_web_search">腾讯混元官方 API + 搜索增强</option>
                <option value="volcengine_ark">火山方舟 / 豆包</option>
                <option value="qwen_compatible">千问兼容</option>
                <option value="bailian_qwen_responses">千问 3.7 Plus · 百炼官方 Responses API</option>
                <option value="xiaoma_domestic_web_search">小马 API · 国内模型联网搜索</option>
                <option value="browser_observation">浏览器网页端观测</option>
              </select>
            </div>
            <div className="field">
              <label>模型名称</label>
              <input name="model_name" defaultValue={provider.model_name} required />
            </div>
            <div className="field">
              <label>API Base URL / 网页入口</label>
              <input name="api_base_url" defaultValue={provider.api_base_url ?? ""} placeholder="例如 https://ccdan.cc.cd/v1 或 https://www.doubao.com" />
            </div>
            <div className="field">
              <label>API Key</label>
              <input name="api_key" type="password" placeholder="留空则保留已配置 Key" autoComplete="off" />
            </div>
            <div className="field">
              <label>状态</label>
              <select name="status" defaultValue={provider.status}>
                <option value="active">active</option>
                <option value="inactive">inactive</option>
              </select>
            </div>
          </div>
          <div className="grid cols-3">
            <div className="field">
              <label>输入单价 / 1k token</label>
              <input
                name="input_per_1k"
                type="number"
                min="0"
                step="0.000001"
                defaultValue={numberDefault(provider.cost_rule.input_per_1k)}
              />
            </div>
            <div className="field">
              <label>输出单价 / 1k token</label>
              <input
                name="output_per_1k"
                type="number"
                min="0"
                step="0.000001"
                defaultValue={numberDefault(provider.cost_rule.output_per_1k)}
              />
            </div>
            <div className="field">
              <label>币种</label>
              <input name="currency" defaultValue={String(provider.cost_rule.currency ?? "USD")} />
            </div>
          </div>
          <div className="field">
            <label>超时时间（秒）</label>
            <input
              name="timeout_seconds"
              type="number"
              min="1"
              defaultValue={numberDefault(provider.cost_rule.timeout_seconds, 120)}
            />
          </div>
          {provider.provider_type === "deepseek_web_search" ? (
            <div className="notice">
              DeepSeek 渠道固定启用官方 Web Search。测试只有在同时拿到最终回答和可追溯搜索来源时才算成功。
            </div>
          ) : (
            <label className="checkline">
              <input
                name="enable_search"
                type="checkbox"
                defaultChecked={Boolean(provider.cost_rule.enable_search)}
              />
              <span>启用兼容接口联网搜索（适用于千问/DashScope 支持搜索的模型）</span>
            </label>
          )}
          <SubmitButton pendingText="更新中...">更新配置</SubmitButton>
        </form>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>发起测试</h2>
          <form action={testProvider} className="form">
            {returnTo ? <input type="hidden" name="return_to" value={returnTo} /> : null}
            <div className="field">
              <label>目标问题</label>
              <input name="prompt_text" defaultValue={promptText} />
            </div>
            <div className="field">
              <label>企业名称</label>
              <input name="company_name" defaultValue="示例企业" />
            </div>
            <div className="field">
              <label>行业</label>
              <input name="industry" defaultValue="网络安全" />
            </div>
            <SubmitButton pendingText="测试中...">测试调用</SubmitButton>
          </form>
        </div>

        <div className="panel">
          <h2>测试结果</h2>
          {!hasResult ? (
            <p className="subtle">还没有测试结果。</p>
          ) : (
            <div className="stack">
              <span className="tag">{ok ? "调用成功" : "调用失败"}</span>
              {result.error ? <p className="subtle">{result.error}</p> : null}
              {result.summary ? (
                <div>
                  <h3>摘要</h3>
                  <p className="subtle">{result.summary}</p>
                </div>
              ) : null}
              {result.preview ? (
                <div>
                  <h3>答案预览</h3>
                  <p className="content">{result.preview}</p>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </section>

      <section className="panel">
        <h2>测试历史</h2>
        <div className="list">
          {runs.length === 0 ? (
            <p className="subtle">暂无历史测试。</p>
          ) : (
            runs.map((run) => (
              <div className="row" key={run.id ?? `${run.provider_id}-${run.created_at}`}>
                <div>
                  <h3>{run.ok ? "调用成功" : "调用失败"}</h3>
                  <small>
                    {run.created_at ?? "未知时间"}｜{run.latency_ms ?? 0}ms｜{run.prompt_text}
                  </small>
                  <p className="subtle">{run.error_message ?? run.answer_summary ?? ""}</p>
                </div>
                <span className="tag">{run.ok ? "healthy" : "failed"}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
