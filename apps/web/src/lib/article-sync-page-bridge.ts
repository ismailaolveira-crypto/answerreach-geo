export type ArticleSyncAccount = {
	type: string;
	title: string;
	displayName?: string;
	uid?: string;
	icon?: string;
	avatar?: string;
	home?: string;
	status?: "pending" | "uploading" | "done" | "failed";
	msg?: string;
	error?: string;
	editResp?: { draftLink?: string } | null;
};

export type ArticleSyncPageApi = {
	getAccounts: (callback: (first: unknown, second?: unknown) => void) => void;
	addTask: (
		task: { post: { title: string; content: string; markdown: string }; accounts: ArticleSyncAccount[] },
		statusHandler: (task: { accounts?: ArticleSyncAccount[] }) => void,
		callback: (first?: unknown, second?: unknown) => void,
	) => void;
};

export function getArticleSyncPageApi() {
	if (typeof window === "undefined") return null;
	return (window as Window & { $syncer?: ArticleSyncPageApi }).$syncer ?? null;
}

export type ArticleSyncPlatformKey = "zhihu" | "juejin" | "csdn" | "51cto" | "wechat";

export function articleSyncPlatformKey(account: ArticleSyncAccount): ArticleSyncPlatformKey | null {
	const value = `${account.type} ${account.title} ${account.displayName || ""}`.toLowerCase();
	if (value.includes("zhihu") || value.includes("知乎")) return "zhihu";
	if (value.includes("juejin") || value.includes("掘金")) return "juejin";
	if (value.includes("csdn")) return "csdn";
	if (value.includes("51cto") || value.includes("cto51")) return "51cto";
	if (value.includes("wechat") || value.includes("weixin") || value.includes("微信") || value.includes("公众号")) return "wechat";
	return null;
}

export function articleSyncAccountKey(account: ArticleSyncAccount) {
	return `${account.type}::${account.uid || account.displayName || account.title}`;
}

export function discoverArticleSyncAccounts(api: ArticleSyncPageApi, timeoutMs = 180_000) {
	return new Promise<ArticleSyncAccount[]>((resolve, reject) => {
		const timeout = window.setTimeout(() => reject(new Error("平台登录检查超时，请打开文章同步助手确认登录状态。")), timeoutMs);
		api.getAccounts((first, second) => {
			window.clearTimeout(timeout);
			const value = Array.isArray(second) ? second : Array.isArray(first) ? first : [];
			resolve(value as ArticleSyncAccount[]);
		});
	});
}
