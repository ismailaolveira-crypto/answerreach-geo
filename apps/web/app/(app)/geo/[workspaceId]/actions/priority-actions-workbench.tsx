"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useTransition } from "react";
import { BrandLogo } from "@/components/brand-logo";
import type { AgentRuntime, CleanroomAction, CleanroomAgentEvent, CleanroomAgentRun } from "@/lib/cleanroom-v1-api";
import type { PriorityActionOpportunity } from "./priority-action-opportunities";

type Props = {
	workspaceId: string;
	opportunities: PriorityActionOpportunity[];
	actions: CleanroomAction[];
	agentRuntime: AgentRuntime | null;
	initialAgentRuns: CleanroomAgentRun[];
	createAction: (formData: FormData) => Promise<void>;
	startAgent: (actionId: number, platforms: string[]) => Promise<CleanroomAgentRun>;
	interruptAgent: (runId: number) => Promise<CleanroomAgentRun>;
	resumeAgent: (runId: number) => Promise<CleanroomAgentRun>;
	readAgentProgress: (actionId: number) => Promise<{ runs: CleanroomAgentRun[]; events: CleanroomAgentEvent[] }>;
	discoverActions: () => Promise<void>;
};

type SyncAccount = {
	type: string;
	title: string;
	displayName?: string;
	status?: "pending" | "uploading" | "done" | "failed";
	msg?: string;
	error?: string;
	editResp?: { draftLink?: string } | null;
};

type ArticleSyncPageApi = {
	getAccounts: (callback: (first: unknown, second?: unknown) => void) => void;
	addTask: (
		task: { post: { title: string; content: string; markdown: string }; accounts: SyncAccount[] },
		statusHandler: (task: { accounts?: SyncAccount[] }) => void,
		callback: (first?: unknown, second?: unknown) => void,
	) => void;
};

function escapeHtml(value: string) {
	return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[character] ?? character);
}

function getArticleSyncApi() {
	return (window as Window & { $syncer?: ArticleSyncPageApi }).$syncer;
}

function discoverSyncAccounts(api: ArticleSyncPageApi) {
	return new Promise<SyncAccount[]>((resolve, reject) => {
		const timeout = window.setTimeout(() => reject(new Error("平台登录检查超时，请打开文章同步助手确认登录状态。")), 180_000);
		api.getAccounts((first, second) => {
			window.clearTimeout(timeout);
			const value = Array.isArray(second) ? second : Array.isArray(first) ? first : [];
			resolve(value as SyncAccount[]);
		});
	});
}

const priorityLabel = { high: "高优先级", medium: "中优先级", low: "持续观察" } as const;
const typeLabel = { visibility: "候选缺口", citation: "引用缺口", competitor: "竞品领先" } as const;

function suggestedSources(type: PriorityActionOpportunity["type"]) {
	if (type === "citation") return ["关键指标释义", "应用场景说明", "行业解决方案"];
	if (type === "competitor") return ["客户证言", "权威媒体报道", "第三方评测"];
	return ["企业选型对比", "私有化部署说明", "真实客户案例"];
}

function suggestedCarrier(type: PriorityActionOpportunity["type"]) {
	if (type === "citation") return "官网解决方案页 + 技术文章";
	if (type === "competitor") return "深度回答 + 媒体稿件";
	return "官网专题页 + 深度回答";
}

function modelBrand(label: string) {
	const value = label.toLowerCase();
	if (value.includes("deepseek")) return "deepseek";
	if (value.includes("doubao") || value.includes("豆包")) return "doubao";
	if (value.includes("qwen") || value.includes("千问")) return "qwen";
	if (value.includes("glm") || value.includes("智谱")) return "glm";
	if (value.includes("kimi") || value.includes("moonshot")) return "kimi";
	if (value.includes("hunyuan") || value.includes("混元")) return "hunyuan";
	return null;
}

function ModelBadge({ label }: { label: string }) {
	const brand = modelBrand(label);
	return <span className="pa-model-badge">{brand ? <BrandLogo brand={brand} label={label} className="pa-model-logo" /> : <i>AI</i>}<b>{label}</b></span>;
}

function Icon({ name }: { name: "warning" | "trend" | "draft" | "check" | "chevron" | "arrow" | "quote" | "spark" | "calendar" | "filter" | "eye" }) {
	const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
	return <svg viewBox="0 0 24 24" aria-hidden="true">
		{name === "warning" && <><path {...common} d="M12 4 3.8 19h16.4L12 4Z" /><path {...common} d="M12 9v4.3M12 16.8h.01" /></>}
		{name === "trend" && <><path {...common} d="M4 18V6M4 18h16" /><path {...common} d="m7 14 3.5-3.4 2.7 1.8L18 7" /></>}
		{name === "draft" && <><path {...common} d="M6 3.8h8l4 4V20H6z" /><path {...common} d="M14 3.8V8h4M9 12h6M9 15.5h4" /></>}
		{name === "check" && <path {...common} d="m5 12.5 4.2 4.2L19 7" />}
		{name === "chevron" && <path {...common} d="m8 10 4 4 4-4" />}
		{name === "arrow" && <path {...common} d="M5 12h13M13 7l5 5-5 5" />}
		{name === "quote" && <path {...common} d="M7.8 10H4.5v3.2h3.1c0 2-1 3.6-2.8 4.5m12.7-7.7h-3.3v3.2h3.1c0 2-1 3.6-2.8 4.5" />}
		{name === "spark" && <path {...common} d="m12 3 1.5 5.8L19 10.5l-5.5 1.7L12 18l-1.5-5.8L5 10.5l5.5-1.7z" />}
		{name === "calendar" && <><rect {...common} x="4" y="5.5" width="16" height="14" rx="2" /><path {...common} d="M8 3.5v4M16 3.5v4M4 10h16" /></>}
		{name === "filter" && <><path {...common} d="M4 6h16M7 12h10M10 18h4" /></>}
		{name === "eye" && <><path {...common} d="M2.7 12s3.3-5.1 9.3-5.1 9.3 5.1 9.3 5.1-3.3 5.1-9.3 5.1S2.7 12 2.7 12Z" /><circle {...common} cx="12" cy="12" r="2" /></>}
	</svg>;
}

function actionStage(action?: CleanroomAction) {
	if (!action) return 0;
	if (["verified", "closed"].includes(action.status)) return 4;
	// Legacy actions marked in_progress only prove that an action was selected.
	// Agent generation is driven exclusively by persisted GeoAgentRun records.
	return 1;
}

function ActionStage({ index, label, state, children }: { index: number; label: string; state: "done" | "active" | "idle"; children?: React.ReactNode }) {
	return <li className={`pa-stage is-${state}`}>
		<span>{state === "done" ? <Icon name="check" /> : index}</span>
		<div><header><b>{label}</b><small>{state === "done" ? "已完成" : state === "active" ? "进行中" : "待处理"}</small></header>{children}</div>
	</li>;
}

const agentStageLabels: Record<string, string> = {
	queued: "等待本机 worker",
	preparing_context: "整理真实证据",
	researching_platform: "查阅平台规则",
	researching_brand: "核对品牌事实",
	adapting_platforms: "生成平台差异稿",
	awaiting_review: "等待人工审核",
	cancelled: "已中止",
	failed: "运行失败",
};

const platformOptions = [
	{ key: "zhihu", label: "知乎", logo: "/brand/zhihu.svg" },
	{ key: "wechat", label: "公众号", logo: "/brand/wechat.svg" },
] as const;

export function PriorityActionsWorkbench({ workspaceId, opportunities, actions, agentRuntime, initialAgentRuns, createAction, startAgent, interruptAgent, resumeAgent, readAgentProgress, discoverActions }: Props) {
	const router = useRouter();
	const [selectedId, setSelectedId] = useState(opportunities.find((item) => item.existingAction)?.id ?? opportunities[0]?.id ?? "");
	const [selectedModel, setSelectedModel] = useState("all");
	const [selectedQuestion, setSelectedQuestion] = useState("all");
	const [isTimelineCollapsed, setIsTimelineCollapsed] = useState(false);
	const [previewMessage, setPreviewMessage] = useState("");
	const [syncOpen, setSyncOpen] = useState(false);
	const [syncPhase, setSyncPhase] = useState<"idle" | "discovering" | "confirm" | "syncing" | "complete" | "error">("idle");
	const [syncAccounts, setSyncAccounts] = useState<SyncAccount[]>([]);
	const [selectedSyncAccounts, setSelectedSyncAccounts] = useState<string[]>([]);
	const [syncMessage, setSyncMessage] = useState("");
	const [agentRuns, setAgentRuns] = useState(initialAgentRuns);
	const [agentEvents, setAgentEvents] = useState<CleanroomAgentEvent[]>([]);
	const [agentFeedback, setAgentFeedback] = useState("");
	const [targetPlatforms, setTargetPlatforms] = useState<string[]>(["zhihu", "wechat"]);
	const [isSaving, startSaving] = useTransition();

	const models = useMemo(() => [...new Set(opportunities.flatMap((item) => item.modelLabels))], [opportunities]);
	const questions = useMemo(() => [...new Map(opportunities.map((item) => [item.questionId, item.questionText])).entries()], [opportunities]);
	const filtered = useMemo(() => opportunities.filter((item) => (selectedModel === "all" || item.modelLabels.includes(selectedModel)) && (selectedQuestion === "all" || String(item.questionId) === selectedQuestion)), [opportunities, selectedModel, selectedQuestion]);
	useEffect(() => { if (!filtered.some((item) => item.id === selectedId)) setSelectedId(filtered[0]?.id ?? ""); }, [filtered, selectedId]);
	const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
	const actionable = opportunities.filter((item) => !item.existingAction);
	const high = actionable.filter((item) => item.priority === "high").length;
	const pendingActions = agentRuns.filter((run) => run.status === "awaiting_review").length;
	const retestReady = actions.filter((item) => ["verified", "closed"].includes(item.status)).length;
	const stage = actionStage(selected?.existingAction);
	const syncAction = selected?.existingAction ?? actions[0];
	const currentRun = useMemo(() => agentRuns
		.filter((run) => run.action_id === selected?.existingAction?.id)
		.sort((a, b) => b.id - a.id)[0], [agentRuns, selected?.existingAction?.id]);
	const runActive = Boolean(currentRun && ["queued", "resuming", "running", "cancelling"].includes(currentRun.status));

	useEffect(() => {
		const actionId = selected?.existingAction?.id;
		if (!actionId) {
			setAgentEvents([]);
			return;
		}
		const activeActionId = actionId;
		let cancelled = false;
		async function refresh() {
			try {
				const result = await readAgentProgress(activeActionId);
				if (!cancelled) {
					setAgentRuns((current) => [...current.filter((run) => run.action_id !== activeActionId), ...result.runs]);
					setAgentEvents(result.events);
				}
			} catch (error) {
				if (!cancelled) setAgentFeedback(error instanceof Error ? error.message : "无法读取 Agent 进度");
			}
		}
		void refresh();
		const timer = window.setInterval(() => { if (runActive) void refresh(); }, 1500);
		return () => { cancelled = true; window.clearInterval(timer); };
	}, [readAgentProgress, runActive, selected?.existingAction?.id]);

	useEffect(() => {
		if (!currentRun || !["queued", "resuming", "running", "cancelling"].includes(currentRun.status)) return;
		const after = agentEvents.at(-1)?.sequence ?? 0;
		const source = new EventSource(`/api/geo/${workspaceId}/agent-runs/${currentRun.id}/events?after=${after}`);
		source.addEventListener("agent_event", (raw) => {
			const event = JSON.parse((raw as MessageEvent<string>).data) as CleanroomAgentEvent;
			setAgentEvents((current) => current.some((item) => item.id === event.id) ? current : [...current, event]);
			setAgentRuns((current) => current.map((run) => run.id === currentRun.id ? {
				...run,
				stage: event.stage,
				status: event.event_type === "awaiting_human_review" ? "awaiting_review" : event.event_type === "run_cancelled" ? "cancelled" : event.event_type === "run_failed" ? "failed" : run.status === "queued" ? "running" : run.status,
			} : run));
		});
		source.addEventListener("end", () => { source.close(); router.refresh(); });
		source.onerror = () => source.close();
		return () => source.close();
	}, [agentEvents, currentRun, router, workspaceId]);

	function beginAgent() {
		if (!selected?.existingAction || !targetPlatforms.length) return;
		setAgentFeedback("");
		startSaving(async () => {
			try {
				const run = await startAgent(selected.existingAction!.id, targetPlatforms);
				setAgentRuns((current) => [run, ...current]);
				setAgentEvents([]);
				router.refresh();
			} catch (error) {
				setAgentFeedback(error instanceof Error ? error.message : "Agent 启动失败");
			}
		});
	}

	function requestInterrupt() {
		if (!currentRun) return;
		startSaving(async () => {
			try {
				const run = await interruptAgent(currentRun.id);
				setAgentRuns((current) => current.map((item) => item.id === run.id ? run : item));
			} catch (error) {
				setAgentFeedback(error instanceof Error ? error.message : "中止请求失败");
			}
		});
	}

	function requestResume() {
		if (!currentRun) return;
		startSaving(async () => {
			try {
				const run = await resumeAgent(currentRun.id);
				setAgentRuns((current) => current.map((item) => item.id === run.id ? run : item));
			} catch (error) {
				setAgentFeedback(error instanceof Error ? error.message : "恢复请求失败");
			}
		});
	}

	async function openSyncAssistant() {
		if (!syncAction) {
			setPreviewMessage("请先选择一个真实行动，准备好内容后再打开同步助手。");
			return;
		}
		setSyncOpen(true);
		setSyncPhase("discovering");
		setSyncMessage("正在通过文章同步助手检查已登录平台…");
		setSyncAccounts([]);
		setSelectedSyncAccounts([]);
		const api = getArticleSyncApi();
		if (!api) {
			setSyncPhase("error");
			setSyncMessage("当前网页没有检测到文章同步助手。请在 EgoLite 中启用扩展并刷新本页。");
			return;
		}
		try {
			const accounts = await discoverSyncAccounts(api);
			const platformAccounts = accounts.filter((account) => account.type !== "zip-download");
			setSyncAccounts(platformAccounts);
			if (!platformAccounts.length) {
				setSyncPhase("error");
				setSyncMessage("没有检测到已登录平台。请先在 EgoLite 中登录目标平台，再重新打开同步助手。");
				return;
			}
			setSyncPhase("confirm");
			setSyncMessage(platformAccounts.length === 1
				? "当前只检测到 1 个已登录平台；如需双平台，请先在 EgoLite 中登录另一个平台。"
				: `已检测到 ${platformAccounts.length} 个登录平台。选择目标后由你确认，系统不会自动发布。`);
		} catch (error) {
			setSyncPhase("error");
			setSyncMessage(error instanceof Error ? error.message : "文章同步助手连接失败。");
		}
	}

	function confirmSync() {
		const api = getArticleSyncApi();
		const accounts = syncAccounts.filter((account) => selectedSyncAccounts.includes(account.type));
		if (!api || !syncAction || accounts.length === 0) return;
		const content = `<h1>${escapeHtml(syncAction.title)}</h1><p>${escapeHtml(syncAction.rationale)}</p>${syncAction.hypothesis ? `<h2>验证目标</h2><p>${escapeHtml(syncAction.hypothesis)}</p>` : ""}<p><strong>说明：</strong>此内容由春秋元泉 GEO 工作台交给文章同步助手，仅写入平台草稿，不执行发布。</p>`;
		const markdown = `# ${syncAction.title}\n\n${syncAction.rationale}${syncAction.hypothesis ? `\n\n## 验证目标\n\n${syncAction.hypothesis}` : ""}\n\n**说明：** 此内容由春秋元泉 GEO 工作台交给文章同步助手，仅写入平台草稿，不执行发布。`;
		setSyncPhase("syncing");
		setSyncMessage("同步请求已提交，正在等待各平台返回草稿结果…");
		api.addTask(
			{ post: { title: syncAction.title, content, markdown }, accounts },
			(task) => {
				if (!task.accounts?.length) return;
				setSyncAccounts(task.accounts);
				const finished = task.accounts.every((account) => account.status === "done" || account.status === "failed");
				if (finished) {
					setSyncPhase("complete");
					const saved = task.accounts.filter((account) => account.status === "done" && account.editResp?.draftLink).length;
					setSyncMessage(saved > 0 ? `${saved} 个平台返回了可回读的草稿链接；其余结果请逐项核对。` : "平台未返回可回读草稿；不会计为已保存。请查看下方失败原因。");
				}
			},
			() => undefined,
		);
	}

	return <main className="pa-page">
		<section className="pa-topline">
			<header className="pa-hero">
				<div><h1>优先行动</h1><span>从真实观测缺口出发，补齐信源、生成内容、写入草稿，并在下一轮验证变化。</span>
					<form action={discoverActions} className="pa-discover-form"><button type="submit">从真实观测刷新机会</button></form>
					<div className="pa-filters" aria-label="筛选行动机会">
						<label><Icon name="calendar" /><select defaultValue="current" disabled><option value="current">当前批次证据</option></select><Icon name="chevron" /></label>
						<label><Icon name="filter" /><select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)}><option value="all">全部模型</option>{models.map((model) => <option key={model} value={model}>{model}</option>)}</select><Icon name="chevron" /></label>
						<label><Icon name="spark" /><select value={selectedQuestion} onChange={(event) => setSelectedQuestion(event.target.value)}><option value="all">全部问题</option>{questions.map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select><Icon name="chevron" /></label>
					</div>
				</div>
			</header>

			<section className="pa-summary" aria-label="行动状态摘要">
				<article><span className="pa-summary-icon is-warning"><Icon name="warning" /></span><div><small>待处理缺口</small><strong>{actionable.length}</strong></div></article>
				<article><span className="pa-summary-icon is-trend"><Icon name="trend" /></span><div><small>高优先级</small><strong>{high}</strong></div></article>
				<article><span className="pa-summary-icon is-draft"><Icon name="draft" /></span><div><small>草稿待确认</small><strong>{pendingActions}</strong></div></article>
				<article><span className="pa-summary-icon is-check"><Icon name="check" /></span><div><small>已完成待复测</small><strong>{retestReady}</strong></div></article>
			</section>
		</section>

		{opportunities.length === 0 ? <section className="pa-empty"><span><Icon name="spark" /></span><h2>还没有足够的真实证据</h2><p>完成一次联网观测并归档回答与来源后，系统才会从真实结果中识别行动机会。</p><Link href={`/geo/${workspaceId}`}>发起真实观测 <Icon name="arrow" /></Link></section> : <>
			<section className="pa-workspace">
				<div className="pa-opportunity-panel">
					<header><div><h2>系统发现的优先机会</h2><p>仅使用已归档回答生成，不补造证据。</p></div><small>{filtered.length} 个机会</small></header>
					<div className="pa-opportunity-list">
						{filtered.map((item) => <article key={item.id} className={selected?.id === item.id ? "is-selected" : ""}>
							<div className="pa-opportunity-main"><span className={`pa-priority ${item.priority}`}>{priorityLabel[item.priority]}</span><h3>{item.title}</h3><p>{item.summary}</p><div className="pa-models">{item.modelLabels.slice(0, 4).map((label) => <ModelBadge key={label} label={label} />)}</div></div>
							<div className="pa-gap"><small>缺失信源</small><div className="pa-source-tags">{suggestedSources(item.type).map((source) => <span key={source}>{source}</span>)}</div><em>建议载体 · {suggestedCarrier(item.type)}</em></div>
							<div className="pa-opportunity-actions"><span className="pa-evidence-ok"><Icon name="check" />证据充分</span><button type="button" onClick={() => setSelectedId(item.id)}>{item.existingAction ? "查看行动" : "选择并开始"}</button><Link href={`/geo/${workspaceId}/evidence/${item.evidenceIds[0]}`}>查看 {item.evidenceIds.length} 条证据 <Icon name="arrow" /></Link></div>
						</article>)}
					</div>
				</div>

				<aside className={`pa-current-action ${isTimelineCollapsed ? "is-collapsed" : ""}`}>
					<header><h2>本次行动</h2><button type="button" onClick={() => setIsTimelineCollapsed((value) => !value)}>{isTimelineCollapsed ? "展开" : "收起"} <Icon name="chevron" /></button></header>
					{!isTimelineCollapsed && selected ? <ol>
						<ActionStage index={1} label="选择信源" state={stage >= 1 ? "done" : "active"}>{stage === 0 ? <div className="pa-stage-card"><b>目标载体</b><p>{selected.recommendedAsset}</p><form action={(formData) => startSaving(() => createAction(formData))}><input type="hidden" name="title" value={`${selected.title}：${selected.questionText}`} /><input type="hidden" name="rationale" value={selected.summary} /><input type="hidden" name="hypothesis" value={`下一轮相同问题中，期待“${selected.recommendedAsset}”补齐后，春秋元泉进入候选或获得引用。`} /><input type="hidden" name="priority" value={selected.priority} /><input type="hidden" name="question_plan_id" value={selected.questionId} /><input type="hidden" name="source_evidence_id" value={selected.evidenceIds[0]} />{selected.backendId ? <input type="hidden" name="opportunity_id" value={selected.backendId} /> : null}<button disabled={isSaving} type="submit">{isSaving ? "正在保存行动…" : "选择这个行动"}</button></form></div> : <p className="pa-stage-note">已关联当前问题的真实证据与行动记录。</p>}</ActionStage>
						<ActionStage index={2} label="Agent 调研与生成" state={currentRun?.status === "awaiting_review" ? "done" : currentRun ? "active" : stage === 1 ? "active" : "idle"}>
							{stage === 1 && selected.existingAction && !currentRun ? <div className="pa-stage-card"><b>目标平台</b><p>Codex 会先查阅平台官方规则，再根据真实观测和品牌官网生成差异化草稿。</p><div className="pa-platform-picker">{platformOptions.map((platform) => <label key={platform.key} className={targetPlatforms.includes(platform.key) ? "is-selected" : ""}><input type="checkbox" checked={targetPlatforms.includes(platform.key)} onChange={() => setTargetPlatforms((current) => current.includes(platform.key) ? current.filter((key) => key !== platform.key) : [...current, platform.key])} /><img src={platform.logo} alt={`${platform.label} 官方标志`} /><span>{platform.label}</span></label>)}</div><button disabled={isSaving || !targetPlatforms.length || !agentRuntime?.ready} type="button" onClick={beginAgent}><Icon name="spark" />{isSaving ? "正在入队…" : agentRuntime?.ready ? "启动本机 Codex Agent" : "Codex 未就绪，请先去设置"}</button></div> : null}
							{currentRun ? <div className="pa-agent-run"><div className="pa-agent-runtime"><span><img src="/brand/openai.svg" alt="OpenAI 官方标志" /></span><div><b>{currentRun.model || "Local Codex"}</b><small>Run #{currentRun.id} · {agentStageLabels[currentRun.stage] || currentRun.stage}</small></div></div><p>{agentEvents.at(-1)?.message || (currentRun.status === "queued" ? "已入队，等待 worker 接受。" : "正在读取持久化进度…")}</p>{currentRun.error_message ? <p className="is-error">{currentRun.error_message}</p> : null}<div className="pa-agent-actions">{runActive && currentRun.status !== "cancelling" ? <button type="button" onClick={requestInterrupt} disabled={isSaving}>中止运行</button> : null}{["cancelled", "failed"].includes(currentRun.status) && currentRun.codex_thread_id ? <button type="button" onClick={requestResume} disabled={isSaving}>恢复原任务</button> : null}</div></div> : null}
							{agentFeedback ? <p className="pa-agent-error" role="status">{agentFeedback}</p> : null}
						</ActionStage>
						<ActionStage index={3} label="人工审核" state={currentRun?.status === "awaiting_review" ? "active" : "idle"}>{currentRun?.status === "awaiting_review" ? <div className="pa-stage-card"><b>草稿已入库</b><p>内容资产 #{String(currentRun.result_snapshot.asset_id ?? "—")} · {currentRun.selected_platforms.length} 个平台版本。事实主张和来源已保留，当前仍是待审草稿。</p><button type="button" disabled>审核工作台将在下一阶段接入</button></div> : <p className="pa-stage-note">只有 Agent 成功生成并持久化内容后，审核才会开放。</p>}</ActionStage>
						<ActionStage index={4} label="写入平台草稿" state="idle"><p className="pa-stage-note">只允许写入草稿，最终发布仍由人工确认。</p></ActionStage>
						<ActionStage index={5} label="下轮复测" state={stage >= 4 ? "active" : "idle"}>{stage >= 4 ? <p className="pa-stage-note">请使用相同问题与模型集合创建复测批次。</p> : null}</ActionStage>
					</ol> : !isTimelineCollapsed ? <p className="pa-empty-copy">调整筛选条件后，选择一个机会开始。</p> : null}
				</aside>
			</section>

			{actions.length > 0 ? <section className="pa-progress">
				<header><div><h2>内容与发布进度</h2><p>只由已持久化的 Agent 运行与人工状态推进；未运行不显示为生成中。</p></div></header>
				<div className="pa-progress-lanes"><div className={agentRuns.some((run) => ["queued", "resuming", "running", "cancelling"].includes(run.status)) ? "is-current" : ""}><b>Agent 生成</b><span>{agentRuns.filter((run) => ["queued", "resuming", "running", "cancelling"].includes(run.status)).length}</span><p>{agentRuns.find((run) => ["queued", "resuming", "running", "cancelling"].includes(run.status)) ? "正在调研与生成" : "暂无运行中任务"}</p></div><div className={currentRun?.stage === "researching_brand" ? "is-current" : ""}><b>事实校验</b><span>{agentRuns.filter((run) => run.stage === "researching_brand").length}</span><p>只保留可追溯主张，未知项不补写</p></div><div className={currentRun?.stage === "adapting_platforms" ? "is-current" : ""}><b>平台适配</b><span>{agentRuns.filter((run) => run.stage === "adapting_platforms").length}</span><p>按官方规则生成差异化版本</p></div><div className={currentRun?.status === "awaiting_review" ? "is-current" : ""}><b>人工审核</b><span>{agentRuns.filter((run) => run.status === "awaiting_review").length}</span><p>审核前不会触发同步</p></div><div><b>写入草稿</b><span>0</span><p>当前未接入审核通过信号</p></div><div><b>人工发布 / 复测</b><span>{actions.filter((item) => ["verified", "closed"].includes(item.status)).length}</span><p>平台发布始终由人工确认</p></div></div>
				<footer className="pa-progress-footer"><span><Icon name="eye" />Agent 只生成待审内容；审核、写入草稿和发布是独立人工边界</span><div><button type="button" onClick={() => setPreviewMessage(currentRun?.status === "awaiting_review" ? `内容资产 #${String(currentRun.result_snapshot.asset_id ?? "—")} 已生成，但尚未人工审核。` : "请先完成 Agent 调研与生成。")}>预览状态</button><button className="pa-sync-button" type="button" onClick={openSyncAssistant} disabled={true} title="待人工审核接入后开放">审核后打开同步助手 <Icon name="arrow" /></button></div></footer>
				{previewMessage ? <p className="pa-front-notice" role="status">{previewMessage}</p> : null}
			</section> : null}
		{syncOpen ? <div className="pa-sync-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && syncPhase !== "syncing") setSyncOpen(false); }}>
			<section className="pa-sync-dialog" role="dialog" aria-modal="true" aria-labelledby="sync-assistant-title">
				<header><div><small>文章同步助手</small><h2 id="sync-assistant-title">选择平台并确认写入</h2></div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"} aria-label="关闭同步助手">×</button></header>
				<div className="pa-sync-summary"><b>{syncAction?.title}</b><p>当前使用已保存的行动内容进行接入；每个平台默认只保存草稿。</p></div>
				<p className={`pa-sync-message is-${syncPhase}`} role="status">{syncMessage}</p>
				{syncAccounts.length ? <div className="pa-sync-platforms">{syncAccounts.map((account) => {
					const disabled = syncPhase !== "confirm";
					const checked = selectedSyncAccounts.includes(account.type);
					return <label key={account.type} className={checked ? "is-selected" : ""}><input type="checkbox" checked={checked} disabled={disabled} onChange={() => setSelectedSyncAccounts((current) => current.includes(account.type) ? current.filter((value) => value !== account.type) : [...current, account.type])} /><span><b>{account.displayName || account.title}</b><small>{account.status === "done" ? "草稿已返回" : account.status === "failed" ? (account.error || "写入失败") : account.msg || account.title}</small></span>{account.editResp?.draftLink ? <a href={account.editResp.draftLink} target="_blank" rel="noreferrer">打开草稿</a> : null}</label>;
				})}</div> : null}
				<footer><span>确认只会触发草稿写入，不会点击平台发布。</span><div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"}>取消</button>{syncPhase === "confirm" ? <button className="is-primary" type="button" onClick={confirmSync} disabled={!selectedSyncAccounts.length}>确认写入 {selectedSyncAccounts.length} 个平台</button> : null}{syncPhase === "error" ? <button className="is-primary" type="button" onClick={openSyncAssistant}>重新检测</button> : null}</div></footer>
			</section>
		</div> : null}
		</>}
	</main>;
}
