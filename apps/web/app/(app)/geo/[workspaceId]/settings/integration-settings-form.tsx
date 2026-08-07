"use client";

import { useState } from "react";
import type { AgentRuntime, WorkspaceIntegrationSettings } from "@/lib/cleanroom-v1-api";
import { runAgentRuntimeTest, runWorkspaceIntegrationTest, saveWorkspaceIntegrations } from "./actions";
import styles from "./settings.module.css";

type Feedback = { kind: "success" | "error" | "idle"; message?: string };

function statusLabel(configured: boolean) {
	return configured ? "已配置（密钥不回显）" : "尚未配置";
}

export function IntegrationSettingsForm({ workspaceId, initialSettings, initialRuntime }: { workspaceId: number; initialSettings: WorkspaceIntegrationSettings | null; initialRuntime: AgentRuntime | null }) {
	const [settings, setSettings] = useState<WorkspaceIntegrationSettings | null>(initialSettings);
	const [runtime, setRuntime] = useState<AgentRuntime | null>(initialRuntime);
	const mcpConfigured = Boolean(settings?.article_sync_mcp_server_path && settings.article_sync_mcp_token_configured);
	const [mcpServerPath, setMcpServerPath] = useState(initialSettings?.article_sync_mcp_server_path ?? "");
	const [mcpToken, setMcpToken] = useState("");
	const [saving, setSaving] = useState(false);
	const [testing, setTesting] = useState<"local_codex" | "article_sync_mcp" | null>(null);
	const [feedback, setFeedback] = useState<Feedback>({ kind: "idle" });

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
			setFeedback({ kind: "success", message: "配置已加密保存。系统不会在页面、日志或 API 响应中回显密钥。" });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "保存失败，请稍后重试。" });
		} finally {
			setSaving(false);
		}
	}

	async function testMcp() {
		const integration = "article_sync_mcp" as const;
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
		<header className={styles.integrationHeader}><div><span className={styles.integrationEyebrow}>04 · Agent 与草稿交付</span><h2>本机 Codex 与文章同步</h2><p>Codex 负责调研、写作和平台适配；人工审核后，再由文章同步助手写入草稿箱。</p></div><span className={runtime?.ready && mcpConfigured ? styles.integrationReady : styles.integrationPending}>{runtime?.ready && mcpConfigured ? "执行与交付均就绪" : "检查本机状态"}</span></header>
		<div className={styles.integrationGrid}>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>Local Codex Agent</b><small>{runtime?.ready ? "已复用本机 ChatGPT 登录" : "未就绪"}</small></div><i className={runtime?.ready ? styles.dotReady : styles.dotPending} /></div>
				<dl className={styles.runtimeFacts}><div><dt>认证</dt><dd>{runtime?.login_status === "chatgpt_authenticated" ? "ChatGPT 已登录" : runtime?.login_status || "无法读取"}</dd></div><div><dt>默认模型</dt><dd>{runtime?.default_model || "—"}</dd></div><div><dt>SDK</dt><dd>{runtime?.sdk_version || "—"}</dd></div></dl>
				<p className={styles.runtimeNote}>不保存 API Key。Agent 仅在隔离目录写入中间工件，内容生成后停在人工审核。</p>
				<button type="button" className={styles.testButton} onClick={testCodex} disabled={testing !== null || saving}>{testing === "local_codex" ? "正在执行真实 turn…" : "运行 Codex 自检"}</button>
			</div>
			<div className={styles.integrationBlock}>
				<div className={styles.integrationBlockTitle}><div><b>文章同步助手 MCP</b><small>{statusLabel(mcpConfigured)}</small></div><i className={mcpConfigured ? styles.dotReady : styles.dotPending} /></div>
				<label>MCP Server 文件路径<input type="text" value={mcpServerPath} onChange={(event) => setMcpServerPath(event.target.value)} placeholder="/path/to/Wechatsync/packages/mcp-server/dist/index.js" autoComplete="off" spellCheck={false} /></label>
				<label>MCP Token<input type="password" value={mcpToken} onChange={(event) => setMcpToken(event.target.value)} placeholder={settings?.article_sync_mcp_token_configured ? "已配置；留空保持不变" : "粘贴 MCP Token"} autoComplete="new-password" spellCheck={false} /></label>
				<button type="button" className={styles.testButton} onClick={testMcp} disabled={testing !== null || saving}>{testing === "article_sync_mcp" ? "正在发现能力…" : "测试 MCP Server"}</button>
			</div>
		</div>
		<p className={styles.integrationHint}>Codex 直接复用本机登录，无需配置中转站或模型 Key。文章同步助手仍是独立的草稿交付通道；只有审核通过并点击确认后才会写入所选平台，不执行发布。</p>
		{feedback.message ? <p className={`${styles.feedback} ${feedback.kind === "error" ? styles.error : styles.success}`} role="status">{feedback.message}</p> : null}
		<button type="button" className={styles.integrationSave} onClick={save} disabled={saving || testing !== null}>{saving ? "正在保存…" : "保存草稿交付配置"}</button>
	</section>;
}
