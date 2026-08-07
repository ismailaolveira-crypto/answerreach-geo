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
    description: "Moonshot 官方工具 + 联网搜索",
    defaultProviderType: "kimi_web_search",
    defaultModel: "kimi-k2.5",
    defaultBaseUrl: "https://api.moonshot.ai/v1",
    modelOptions: [
      { value: "kimi-k2.5", label: "Kimi K2.5" },
      { value: "kimi-k2-0711-preview", label: "Kimi K2" },
    ],
  },
  {
    key: "hunyuan",
    label: "腾讯混元",
    brand: "hunyuan",
    description: "腾讯混元官方 API + 强制搜索增强",
    defaultProviderType: "hunyuan_web_search",
    defaultModel: "hunyuan-turbos-latest",
    defaultBaseUrl: "https://api.hunyuan.cloud.tencent.com/v1",
    modelOptions: [
      { value: "hunyuan-turbos-latest", label: "混元 TurboS" },
      { value: "hunyuan-large", label: "混元 Large" },
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
