import type { GeoArticleAssistantTask } from "@/lib/cleanroom-v1-api";

export type GeoArticleAssistantPlatformKey =
	| "wechat" | "zhihu" | "juejin" | "51cto" | "csdn" | "bilibili"
	| "baijiahao" | "weibo" | "yuque" | "douban" | "sohu" | "xueqiu"
	| "cnblogs" | "oschina" | "segmentfault" | "imooc" | "woshipm" | "eastmoney";

export type GeoArticleAssistantAccount = {
	accountId: string;
	platformKey: GeoArticleAssistantPlatformKey;
	userId: string;
	displayName: string;
	avatar?: string;
	status?: "pending" | "uploading" | "done" | "failed";
	message?: string;
	draftUrl?: string;
};

export type GeoArticleAssistantResult = {
	platform_key: GeoArticleAssistantPlatformKey;
	request_status: "draft_link_returned" | "failed" | "cancelled";
	draft_url?: string | null;
	external_draft_id?: string | null;
	message?: string | null;
};

export type GeoArticleAssistantApi = {
	protocolVersion: "geo-article-assistant.v1";
	health: () => Promise<{
		protocolVersion: "geo-article-assistant.v1";
		extensionVersion: string;
		draftOnly: true;
		draftReceiptVersion: 1;
		supportedPlatforms: GeoArticleAssistantPlatformKey[];
		readyPlatforms: GeoArticleAssistantPlatformKey[];
		enabledPlatforms: GeoArticleAssistantPlatformKey[];
		unavailable: Partial<Record<GeoArticleAssistantPlatformKey, string>>;
	}>;
	getAccounts: () => Promise<GeoArticleAssistantAccount[]>;
	writeDrafts: (
		task: GeoArticleAssistantTask,
		accountSelections: Array<{ platformKey: GeoArticleAssistantPlatformKey; accountId: string }>,
	) => Promise<GeoArticleAssistantResult[]>;
};

declare global {
	interface Window {
		$geoArticleAssistant?: GeoArticleAssistantApi;
	}
}

export function getGeoArticleAssistantApi() {
	if (typeof window === "undefined") return null;
	const api = window.$geoArticleAssistant ?? null;
	return api?.protocolVersion === "geo-article-assistant.v1" ? api : null;
}

export function geoArticleAssistantAccountKey(account: GeoArticleAssistantAccount) {
	return account.accountId;
}

export async function discoverGeoArticleAssistantAccounts(api: GeoArticleAssistantApi) {
	const health = await api.health();
	if (!health.draftOnly || health.protocolVersion !== "geo-article-assistant.v1") {
		throw new Error("GEO 文章助手安全协议校验失败");
	}
	if (health.draftReceiptVersion !== 1) {
		throw new Error("GEO 文章助手版本过旧，请下载并安装最新版后刷新页面");
	}
	return api.getAccounts();
}
