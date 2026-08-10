"use client";

import { useState } from "react";
import {
	articleSyncPlatformKey,
	discoverArticleSyncAccounts,
	getArticleSyncPageApi,
	type ArticleSyncPlatformKey,
} from "@/lib/article-sync-page-bridge";
import type { AgentRuntime, WorkspaceIntegrationSettings } from "@/lib/cleanroom-v1-api";
import { runAgentRuntimeTest, runWorkspaceIntegrationTest, saveWorkspaceIntegrations } from "./actions";
import styles from "./settings.module.css";

type Feedback = { kind: "success" | "error" | "idle"; message?: string };
type PageSyncState = "unchecked" | "ready" | "missing" | "no_accounts" | "error";
type PageSyncPlatform = ArticleSyncPlatformKey;

const pageSyncPlatformMeta: Record<PageSyncPlatform, { label: string; logo: string }> = {
	zhihu: { label: "知乎", logo: "/brand/zhihu.svg" },
	juejin: { label: "掘金", logo: "https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/static/favicons/favicon-32x32.png" },
	csdn: { label: "CSDN", logo: "https://g.csdnimg.cn/static/logo/favicon32.ico" },
	"51cto": { label: "51CTO", logo: "https://blog.51cto.com/favicon.ico" },
	wechat: { label: "微信公众号", logo: "/brand/wechat.svg" },
};
const pageSyncPlatformOrder: PageSyncPlatform[] = ["zhihu", "juejin", "csdn", "51cto", "wechat"];

function mcpStatusLabel(configured: boolean) {
	return configured ? "已配置（密钥不回显）" : "未配置";
}

export function IntegrationSettingsForm({ workspaceId, initialSettings, initialRuntime, readOnly = false }: { workspaceId: number; initialSettings: WorkspaceIntegrationSettings | null; initialRuntime: AgentRuntime | null; readOnly?: boolean }) {
	const [settings, setSettings] = useState<WorkspaceIntegrationSettings | null>(initialSettings);
	const [runtime, setRuntime] = useState<AgentRuntime | null>(initialRuntime);
	const mcpConfigured = Boolean(settings?.article_sync_mcp_server_path && settings.article_sync_mcp_token_configured);
	const [mcpServerPath, setMcpServerPath] = useState(initialSettings?.article_sync_mcp_server_path ?? "");
	const [mcpToken, setMcpToken] = useState("");
	const [pageSyncState, setPageSyncState] = useState<PageSyncState>("unchecked");
	const [pageSyncSummary, setPageSyncSummary] = useState("尚未检测当前页面");
	const [pageSyncPlatforms, setPageSyncPlatforms] = useState<PageSyncPlatform[]>([]);
	const [saving, setSaving] = useState(false);
	const [testing, setTesting] = useState<"local_codex" | "article_sync_page" | "article_sync_mcp" | null>(null);
	const [feedback, setFeedback] = useState<Feedback>({ kind: "idle" });
	const deliveryReady = pageSyncState === "ready";

	async function save() {
		if (!mcpServerPath.trim() && !mcpToken.trim()) {
			setFeedback({ kind: "error", message: "至少填写一项新配置；留空字段会保持原值。" });
			return;
		}
		setSaving(true);
		setFeedback({ kind: "idle" });
		try {
			const value = await saveWorkspaceIntegrations(workspaceId, {
				...(mcpServerPath.trim() ? { article_sync_mcp_server_path: mcpServerPath.trim() } : {}),
				...(mcpToken.trim() ? { article_sync_mcp_token: mcpToken.trim() } : {}),
			});
			setSettings(value);
			setMcpToken("");
			setFeedback({ kind: "success", message: "高级配置已加密保存。系统不会在页面、日志或 API 响应中回显密钥。" });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "保存失败，请稍后重试。" });
		} finally {
			setSaving(false);
		}
	}

	async function testMcp() {
		setTesting("article_sync_mcp");
		setFeedback({ kind: "idle" });
		try {
			const result = await runWorkspaceIntegrationTest(workspaceId, "article_sync_mcp");
			setFeedback({ kind: result.ok ? "success" : "error", message: `${result.message}${result.latency_ms ? `（${result.latency_ms} ms）` : ""}` });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "测试失败，请稍后重试。" });
		} finally {
			setTesting(null);
		}
	}

	async function testPageSync() {
		setTesting("article_sync_page");
		setFeedback({ kind: "idle" });
		const api = getArticleSyncPageApi();
		if (!api) {
			setPageSyncState("missing");
			setPageSyncSummary("当前页面未检测到扩展");
			setPageSyncPlatforms([]);
			setFeedback({ kind: "error", message: "请使用已安装文章同步助手的 EgoLite 打开本页面，确认扩展已启用后刷新。无需填写 MCP 文件路径。" });
			setTesting(null);
			return;
		}
		try {
			const accounts = await discoverArticleSyncAccounts(api, 60_000);
			const platformAccounts = accounts.flatMap<PageSyncPlatform>((account) => {
				const platform = articleSyncPlatformKey(account);
				return platform ? [platform] : [];
			});
			const platforms = [...new Set<PageSyncPlatform>(platformAccounts)];
			if (!platformAccounts.length) {
				setPageSyncState("no_accounts");
				setPageSyncSummary("扩展已连接，尚未读取到可用平台账号");
				setPageSyncPlatforms([]);
				setFeedback({ kind: "error", message: "文章同步助手已连接，但没有读取到登录账号。请先在 EgoLite 中登录目标平台，再重新检测。" });
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
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "同步助手检测失败。" });
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
				{!readOnly ? <button type="button" className={styles.testButton} onClick={testCodex} disabled={testing !== null || saving}>{testing === "local_codex" ? "正在执行真实 turn…" : "运行 Codex 自检"}</button> : null}
			</div>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>EgoLite 文章同步助手</b><small>{pageSyncSummary}</small></div><span className={deliveryReady ? styles.laneReady : styles.lanePending}><i className={deliveryReady ? styles.dotReady : styles.dotPending} />{deliveryReady ? "页面已检测" : "尚未检测"}</span></div>
				<div className={styles.currentPageStatus}><span>当前页面检测状态</span><b>{pageSyncState === "unchecked" ? "尚未检测当前页面" : pageSyncSummary}</b></div>
				<div className={styles.syncPlatformList} aria-label="文章同步助手支持平台">{pageSyncPlatformOrder.map((platform) => { const available = pageSyncPlatforms.includes(platform); return <span key={platform} className={available ? styles.syncPlatformAvailable : ""}><img src={pageSyncPlatformMeta[platform].logo} alt={`${pageSyncPlatformMeta[platform].label} 官方标志`} /><b>{pageSyncPlatformMeta[platform].label}</b><small>{available ? "账号可用" : "支持检测"}</small></span>; })}</div>
				<button type="button" className={styles.testButton} onClick={testPageSync} disabled={testing !== null || saving}>{testing === "article_sync_page" ? "正在读取登录账号…" : pageSyncState === "ready" ? "重新检测同步助手" : "检测当前页面"}</button>
			</div>
		</div>
		<section className={styles.deliveryPath}><header><h3>交付路径</h3><span>仅写入草稿，最终发布始终由用户完成</span></header><ol><li><i>1</i><div><b>Agent 生成草稿</b><small>基于事实证据与品牌口径</small></div></li><li><i>2</i><div><b>人工审核</b><small>逐稿检查并确认内容</small></div></li><li><i>3</i><div><b>EgoLite 写入平台草稿箱</b><small>同步请求不等于草稿已保存</small></div></li><li><i>4</i><div><b>用户在目标平台确认发布</b><small>最终发布始终由用户完成</small></div></li></ol></section>
		<p className={styles.integrationHint}>Codex 自检只证明本机运行时可用；同步检测只证明当前页面可发现扩展与账号。二者都不代表任务已执行、草稿已保存或内容已发布。</p>
		{feedback.message ? <p className={`${styles.feedback} ${feedback.kind === "error" ? styles.error : styles.success}`} role="status">{feedback.message}</p> : null}
		{!readOnly ? <details className={styles.integrationAdvanced}>
			<summary><span><b>高级：后台 MCP 通道</b><small>仅用于后台诊断与自动化实验，不影响网页点击同步</small></span><em>{mcpStatusLabel(mcpConfigured)}</em></summary>
			<div className={styles.integrationAdvancedBody}>
				<label>MCP Server 文件路径<input type="text" value={mcpServerPath} onChange={(event) => setMcpServerPath(event.target.value)} placeholder="/path/to/Wechatsync/packages/mcp-server/dist/index.js" autoComplete="off" spellCheck={false} /></label>
				<label>MCP Token<input type="password" value={mcpToken} onChange={(event) => setMcpToken(event.target.value)} placeholder={settings?.article_sync_mcp_token_configured ? "已配置；留空保持不变" : "粘贴 MCP Token"} autoComplete="new-password" spellCheck={false} /></label>
				<div><button type="button" className={styles.testButton} onClick={testMcp} disabled={testing !== null || saving}>{testing === "article_sync_mcp" ? "正在发现后台能力…" : "测试后台 MCP"}</button><button type="button" className={styles.integrationSave} onClick={save} disabled={saving || testing !== null}>{saving ? "正在保存…" : "保存高级配置"}</button></div>
			</div>
		</details> : null}
	</section>;
}
