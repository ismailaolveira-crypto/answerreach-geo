export type ProviderCatalogKey = "deepseek" | "doubao" | "qwen" | "glm" | "kimi" | "hunyuan" | "other";

export type ProviderCatalogItem = {
  key: ProviderCatalogKey;
  label: string;
  brand: "deepseek" | "doubao" | "qwen" | "glm" | "kimi" | "hunyuan";
  description: string;
  defaultProviderType: string;
  defaultModel: string;
  defaultBaseUrl: string;
  modelOptions: Array<{ value: string; label: string }>;
  apiEvidenceLabel?: string;
  officialWeb?: { label: string; url: string; observationPlatform: string };
};

export const PROVIDER_CATALOG: ProviderCatalogItem[] = [
  {
    key: "deepseek",
    label: "DeepSeek",
    brand: "deepseek",
    description: "官方 API + Web Search",
    defaultProviderType: "deepseek_web_search",
    defaultModel: "deepseek-v4-flash",
    defaultBaseUrl: "https://api.deepseek.com/anthropic",
    apiEvidenceLabel: "DeepSeek 官方 API 联网观测",
    officialWeb: { label: "DeepSeek 网页端", url: "https://chat.deepseek.com/", observationPlatform: "deepseek" },
    modelOptions: [
      { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
      { value: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
    ],
  },
  {
    key: "doubao",
    label: "豆包",
    brand: "doubao",
    description: "火山方舟 + 联网搜索",
    defaultProviderType: "volcengine_ark",
    defaultModel: "doubao-seed-2-1-pro-260628",
    defaultBaseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    modelOptions: [
      { value: "doubao-seed-2-1-pro-260628", label: "Doubao Seed 2.1 Pro" },
      { value: "doubao-seed-2-1-lite-260628", label: "Doubao Seed 2.1 Lite" },
    ],
  },
  {
    key: "qwen",
    label: "通义千问",
    brand: "qwen",
    description: "百炼官方 API + 联网搜索",
    defaultProviderType: "bailian_qwen_responses",
    defaultModel: "qwen3.5-plus",
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    modelOptions: [
      { value: "qwen3.5-plus", label: "Qwen 3.5 Plus" },
      { value: "qwen3.7-plus", label: "Qwen 3.7 Plus" },
      { value: "qwen-max", label: "Qwen Max" },
    ],
  },
  {
    key: "glm",
    label: "智谱 GLM",
    brand: "glm",
    description: "火山方舟 + 联网搜索",
    defaultProviderType: "volcengine_ark",
    defaultModel: "glm-5-2-260617",
    defaultBaseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    modelOptions: [
      { value: "glm-5-2-260617", label: "GLM 5.2" },
      { value: "glm-4-5", label: "GLM 4.5" },
    ],
  },
  {
    key: "kimi",
    label: "Kimi",
    brand: "kimi",
    description: "Moonshot Formula 官方 API + 联网搜索",
    defaultProviderType: "kimi_web_search",
    defaultModel: "kimi-k3",
    defaultBaseUrl: "https://api.moonshot.cn/v1",
    apiEvidenceLabel: "Kimi 官方 API 联网观测",
    officialWeb: { label: "Kimi 网页端", url: "https://www.kimi.com/", observationPlatform: "kimi" },
    modelOptions: [
      { value: "kimi-k3", label: "Kimi K3" },
      { value: "kimi-k2.6", label: "Kimi K2.6" },
      { value: "kimi-k2.5", label: "Kimi K2.5" },
    ],
  },
  {
    key: "hunyuan",
    label: "腾讯混元",
    brand: "hunyuan",
    description: "腾讯 TokenHub 官方 API + Web Search",
    defaultProviderType: "hunyuan_web_search",
    defaultModel: "hy3-preview",
    defaultBaseUrl: "https://tokenhub.tencentmaas.com/v1",
    apiEvidenceLabel: "混元 TokenHub 官方 API 联网观测",
    officialWeb: { label: "腾讯元宝网页端", url: "https://yuanbao.tencent.com/", observationPlatform: "yuanbao" },
    modelOptions: [
      { value: "hy3-preview", label: "Hy3 Preview" },
    ],
  },
];

export function providerMatchesCatalog(provider: { provider_type: string; name: string; model_name: string; cost_rule?: Record<string, unknown> }, key: ProviderCatalogKey): boolean {
  if (key === "other") return !PROVIDER_CATALOG.some((item) => providerMatchesCatalog(provider, item.key));
  const value = `${provider.name} ${provider.model_name}`.toLowerCase();
  const platformKey = String(provider.cost_rule?.platform_key ?? "").toLowerCase();
  const normalizedPlatformKey = platformKey === "qianwen" ? "qwen" : platformKey;
  if (normalizedPlatformKey && normalizedPlatformKey !== "other") return normalizedPlatformKey === key;
  if (key === "deepseek") return provider.provider_type === "deepseek_web_search" || value.includes("deepseek");
  if (key === "doubao") return (provider.provider_type === "volcengine_ark" && platformKey !== "glm") && (value.includes("doubao") || value.includes("豆包") || !value.includes("glm"));
  if (key === "qwen") return ["qwen_compatible", "bailian_qwen_responses"].includes(provider.provider_type) || value.includes("qwen") || value.includes("千问");
  if (key === "glm") return (provider.provider_type === "volcengine_ark" && platformKey === "glm") || value.includes("glm") || value.includes("智谱");
  if (key === "kimi") return provider.provider_type === "kimi_web_search" || value.includes("kimi") || value.includes("moonshot");
  if (key === "hunyuan") return provider.provider_type === "hunyuan_web_search" || value.includes("hunyuan") || value.includes("混元");
  return false;
}

export function catalogForProvider(provider: { provider_type: string; name: string; model_name: string; cost_rule?: Record<string, unknown> }) {
  return PROVIDER_CATALOG.find((item) => providerMatchesCatalog(provider, item.key));
}

export function isOfficialProvider(
  provider: { provider_type: string; name: string; cost_rule?: Record<string, unknown> },
  key: ProviderCatalogKey,
) {
  const catalog = PROVIDER_CATALOG.find((item) => item.key === key);
  if (!catalog) return false;
  const role = String(provider.cost_rule?.channel_role ?? "").toLowerCase();
  if (role === "custom" || role === "archived_duplicate") return false;
  if (role === "official") return true;
  if (key === "qwen") return ["qwen_compatible", "bailian_qwen_responses"].includes(provider.provider_type);
  return provider.provider_type === catalog.defaultProviderType && !/小马|mock|模拟/i.test(provider.name);
}
