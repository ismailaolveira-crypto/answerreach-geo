"use client";

import { useState } from "react";
import type { WorkspaceIntegrationSettings } from "@/lib/cleanroom-v1-api";
import { runWorkspaceIntegrationTest, saveWorkspaceIntegrations } from "./actions";
import styles from "./settings.module.css";

type Feedback = { kind: "success" | "error" | "idle"; message?: string };

function statusLabel(configured: boolean) {
	return configured ? "已配置（密钥不回显）" : "尚未配置";
}

export function IntegrationSettingsForm({ workspaceId, initialSettings }: { workspaceId: number; initialSettings: WorkspaceIntegrationSettings | null }) {
	const [settings, setSettings] = useState<WorkspaceIntegrationSettings | null>(initialSettings);
	const mcpConfigured = Boolean(settings?.article_sync_mcp_server_path && settings.article_sync_mcp_token_configured);
	const [deepseekKey, setDeepseekKey] = useState("");
	const [mcpServerPath, setMcpServerPath] = useState(initialSettings?.article_sync_mcp_server_path ?? "");
	const [mcpToken, setMcpToken] = useState("");
	const [saving, setSaving] = useState(false);
	const [testing, setTesting] = useState<"deepseek" | "article_sync_mcp" | null>(null);
	const [feedback, setFeedback] = useState<Feedback>({ kind: "idle" });

	async function save() {
		if (!deepseekKey.trim() && !mcpServerPath.trim() && !mcpToken.trim()) {
			setFeedback({ kind: "error", message: "至少填写一项新配置；留空字段会保持原值。" });
			return;
		}
		setSaving(true);
		setFeedback({ kind: "idle" });
		try {
			const value = await saveWorkspaceIntegrations(workspaceId, {
				...(deepseekKey.trim() ? { deepseek_api_key: deepseekKey.trim() } : {}),
				...(mcpServerPath.trim() ? { article_sync_mcp_server_path: mcpServerPath.trim() } : {}),
				...(mcpToken.trim() ? { article_sync_mcp_token: mcpToken.trim() } : {}),
			});
			setSettings(value);
			setDeepseekKey("");
			setMcpToken("");
			setFeedback({ kind: "success", message: "配置已加密保存。系统不会在页面、日志或 API 响应中回显密钥。" });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "保存失败，请稍后重试。" });
		} finally {
			setSaving(false);
		}
	}

	async function test(integration: "deepseek" | "article_sync_mcp") {
		setTesting(integration);
		setFeedback({ kind: "idle" });
		try {
			const result = await runWorkspaceIntegrationTest(workspaceId, integration);
			setFeedback({ kind: result.ok ? "success" : "error", message: `${result.message}${result.latency_ms ? `（${result.latency_ms} ms）` : ""}` });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "测试失败，请稍后重试。" });
		} finally {
			setTesting(null);
		}
	}

	return <section className={styles.integrationCard}>
		<header className={styles.integrationHeader}><div><span className={styles.integrationEyebrow}>04 · 外部能力</span><h2>内容生成与文章同步</h2><p>用于从真实问题生成待审稿，并通过文章同步助手 MCP 写入指定平台草稿。</p></div><span className={settings?.deepseek_api_key_configured && mcpConfigured ? styles.integrationReady : styles.integrationPending}>{settings?.deepseek_api_key_configured && mcpConfigured ? "两项均已配置" : "等待配置"}</span></header>
		<div className={styles.integrationGrid}>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>DeepSeek 内容生成</b><small>{statusLabel(Boolean(settings?.deepseek_api_key_configured))}</small></div><i className={settings?.deepseek_api_key_configured ? styles.dotReady : styles.dotPending} /></div>
				<label>DeepSeek API Key<input type="password" value={deepseekKey} onChange={(event) => setDeepseekKey(event.target.value)} placeholder={settings?.deepseek_api_key_configured ? "已配置；留空保持不变" : "粘贴 API Key"} autoComplete="new-password" spellCheck={false} /></label>
				<button type="button" className={styles.testButton} onClick={() => test("deepseek")} disabled={testing !== null || saving}>{testing === "deepseek" ? "正在请求…" : "测试内容生成"}</button>
			</div>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>文章同步助手 MCP</b><small>{statusLabel(mcpConfigured)}</small></div><i className={mcpConfigured ? styles.dotReady : styles.dotPending} /></div>
				<label>MCP Server 文件路径<input type="text" value={mcpServerPath} onChange={(event) => setMcpServerPath(event.target.value)} placeholder="/path/to/Wechatsync/packages/mcp-server/dist/index.js" autoComplete="off" spellCheck={false} /></label>
				<label>MCP Token<input type="password" value={mcpToken} onChange={(event) => setMcpToken(event.target.value)} placeholder={settings?.article_sync_mcp_token_configured ? "已配置；留空保持不变" : "粘贴 MCP Token"} autoComplete="new-password" spellCheck={false} /></label>
				<button type="button" className={styles.testButton} onClick={() => test("article_sync_mcp")} disabled={testing !== null || saving}>{testing === "article_sync_mcp" ? "正在发现能力…" : "测试 MCP Server"}</button>
			</div>
		</div>
		<p className={styles.integrationHint}>GEO 会持续托管官方 MCP Server，无需手动启动。文章同步助手扩展是客户端：开启 MCP 连接并填写 <code>ws://localhost:9527</code> 后，会自动重连。扩展重连最多等待 35 秒；首次只读发现会检查 20+ 平台登录态，可能需要约 2 分钟。真正写入由“优先行动”页的人工确认触发，只写入所选平台草稿箱，不执行发布。</p>
		{feedback.message ? <p className={`${styles.feedback} ${feedback.kind === "error" ? styles.error : styles.success}`} role="status">{feedback.message}</p> : null}
		<button type="button" className={styles.integrationSave} onClick={save} disabled={saving || testing !== null}>{saving ? "正在保存…" : "保存外部能力配置"}</button>
	</section>;
}
