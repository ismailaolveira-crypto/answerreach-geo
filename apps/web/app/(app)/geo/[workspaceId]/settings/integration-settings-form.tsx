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

export function IntegrationSettingsForm({ workspaceId, initialSettings, initialRuntime }: { workspaceId: number; initialSettings: WorkspaceIntegrationSettings | null; initialRuntime: AgentRuntime | null }) {
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
		<header className={styles.integrationHeader}><div><span className={styles.integrationEyebrow}>05 · Agent 与草稿交付</span><h2>本机 Codex 与文章同步</h2><p>Codex 负责调研、写作和平台适配；人工审核后，再由 EgoLite 里的文章同步助手写入草稿箱。</p></div><span className={runtime?.ready && deliveryReady ? styles.integrationReady : styles.integrationPending}>{runtime?.ready && deliveryReady ? "执行与交付均就绪" : runtime?.ready ? "Agent 已就绪 · 检测交付" : "检查本机状态"}</span></header>
		<div className={styles.integrationGrid}>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>Local Codex Agent</b><small>{runtime?.ready ? "已复用本机 ChatGPT 登录" : "未就绪"}</small></div><i className={runtime?.ready ? styles.dotReady : styles.dotPending} /></div>
				<dl className={styles.runtimeFacts}><div><dt>认证</dt><dd>{runtime?.login_status === "chatgpt_authenticated" ? "ChatGPT 已登录" : runtime?.login_status || "无法读取"}</dd></div><div><dt>默认模型</dt><dd>{runtime?.default_model || "—"}</dd></div><div><dt>SDK</dt><dd>{runtime?.sdk_version || "—"}</dd></div></dl>
				<p className={styles.runtimeNote}>不保存 API Key。Agent 仅在隔离目录写入中间工件，内容生成后停在人工审核。</p>
				<button type="button" className={styles.testButton} onClick={testCodex} disabled={testing !== null || saving}>{testing === "local_codex" ? "正在执行真实 turn…" : "运行 Codex 自检"}</button>
			</div>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>EgoLite 文章同步助手</b><small>{pageSyncSummary}</small></div><i className={deliveryReady ? styles.dotReady : styles.dotPending} /></div>
				<dl className={styles.runtimeFacts}><div><dt>触发方式</dt><dd>审核后网页确认</dd></div><div><dt>写入范围</dt><dd>仅平台草稿</dd></div><div><dt>最终发布</dt><dd>始终由人工完成</dd></div></dl>
				<div className={styles.syncPlatformList} aria-label="文章同步助手支持平台">{pageSyncPlatformOrder.map((platform) => { const available = pageSyncPlatforms.includes(platform); return <span key={platform} className={available ? styles.syncPlatformAvailable : ""}><img src={pageSyncPlatformMeta[platform].logo} alt={`${pageSyncPlatformMeta[platform].label} 官方标志`} /><b>{pageSyncPlatformMeta[platform].label}</b><small>{available ? "账号可用" : "支持检测"}</small></span>; })}</div>
				<p className={styles.runtimeNote}>检测的是当前浏览器页面里的真实扩展和登录账号；保存 MCP 路径并不能代表 EgoLite 已连接。</p>
				<button type="button" className={styles.testButton} onClick={testPageSync} disabled={testing !== null || saving}>{testing === "article_sync_page" ? "正在读取登录账号…" : pageSyncState === "ready" ? "重新检测同步助手" : "检测当前页面"}</button>
			</div>
		</div>
		<p className={styles.integrationHint}>Codex 直接复用本机登录，无需配置中转站或模型 Key。常规交付也无需填写 MCP 路径：请在 EgoLite 中打开工作台，审核内容后点击“打开文章同步助手”。</p>
		{feedback.message ? <p className={`${styles.feedback} ${feedback.kind === "error" ? styles.error : styles.success}`} role="status">{feedback.message}</p> : null}
		<details className={styles.integrationAdvanced}>
			<summary><span><b>高级：后台 MCP 通道</b><small>不影响网页点击同步；仅用于后台诊断与自动化实验</small></span><em>{mcpStatusLabel(mcpConfigured)}</em></summary>
			<div className={styles.integrationAdvancedBody}>
				<label>MCP Server 文件路径<input type="text" value={mcpServerPath} onChange={(event) => setMcpServerPath(event.target.value)} placeholder="/path/to/Wechatsync/packages/mcp-server/dist/index.js" autoComplete="off" spellCheck={false} /></label>
				<label>MCP Token<input type="password" value={mcpToken} onChange={(event) => setMcpToken(event.target.value)} placeholder={settings?.article_sync_mcp_token_configured ? "已配置；留空保持不变" : "粘贴 MCP Token"} autoComplete="new-password" spellCheck={false} /></label>
				<div><button type="button" className={styles.testButton} onClick={testMcp} disabled={testing !== null || saving}>{testing === "article_sync_mcp" ? "正在发现后台能力…" : "测试后台 MCP"}</button><button type="button" className={styles.integrationSave} onClick={save} disabled={saving || testing !== null}>{saving ? "正在保存…" : "保存高级配置"}</button></div>
			</div>
		</details>
	</section>;
}
