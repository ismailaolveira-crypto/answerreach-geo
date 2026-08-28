"use client";

import { useState } from "react";
import {
	discoverGeoArticleAssistantAccounts,
	getGeoArticleAssistantApi,
	type GeoArticleAssistantPlatformKey,
} from "@/lib/geo-article-assistant-bridge";
import type { AgentRuntime, WorkspaceIntegrationSettings } from "@/lib/cleanroom-v1-api";
import { runAgentRuntimeTest } from "./actions";
import styles from "./settings.module.css";

type Feedback = { kind: "success" | "warning" | "error" | "idle"; message?: string };
type PageSyncState = "unchecked" | "ready" | "missing" | "no_accounts" | "error";
type PageSyncPlatform = GeoArticleAssistantPlatformKey;

const pageSyncPlatformMeta: Record<PageSyncPlatform, { label: string; logo: string }> = {
	zhihu: { label: "知乎", logo: "/brand/zhihu.svg" },
	juejin: { label: "掘金", logo: "/brand/platforms/juejin.png" },
	csdn: { label: "CSDN", logo: "/brand/platforms/csdn.ico" },
	"51cto": { label: "51CTO", logo: "/brand/platforms/51cto.png" },
	wechat: { label: "微信公众号", logo: "/brand/wechat.svg" },
	bilibili: { label: "哔哩哔哩", logo: "/brand/platforms/bilibili.ico" },
	baijiahao: { label: "百家号", logo: "/brand/platforms/baijiahao.ico" },
	weibo: { label: "微博", logo: "/brand/platforms/weibo.ico" },
	yuque: { label: "语雀", logo: "/brand/platforms/yuque.png" },
	douban: { label: "豆瓣", logo: "/brand/platforms/douban.ico" },
	sohu: { label: "搜狐号", logo: "/brand/platforms/sohu.ico" },
	xueqiu: { label: "雪球", logo: "/brand/platforms/xueqiu.ico" },
	cnblogs: { label: "博客园", logo: "/brand/platforms/cnblogs.ico" },
	oschina: { label: "开源中国", logo: "/brand/platforms/oschina.ico" },
	segmentfault: { label: "思否", logo: "/brand/platforms/segmentfault.png" },
	imooc: { label: "慕课手记", logo: "/brand/platforms/imooc.ico" },
	woshipm: { label: "人人都是产品经理", logo: "/brand/platforms/woshipm.ico" },
	eastmoney: { label: "东方财富", logo: "/brand/platforms/eastmoney.ico" },
};
const pageSyncPlatformOrder: PageSyncPlatform[] = ["zhihu", "juejin", "csdn", "51cto", "wechat"];

export function IntegrationSettingsForm({ workspaceId, initialSettings: _initialSettings, initialRuntime, readOnly = false }: { workspaceId: number; initialSettings: WorkspaceIntegrationSettings | null; initialRuntime: AgentRuntime | null; readOnly?: boolean }) {
	void _initialSettings; // Legacy MCP values remain readable for migration but are no longer exposed in product UI.
	const [runtime, setRuntime] = useState<AgentRuntime | null>(initialRuntime);
	const [pageSyncState, setPageSyncState] = useState<PageSyncState>("unchecked");
	const [pageSyncSummary, setPageSyncSummary] = useState("尚未检测当前页面");
	const [pageSyncPlatforms, setPageSyncPlatforms] = useState<PageSyncPlatform[]>([]);
	const [pageSyncVersion, setPageSyncVersion] = useState<string | null>(null);
	const [testing, setTesting] = useState<"local_codex" | "article_sync_page" | null>(null);
	const [feedback, setFeedback] = useState<Feedback>({ kind: "idle" });
	const assistantConnected = ["ready", "no_accounts"].includes(pageSyncState);

	async function testPageSync() {
		setTesting("article_sync_page");
		setFeedback({ kind: "idle" });
		const api = getGeoArticleAssistantApi();
		if (!api) {
			setPageSyncState("missing");
			setPageSyncSummary("当前页面未检测到扩展");
			setPageSyncPlatforms([]);
			setPageSyncVersion(null);
			setFeedback({ kind: "error", message: "请先启用 GEO 文章助手，然后刷新本页。不需要配置第三方路径或 Token。" });
			setTesting(null);
			return;
		}
		try {
			const health = await api.health();
			setPageSyncVersion(health.extensionVersion);
			const accounts = await discoverGeoArticleAssistantAccounts(api);
			const platformAccounts = accounts.map((account) => account.platformKey);
			const platforms = [...new Set<PageSyncPlatform>(platformAccounts)];
			if (!platformAccounts.length) {
				setPageSyncState("no_accounts");
				setPageSyncSummary("扩展已连接，尚未读取到可用平台账号");
				setPageSyncPlatforms([]);
				setFeedback({ kind: "warning", message: "GEO 文章助手已连接，但当前浏览器还没有登录可用的目标平台账号。" });
				return;
			}
			setPageSyncState("ready");
			setPageSyncPlatforms(platforms);
			setPageSyncSummary(`${platformAccounts.length} 个可用账号 · ${platforms.map((item) => pageSyncPlatformMeta[item].label).join("、")}`);
			setFeedback({ kind: "success", message: `已从当前页面真实读取 ${platformAccounts.length} 个可写入平台账号。只有审核通过并由你确认后，系统才会逐平台写入草稿。` });
		} catch (error) {
			setPageSyncState("error");
			setPageSyncSummary("扩展已检测，但账号读取失败");
			setPageSyncPlatforms([]);
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "GEO 文章助手检测失败。" });
		} finally {
			setTesting(null);
		}
	}

	async function testCodex() {
		setTesting("local_codex");
		setFeedback({ kind: "idle" });
		try {
			const result = await runAgentRuntimeTest(workspaceId);
			setRuntime(result.runtime);
			setFeedback({
				kind: result.ok ? "success" : "error",
				message: result.ok
					? `本机 Codex 已完成真实结构化 turn（${result.latency_ms} ms）。`
					: result.error || "Codex 自检失败。",
			});
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "Codex 自检失败。" });
		} finally {
			setTesting(null);
		}
	}

	return <section className={styles.integrationCard}>
		<header className={styles.integrationHeader}><div><h2>Agent 与交付</h2><p>配置 Agent 与内容交付通路，确保仅写入平台草稿，不代替发布。</p></div></header>
		<div className={styles.integrationGrid}>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>Local Codex Agent</b><small>本机运行时状态</small></div><span className={runtime?.ready ? styles.laneReady : styles.lanePending}><i className={runtime?.ready ? styles.dotReady : styles.dotPending} />{runtime?.ready ? "已就绪" : "等待自检"}</span></div>
				<dl className={styles.runtimeFacts}><div><dt>ChatGPT 账号</dt><dd>{runtime?.login_status === "chatgpt_authenticated" ? "ChatGPT 已登录" : runtime?.login_status || "检测后显示"}</dd></div><div><dt>默认模型</dt><dd>{runtime?.default_model || "检测后显示"}</dd></div><div><dt>SDK 版本</dt><dd>{runtime?.sdk_version || "检测后显示"}</dd></div><div><dt>隐私与凭证</dt><dd>不保存 API Key</dd></div></dl>
				<p className={styles.runtimeNote}>不保存 API Key。Agent 仅在隔离目录写入中间工件，内容生成后停在人工审核。</p>
				{!readOnly ? <button type="button" className={styles.testButton} onClick={testCodex} disabled={testing !== null}>{testing === "local_codex" ? "正在执行真实 turn…" : "运行 Codex 自检"}</button> : null}
			</div>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>GEO 文章助手</b><small>{pageSyncVersion ? `v${pageSyncVersion} · 只写草稿 · 最小权限` : pageSyncSummary}</small></div><span className={assistantConnected ? styles.laneReady : styles.lanePending}><i className={assistantConnected ? styles.dotReady : styles.dotPending} />{assistantConnected ? "已连接" : pageSyncState === "missing" ? "未连接" : pageSyncState === "error" ? "连接异常" : "尚未检测"}</span></div>
				<div className={styles.currentPageStatus}><span>当前页面检测状态</span><b>{pageSyncState === "unchecked" ? "尚未检测当前页面" : pageSyncSummary}</b></div>
				<div className={styles.syncPlatformList} aria-label="GEO 文章助手支持平台">{pageSyncPlatformOrder.map((platform) => { const available = pageSyncPlatforms.includes(platform); const status = available ? "账号可用" : assistantConnected ? platform === "csdn" ? "需官方授权" : "未登录" : platform === "csdn" ? "需官方授权" : "支持检测"; return <span key={platform} className={available ? styles.syncPlatformAvailable : ""}><img src={pageSyncPlatformMeta[platform].logo} alt={`${pageSyncPlatformMeta[platform].label} 官方标志`} /><b>{pageSyncPlatformMeta[platform].label}</b><small>{status}</small></span>; })}</div>
				<div className={styles.assistantActions}><a href="/downloads/geo-article-assistant-0.3.0.zip" download>下载扩展包</a><button type="button" className={styles.testButton} onClick={testPageSync} disabled={testing !== null}>{testing === "article_sync_page" ? "正在读取登录账号…" : assistantConnected ? "重新检测 GEO 文章助手" : "检测当前页面"}</button></div>
			</div>
		</div>
		<section className={styles.deliveryPath}><header><h3>交付路径</h3><span>仅写入草稿，最终发布始终由用户完成</span></header><ol><li><i>1</i><div><b>Agent 生成草稿</b><small>基于事实证据与品牌口径</small></div></li><li><i>2</i><div><b>人工审核</b><small>逐稿检查并确认内容</small></div></li><li><i>3</i><div><b>GEO 文章助手写入草稿箱</b><small>只传递已审核版本，登录态留在本机</small></div></li><li><i>4</i><div><b>用户在目标平台确认发布</b><small>最终发布始终由用户完成</small></div></li></ol></section>
		<p className={styles.integrationHint}>Codex 自检只证明本机运行时可用；同步检测只证明当前页面可发现扩展与账号。二者都不代表任务已执行、草稿已保存或内容已发布。</p>
		{feedback.message ? <p className={`${styles.feedback} ${feedback.kind === "error" ? styles.error : feedback.kind === "warning" ? styles.warning : styles.success}`} role="status">{feedback.message}</p> : null}
	</section>;
}
