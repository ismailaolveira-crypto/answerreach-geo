export type GeoScopePreset = "7d" | "30d" | "90d" | "365d" | "custom";

export type GeoGlobalScope = {
	version: 1;
	workspace_id: number;
	range: GeoScopePreset;
	date_from: string;
	date_to: string;
	batch_ids: number[];
	model_keys: string[];
	question_plan_ids: number[];
	mode: "single" | "historical";
	fingerprint: string;
};

export type GeoGlobalScopeOptions = {
	scope: GeoGlobalScope;
	batches: Array<{
		id: number;
		label: string;
		status: string;
		source_type: string;
		created_at: string;
		completed_at: string | null;
		provider_count: number;
		question_count: number;
		model_keys: string[];
		question_plan_ids: number[];
	}>;
	models: Array<{ key: string; label: string; logo_key: string | null; observation_count: number }>;
	questions: Array<{ id: number; label: string; importance: number; journey_stage: string }>;
	corrections: string[];
	capabilities: Record<string, boolean>;
};

export const GEO_SCOPE_KEYS = ["range", "from", "to", "batch", "model", "question"] as const;
export const GEO_SCOPE_LEGACY_KEYS = ["period_days"] as const;

export function hasGeoScope(searchParams: URLSearchParams): boolean {
	return GEO_SCOPE_KEYS.some((key) => searchParams.has(key));
}

export function scopeOnlySearchParams(searchParams: URLSearchParams): URLSearchParams {
	const next = new URLSearchParams();
	for (const key of [...GEO_SCOPE_KEYS, ...GEO_SCOPE_LEGACY_KEYS, "period"] as const) {
		for (const value of searchParams.getAll(key)) next.append(key, value);
	}
	return next;
}

export function writeGeoScope(searchParams: URLSearchParams, scope: GeoGlobalScope): URLSearchParams {
	const next = new URLSearchParams(searchParams);
	for (const key of [...GEO_SCOPE_KEYS, ...GEO_SCOPE_LEGACY_KEYS, "period"] as const) next.delete(key);
	next.set("range", scope.range);
	if (scope.range === "custom") {
		next.set("from", scope.date_from);
		next.set("to", scope.date_to);
	}
	for (const value of [...new Set(scope.batch_ids)].sort((a, b) => a - b)) next.append("batch", String(value));
	for (const value of [...new Set(scope.model_keys)].sort()) next.append("model", value);
	for (const value of [...new Set(scope.question_plan_ids)].sort((a, b) => a - b)) next.append("question", String(value));
	return next;
}

export function preserveGeoScopeInHref(href: string, current: URLSearchParams): string {
	if (!href.startsWith("/geo/")) return href;
	const [path, rawQuery = ""] = href.split("?", 2);
	const next = new URLSearchParams(rawQuery);
	for (const key of GEO_SCOPE_KEYS) {
		next.delete(key);
		for (const value of current.getAll(key)) next.append(key, value);
	}
	const query = next.toString();
	return query ? `${path}?${query}` : path;
}

export function modelLogoPath(modelKey: string): string | null {
	const key = modelKey.toLowerCase();
	if (key.includes("deepseek")) return "/brand/deepseek.svg";
	if (key.includes("doubao")) return "/brand/doubao.png";
	if (key.includes("qwen") || key.includes("qianwen")) return "/brand/qwen.png";
	if (key.includes("glm") || key.includes("zhipu")) return "/brand/glm.svg";
	if (key.includes("kimi") || key.includes("moonshot")) return "/brand/kimi.ico";
	if (key.includes("yuanbao") || key.includes("hunyuan")) return "/brand/yuanbao.png";
	if (key.includes("claude")) return "/brand/claude.svg";
	if (key.includes("openai") || key.includes("gpt")) return "/brand/openai.svg";
	return null;
}
