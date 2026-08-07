"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useTransition } from "react";
import { BrandLogo } from "@/components/brand-logo";
import type {
	AgentRuntime,
	CleanroomAction,
	CleanroomActionOpportunityScope,
	CleanroomActionRetest,
	CleanroomAgentEvent,
	CleanroomAgentRun,
	CleanroomAgentRunProgress,
	CleanroomContentReviewPackage,
	CleanroomDistributionRun,
	CleanroomPlatformVariant,
} from "@/lib/cleanroom-v1-api";
import type { PriorityActionOpportunity } from "./priority-action-opportunities";

type Props = {
	workspaceId: string;
	opportunities: PriorityActionOpportunity[];
	opportunityScope: CleanroomActionOpportunityScope;
	initialScope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null };
	actions: CleanroomAction[];
	agentRuntime: AgentRuntime | null;
	initialAgentRuns: CleanroomAgentRun[];
	initialReviewPackages: CleanroomContentReviewPackage[];
	initialDistributionRuns: CleanroomDistributionRun[];
	initialRetests: CleanroomActionRetest[];
	createAction: (formData: FormData) => Promise<void>;
	startAgent: (actionId: number, platforms: string[]) => Promise<CleanroomAgentRun>;
	interruptAgent: (runId: number) => Promise<CleanroomAgentRun>;
	resumeAgent: (runId: number) => Promise<CleanroomAgentRun>;
	reviseAgent: (runId: number, contentAssetId: number) => Promise<CleanroomAgentRun>;
	readAgentProgress: (actionId: number) => Promise<{ runs: CleanroomAgentRun[]; progress: CleanroomAgentRunProgress | null }>;
	decideReview: (assetId: number, payload: { verdict: "approved" | "changes_requested"; confirmed_claim_ids: number[]; platform_keys: string[]; note?: string | null }) => Promise<CleanroomContentReviewPackage>;
	createDistribution: (assetId: number, platformKeys: string[]) => Promise<CleanroomDistributionRun>;
	recordDistributionResults: (runId: number, targets: Array<{ platform_key: string; request_status: "draft_saved" | "failed" | "cancelled"; draft_url?: string | null; external_draft_id?: string | null; message?: string | null }>) => Promise<CleanroomDistributionRun>;
	recordHumanPublication: (runId: number, targetId: number, publicUrl: string) => Promise<CleanroomDistributionRun>;
	createRetest: (actionId: number) => Promise<CleanroomActionRetest>;
	readRetest: (actionId: number) => Promise<CleanroomActionRetest>;
	discoverActions: (scope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null }) => Promise<void>;
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

function syncPlatformKey(account: SyncAccount) {
	const value = `${account.type} ${account.title} ${account.displayName || ""}`.toLowerCase();
	if (value.includes("zhihu") || value.includes("知乎")) return "zhihu";
	if (value.includes("wechat") || value.includes("weixin") || value.includes("微信") || value.includes("公众号")) return "wechat";
	return null;
}

function inlineMarkdownHtml(value: string) {
	return escapeHtml(value)
		.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
		.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function basicMarkdownHtml(markdown: string) {
	return markdown
		.split(/\n{2,}/)
		.map((block) => {
			const text = block.trim();
			if (!text) return "";
			if (text.startsWith("### ")) return `<h3>${inlineMarkdownHtml(text.slice(4))}</h3>`;
			if (text.startsWith("## ")) return `<h2>${inlineMarkdownHtml(text.slice(3))}</h2>`;
			if (text.startsWith("# ")) return `<h1>${inlineMarkdownHtml(text.slice(2))}</h1>`;
			return `<p>${inlineMarkdownHtml(text).replaceAll("\n", "<br>")}</p>`;
		})
		.join("");
}

function syncVariant(api: ArticleSyncPageApi, account: SyncAccount, variant: CleanroomPlatformVariant) {
	return new Promise<SyncAccount>((resolve) => {
		let settled = false;
		const finish = (result: SyncAccount) => {
			if (settled) return;
			settled = true;
			window.clearTimeout(timeout);
			resolve(result);
		};
		const timeout = window.setTimeout(() => finish({ ...account, status: "failed", error: "写入等待超时" }), 180_000);
		api.addTask(
			{
				post: {
					title: variant.title,
					content: basicMarkdownHtml(variant.body_markdown),
					markdown: variant.body_markdown,
				},
				accounts: [account],
			},
			(task) => {
				const result = task.accounts?.[0];
				if (result?.status === "done" || result?.status === "failed") finish(result);
			},
			() => undefined,
		);
	});
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
	resuming: "正在恢复原任务",
	running: "正在执行",
	cancelling: "正在中止",
	cancelled: "已中止",
	timed_out: "运行超时",
	failed: "运行失败",
};

const platformOptions = [
	{ key: "zhihu", label: "知乎", logo: "/brand/zhihu.svg" },
	{ key: "wechat", label: "公众号", logo: "/brand/wechat.svg" },
] as const;

function runtimeVersionLabel(value?: string | null) {
	if (!value) return "Codex 运行时已检测";
	const desktopVersion = value.match(/Codex Desktop\/([^\s;]+)/i)?.[1];
	if (desktopVersion) return `Codex Desktop ${desktopVersion}`;
	const cliVersion = value.match(/codex(?:-cli)?\s+([^\s;]+)/i)?.[1];
	return cliVersion ? `Codex CLI ${cliVersion}` : "Codex 运行时已检测";
}

function formatAgentDuration(totalSeconds: number) {
	const seconds = Math.max(0, Math.floor(totalSeconds));
	const minutes = Math.floor(seconds / 60);
	const remainder = seconds % 60;
	return minutes ? `${minutes} 分 ${remainder} 秒` : `${remainder} 秒`;
}

function formatArtifactSize(size: number) {
	if (size < 1024) return `${size} B`;
	if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
	return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatEventTime(value: string) {
	return value.replace("T", " ").slice(11, 19);
}

function groupAgentEvents(events: CleanroomAgentEvent[]) {
	return events.reduce<Array<{ key: number; stage: string; message: string; count: number; firstAt: string; lastAt: string }>>((groups, event) => {
		const previous = groups.at(-1);
		if (previous && previous.stage === event.stage && previous.message === event.message) {
			previous.count += 1;
			previous.lastAt = event.created_at;
			return groups;
		}
		groups.push({ key: event.id, stage: event.stage, message: event.message, count: 1, firstAt: event.created_at, lastAt: event.created_at });
		return groups;
	}, []);
}

const agentProgressStateLabels = {
	waiting: "等待",
	running: "进行中",
	done: "已完成",
	waiting_human: "待你审核",
	failed: "未完成",
} as const;

export function PriorityActionsWorkbench({ workspaceId, opportunities, opportunityScope, initialScope, actions, agentRuntime, initialAgentRuns, initialReviewPackages, initialDistributionRuns, initialRetests, createAction, startAgent, interruptAgent, resumeAgent, reviseAgent, readAgentProgress, decideReview, createDistribution, recordDistributionResults, recordHumanPublication, createRetest, readRetest, discoverActions }: Props) {
	const router = useRouter();
	const [selectedId, setSelectedId] = useState(opportunities.find((item) => item.existingAction)?.id ?? opportunities[0]?.id ?? "");
	const [selectedBatchId, setSelectedBatchId] = useState(initialScope.batchId);
	const [selectedModel, setSelectedModel] = useState(initialScope.modelKey ?? "all");
	const [selectedQuestion, setSelectedQuestion] = useState(initialScope.questionPlanId ? String(initialScope.questionPlanId) : "all");
	const [discoveryFeedback, setDiscoveryFeedback] = useState("");
	const [runtimeExpanded, setRuntimeExpanded] = useState(false);
	const [isTimelineCollapsed, setIsTimelineCollapsed] = useState(false);
	const [previewMessage, setPreviewMessage] = useState("");
	const [syncOpen, setSyncOpen] = useState(false);
	const [syncPhase, setSyncPhase] = useState<"idle" | "discovering" | "confirm" | "syncing" | "complete" | "error">("idle");
	const [syncAccounts, setSyncAccounts] = useState<SyncAccount[]>([]);
	const [selectedSyncAccounts, setSelectedSyncAccounts] = useState<string[]>([]);
	const [syncMessage, setSyncMessage] = useState("");
	const [agentRuns, setAgentRuns] = useState(initialAgentRuns);
	const [agentEvents, setAgentEvents] = useState<CleanroomAgentEvent[]>([]);
	const [agentProgress, setAgentProgress] = useState<CleanroomAgentRunProgress | null>(null);
	const [agentDetailsExpanded, setAgentDetailsExpanded] = useState(false);
	const [agentTransport, setAgentTransport] = useState<"idle" | "connecting" | "live" | "fallback" | "ended">("idle");
	const [agentFeedback, setAgentFeedback] = useState("");
	const [reviewPackages, setReviewPackages] = useState(initialReviewPackages);
	const [distributionRuns, setDistributionRuns] = useState(initialDistributionRuns);
	const [retests, setRetests] = useState(initialRetests);
	const [publicationUrls, setPublicationUrls] = useState<Record<number, string>>({});
	const [publicationMessage, setPublicationMessage] = useState("");
	const [retestMessage, setRetestMessage] = useState("");
	const [reviewOpen, setReviewOpen] = useState(false);
	const [reviewTab, setReviewTab] = useState("master");
	const [confirmedClaimIds, setConfirmedClaimIds] = useState<number[]>([]);
	const [reviewPlatformKeys, setReviewPlatformKeys] = useState<string[]>([]);
	const [reviewNote, setReviewNote] = useState("");
	const [reviewFeedback, setReviewFeedback] = useState("");
	const [targetPlatforms, setTargetPlatforms] = useState<string[]>(["zhihu", "wechat"]);
	const [isSaving, startSaving] = useTransition();
	const [isScopePending, startScopeTransition] = useTransition();

	const selectedBatch = opportunityScope.batches.find((batch) => batch.id === selectedBatchId);
	const models = opportunityScope.models.filter((model) => selectedBatch?.model_keys.includes(model.key));
	const questions = opportunityScope.questions.filter((question) => selectedBatch?.question_plan_ids.includes(question.id));
	// The server has already applied the exact batch/model/question scope. Do not
	// compare model keys with user-facing model labels a second time in the client.
	const filtered = opportunities;
	useEffect(() => { if (!filtered.some((item) => item.id === selectedId)) setSelectedId(filtered[0]?.id ?? ""); }, [filtered, selectedId]);
	const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
	const actionable = filtered.filter((item) => !item.existingAction);
	const high = actionable.filter((item) => item.priority === "high").length;
	const pendingActions = agentRuns.filter((run) => {
		const assetId = Number(run.result_snapshot.asset_id);
		const reviewPackage = reviewPackages.find((item) => item.asset.id === assetId);
		return run.status === "awaiting_review" && !reviewPackage?.approved_platform_keys.length;
	}).length;
	const retestReady = retests.filter((item) => item.status === "completed").length;
	const stage = actionStage(selected?.existingAction);
	const syncAction = selected?.existingAction ?? actions[0];
	const currentRun = useMemo(() => agentRuns
		.filter((run) => run.action_id === selected?.existingAction?.id)
		.sort((a, b) => b.id - a.id)[0], [agentRuns, selected?.existingAction?.id]);
	const activeAgentRunCount = agentRuns.filter((run) => ["queued", "resuming", "running", "cancelling"].includes(run.status)).length;
	const agentCapacityLimit = Math.max(1, agentRuntime?.max_concurrent_runs ?? 1);
	const agentCapacityUsed = activeAgentRunCount;
	const agentCapacityAvailable = agentCapacityUsed < agentCapacityLimit;
	const agentCanStart = Boolean(agentRuntime?.ready && agentCapacityAvailable);
	const agentTimeoutMinutes = Math.max(1, Math.round((agentRuntime?.run_timeout_seconds ?? 900) / 60));
	const generatedAssetCount = new Set(
		agentRuns
			.map((run) => Number(run.result_snapshot.asset_id))
			.filter((assetId) => Number.isFinite(assetId) && assetId > 0),
	).size;
	const runActive = Boolean(currentRun && ["queued", "resuming", "running", "cancelling"].includes(currentRun.status));
	const currentRunId = currentRun?.id;
	const currentRunStatus = currentRun?.status;
	const currentAssetId = Number(currentRun?.result_snapshot.asset_id) || null;
	const currentReviewPackage = reviewPackages.find((item) => item.asset.id === currentAssetId);
	const reviewNeedsRevision = currentReviewPackage?.asset.status === "changes_requested";
	const approvedPlatformKeys = currentReviewPackage?.approved_platform_keys ?? [];
	const pendingClaims = currentReviewPackage?.claims.filter((claim) => !["source_linked", "verified", "human_confirmed"].includes(claim.verification_status)) ?? [];
	const confirmedPendingClaimCount = pendingClaims.filter((claim) => confirmedClaimIds.includes(claim.id)).length;
	const remainingPendingClaimCount = Math.max(0, pendingClaims.length - confirmedPendingClaimCount);
	const currentDistribution = distributionRuns
		.filter((run) => run.action_id === selected?.existingAction?.id)
		.sort((a, b) => b.id - a.id)[0];
	const savedDraftCount = currentDistribution?.targets.filter((target) => target.draft_readback_status === "draft_saved").length ?? 0;
	const allDraftsSaved = Boolean(currentDistribution?.targets.length && savedDraftCount === currentDistribution.targets.length);
	const publishedTargetCount = currentDistribution?.targets.filter((target) => target.human_publish_status === "published" && target.public_url).length ?? 0;
	const allTargetsPublished = Boolean(currentDistribution?.targets.length && publishedTargetCount === currentDistribution.targets.length);
	const currentRetest = retests.find((item) => item.action_id === selected?.existingAction?.id);
	const publicationRecordsLocked = Boolean(currentRetest?.retest_batch_id);
	const retestActive = Boolean(currentRetest && ["preparing", "queued", "running"].includes(currentRetest.status));
	const retestComplete = currentRetest?.status === "completed";
	const comparableRetestComplete = Boolean(retestComplete && currentRetest?.measured_delta.comparable);
	const retestProviderCount = Array.isArray(currentRetest?.scope_snapshot.provider_ids) ? currentRetest.scope_snapshot.provider_ids.length : 0;
	const retestRepeatCount = Number(currentRetest?.scope_snapshot.repeat_count || 0);
	const retestConclusionLabel = currentRetest ? ({
		improved: "可见度提升",
		unchanged: "暂未变化",
		regressed: "可见度下降",
		insufficient_evidence: "证据不足",
		pending: "等待复测完成",
	} as Record<string, string>)[currentRetest.conclusion] || currentRetest.conclusion : "";
	const syncConnectionReady = ["confirm", "syncing", "complete"].includes(syncPhase) || (syncPhase === "error" && syncAccounts.length > 0);
	const syncSelectionReady = ["syncing", "complete"].includes(syncPhase) || (syncPhase === "error" && selectedSyncAccounts.length > 0);
	const syncProgressSteps = [
		{
			label: "连接助手",
			hint: syncConnectionReady ? `${syncAccounts.length} 个匹配账号` : "检查扩展与登录状态",
			state: syncConnectionReady ? "done" : syncPhase === "discovering" ? "current" : syncPhase === "error" ? "issue" : "waiting",
		},
		{
			label: "确认平台",
			hint: syncPhase === "confirm" ? `已选择 ${selectedSyncAccounts.length}/${syncAccounts.length}` : syncSelectionReady ? `${selectedSyncAccounts.length} 个平台已确认` : "由你决定写入范围",
			state: syncSelectionReady ? "done" : syncPhase === "confirm" ? "current" : "waiting",
		},
		{
			label: "写入并回读",
			hint: syncPhase === "complete" ? "结果已按草稿链接归档" : "未回读不计为已保存",
			state: syncPhase === "complete" ? "done" : syncPhase === "syncing" ? "current" : syncPhase === "error" && selectedSyncAccounts.length > 0 ? "issue" : "waiting",
		},
	] as const;
	const visibleAgentProgress = agentProgress?.run.id === currentRunId ? agentProgress : null;
	const groupedAgentEvents = useMemo(() => groupAgentEvents(visibleAgentProgress?.events ?? []), [visibleAgentProgress?.events]);
	const agentTransportLabel = agentTransport === "live"
		? "实时事件已连接"
		: agentTransport === "fallback"
			? "实时连接中断，正在回读数据库"
			: agentTransport === "connecting"
				? "正在连接实时事件"
				: visibleAgentProgress
					? `${visibleAgentProgress.event_count} 条持久化事件`
					: "正在读取持久化进度";

	useEffect(() => {
		setSelectedBatchId(initialScope.batchId);
		setSelectedModel(initialScope.modelKey ?? "all");
		setSelectedQuestion(initialScope.questionPlanId ? String(initialScope.questionPlanId) : "all");
	}, [initialScope.batchId, initialScope.modelKey, initialScope.questionPlanId]);

	useEffect(() => setReviewPackages(initialReviewPackages), [initialReviewPackages]);
	useEffect(() => setDistributionRuns(initialDistributionRuns), [initialDistributionRuns]);
	useEffect(() => setRetests(initialRetests), [initialRetests]);
	useEffect(() => {
		if (!reviewOpen && !syncOpen) return;
		const previousOverflow = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		function closeModal(event: KeyboardEvent) {
			if (event.key !== "Escape" || isSaving) return;
			if (syncOpen) {
				if (syncPhase !== "syncing") setSyncOpen(false);
				return;
			}
			setReviewOpen(false);
		}
		document.addEventListener("keydown", closeModal);
		return () => {
			document.body.style.overflow = previousOverflow;
			document.removeEventListener("keydown", closeModal);
		};
	}, [isSaving, reviewOpen, syncOpen, syncPhase]);

	useEffect(() => {
		const actionId = selected?.existingAction?.id;
		if (!actionId) {
			setAgentEvents([]);
			setAgentProgress(null);
			return;
		}
		const activeActionId = actionId;
		let cancelled = false;
		setAgentProgress(null);
		setAgentDetailsExpanded(false);
		async function refresh() {
			try {
				const result = await readAgentProgress(activeActionId);
				if (!cancelled) {
					setAgentRuns((current) => [...current.filter((run) => run.action_id !== activeActionId), ...result.runs]);
					setAgentProgress(result.progress);
					setAgentEvents(result.progress?.events ?? []);
					setAgentFeedback("");
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
		if (!currentRunId || !currentRunStatus || !["queued", "resuming", "running", "cancelling"].includes(currentRunStatus)) {
			setAgentTransport(currentRunId ? "ended" : "idle");
			return;
		}
		const latestKnownEvent = agentEvents.at(-1);
		const after = latestKnownEvent?.agent_run_id === currentRunId ? latestKnownEvent.sequence : 0;
		setAgentTransport("connecting");
		const source = new EventSource(`/api/geo/${workspaceId}/agent-runs/${currentRunId}/events?after=${after}`);
		source.onopen = () => setAgentTransport("live");
		source.addEventListener("agent_event", (raw) => {
			const event = JSON.parse((raw as MessageEvent<string>).data) as CleanroomAgentEvent;
			setAgentEvents((current) => current.some((item) => item.id === event.id) ? current : [...current, event].sort((a, b) => a.sequence - b.sequence));
			setAgentRuns((current) => current.map((run) => run.id === currentRunId ? {
				...run,
				stage: event.stage,
				status: event.event_type === "awaiting_human_review" ? "awaiting_review" : event.event_type === "run_cancelled" ? "cancelled" : ["run_failed", "run_timed_out"].includes(event.event_type) ? "failed" : run.status === "queued" ? "running" : run.status,
			} : run));
		});
		source.addEventListener("end", () => { setAgentTransport("ended"); source.close(); router.refresh(); });
		source.onerror = () => { setAgentTransport("fallback"); source.close(); };
		return () => source.close();
	// The polling path above remains active as the authoritative fallback. Do not
	// reconnect the stream every time a new event is appended.
	// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [currentRunId, currentRunStatus, router, workspaceId]);

	useEffect(() => {
		const actionId = selected?.existingAction?.id;
		if (!actionId || !retestActive) return;
		const activeActionId = actionId;
		let cancelled = false;
		async function refreshRetest() {
			try {
				const result = await readRetest(activeActionId);
				if (cancelled) return;
				setRetests((current) => [result, ...current.filter((item) => item.action_id !== activeActionId)]);
				if (!["preparing", "queued", "running"].includes(result.status)) router.refresh();
			} catch (error) {
				if (!cancelled) setRetestMessage(error instanceof Error ? error.message : "无法读取复测进度");
			}
		}
		void refreshRetest();
		const timer = window.setInterval(() => void refreshRetest(), 2000);
		return () => { cancelled = true; window.clearInterval(timer); };
	}, [readRetest, retestActive, router, selected?.existingAction?.id]);

	function changeScope(next: { batchId?: number | null; modelKey?: string; questionPlanId?: number | null }) {
		const batchId = next.batchId !== undefined ? next.batchId : selectedBatchId;
		const batchChanged = next.batchId !== undefined && next.batchId !== selectedBatchId;
		const modelKey = batchChanged ? "all" : next.modelKey ?? selectedModel;
		const questionPlanId = batchChanged
			? null
			: next.questionPlanId !== undefined
				? next.questionPlanId
				: selectedQuestion === "all" ? null : Number(selectedQuestion);
		setDiscoveryFeedback("");
		setSelectedBatchId(batchId);
		setSelectedModel(modelKey);
		setSelectedQuestion(questionPlanId ? String(questionPlanId) : "all");
		const params = new URLSearchParams();
		if (batchId) params.set("batch", String(batchId));
		if (modelKey !== "all") params.set("model", modelKey);
		if (questionPlanId) params.set("question", String(questionPlanId));
		startScopeTransition(() => router.push(`/geo/${workspaceId}/actions?${params.toString()}`, { scroll: false }));
	}

	function refreshOpportunities() {
		setDiscoveryFeedback("");
		startSaving(async () => {
			try {
				await discoverActions({
					batchId: selectedBatchId,
					modelKey: selectedModel === "all" ? null : selectedModel,
					questionPlanId: selectedQuestion === "all" ? null : Number(selectedQuestion),
				});
				setDiscoveryFeedback("已按当前批次、模型和问题重新分析真实证据。");
				router.refresh();
			} catch (error) {
				setDiscoveryFeedback(error instanceof Error ? error.message : "无法刷新行动机会");
			}
		});
	}

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

	function requestRevision() {
		if (!currentRun || !currentReviewPackage || !reviewNeedsRevision) return;
		setReviewFeedback("");
		startSaving(async () => {
			try {
				const run = await reviseAgent(currentRun.id, currentReviewPackage.asset.id);
				setAgentRuns((current) => current.map((item) => item.id === run.id ? run : item));
				setReviewOpen(false);
				setAgentFeedback("已将人工修改意见交给原 Codex 任务；旧版本会保留。");
				router.refresh();
			} catch (error) {
				setReviewFeedback(error instanceof Error ? error.message : "无法启动内容修订");
			}
		});
	}

	function openReviewWorkbench() {
		if (!currentReviewPackage) return;
		setReviewTab("master");
		setConfirmedClaimIds([]);
		setReviewPlatformKeys(currentReviewPackage.variants.map((variant) => variant.platform_key));
		setReviewNote("");
		setReviewFeedback("");
		setReviewOpen(true);
	}

	function submitReview(verdict: "approved" | "changes_requested") {
		if (!currentReviewPackage) return;
		setReviewFeedback("");
		startSaving(async () => {
			try {
				const result = await decideReview(currentReviewPackage.asset.id, {
					verdict,
					confirmed_claim_ids: confirmedClaimIds,
					platform_keys: reviewPlatformKeys,
					note: reviewNote || null,
				});
				setReviewPackages((current) => [result, ...current.filter((item) => item.asset.id !== result.asset.id)]);
				setReviewFeedback(verdict === "approved" ? "审核已记录，已通过的平台稿可以交给文章同步助手。" : "修改要求已记录，本版本不会进入同步。");
				router.refresh();
			} catch (error) {
				setReviewFeedback(error instanceof Error ? error.message : "无法保存审核结果");
			}
		});
	}

	async function openSyncAssistant() {
		if (!syncAction || !currentReviewPackage || !approvedPlatformKeys.length) {
			setPreviewMessage("请先完成人工审核，至少通过一个平台稿。");
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
			const platformAccounts = accounts.filter((account) => {
				const platformKey = syncPlatformKey(account);
				return platformKey !== null && approvedPlatformKeys.includes(platformKey);
			});
			setSyncAccounts(platformAccounts);
			if (!platformAccounts.length) {
				setSyncPhase("error");
				setSyncMessage("没有检测到与已审核稿匹配的登录平台。请先在 EgoLite 中登录知乎或微信公众号。");
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

	async function confirmSync() {
		const api = getArticleSyncApi();
		const accounts = syncAccounts.filter((account) => selectedSyncAccounts.includes(account.type));
		if (!api || !syncAction || !currentReviewPackage || accounts.length === 0) return;
		const accountVariants = accounts.flatMap((account) => {
			const platformKey = syncPlatformKey(account);
			const variant = currentReviewPackage.variants.find((item) => item.platform_key === platformKey && approvedPlatformKeys.includes(item.platform_key));
			return platformKey && variant ? [{ account, platformKey, variant }] : [];
		});
		if (!accountVariants.length) return;
		setSyncPhase("syncing");
		setSyncMessage("正在按平台逐份写入已审核稿，不会执行发布…");
		try {
			const distribution = await createDistribution(currentReviewPackage.asset.id, accountVariants.map((item) => item.platformKey));
			setDistributionRuns((current) => [distribution, ...current.filter((item) => item.id !== distribution.id)]);
			const results = await Promise.all(accountVariants.map(({ account, variant }) => syncVariant(api, account, variant)));
			setSyncAccounts(results);
			const persisted = await recordDistributionResults(distribution.id, results.map((result, index) => ({
				platform_key: accountVariants[index].platformKey,
				request_status: result.status === "done" && result.editResp?.draftLink ? "draft_saved" as const : "failed" as const,
				draft_url: result.editResp?.draftLink || null,
				message: result.error || result.msg || null,
			})));
			setDistributionRuns((current) => [persisted, ...current.filter((item) => item.id !== persisted.id)]);
			const saved = persisted.targets.filter((target) => target.draft_readback_status === "draft_saved").length;
			setSyncPhase("complete");
			setSyncMessage(saved > 0 ? `${saved} 个平台草稿已回读并归档；最终发布仍由你确认。` : "未获得可回读的草稿链接，本次不计为已保存。");
			router.refresh();
		} catch (error) {
			setSyncPhase("error");
			setSyncMessage(error instanceof Error ? error.message : "文章同步助手写入失败。");
		}
	}

	function savePublication(targetId: number) {
		if (!currentDistribution) return;
		if (publicationRecordsLocked) {
			setPublicationMessage("同口径复测已建立，公开 URL 已锁定，避免复测依据发生漂移。");
			return;
		}
		const target = currentDistribution.targets.find((item) => item.id === targetId);
		const publicUrl = (publicationUrls[targetId] ?? target?.public_url ?? "").trim();
		if (!target || !publicUrl) {
			setPublicationMessage("请粘贴该平台的具体公开文章 URL。");
			return;
		}
		setPublicationMessage("");
		startSaving(async () => {
			try {
				const result = await recordHumanPublication(currentDistribution.id, targetId, publicUrl);
				setDistributionRuns((current) => [result, ...current.filter((item) => item.id !== result.id)]);
				setPublicationUrls((current) => ({ ...current, [targetId]: publicUrl }));
				const published = result.targets.filter((item) => item.human_publish_status === "published").length;
				setPublicationMessage(`${published}/${result.targets.length} 个平台已记录人工发布结果。系统没有代替你点击发布。`);
				router.refresh();
			} catch (error) {
				setPublicationMessage(error instanceof Error ? error.message : "无法保存发布结果");
			}
		});
	}

	function beginRetest() {
		if (!selected?.existingAction || !allTargetsPublished) return;
		setRetestMessage("");
		startSaving(async () => {
			try {
				const result = await createRetest(selected.existingAction!.id);
				setRetests((current) => [result, ...current.filter((item) => item.action_id !== result.action_id)]);
				setRetestMessage("复测已按基线问题、模型版本和重复次数进入真实观测队列。");
				router.refresh();
			} catch (error) {
				setRetestMessage(error instanceof Error ? error.message : "无法创建同口径复测");
			}
		});
	}

	return <main className="pa-page">
		<section className="pa-topline">
			<header className="pa-hero">
				<div><h1>优先行动</h1><span>从真实观测缺口出发，补齐信源、生成内容、写入草稿，并在下一轮验证变化。</span>
					<div className="pa-runtime-wrap">
						<button type="button" className={`pa-runtime-status${!agentRuntime?.ready ? " is-warning" : agentCapacityAvailable ? " is-ready" : " is-busy"}`} onClick={() => setRuntimeExpanded((value) => !value)} aria-expanded={runtimeExpanded}>
							<i />{!agentRuntime?.ready ? "Codex 需要处理" : agentCapacityAvailable ? "Codex 已连接" : `Codex 正在执行 ${agentCapacityUsed}/${agentCapacityLimit}`}<Icon name="chevron" />
						</button>
						{runtimeExpanded ? <div className="pa-runtime-popover" role="status"><b>{!agentRuntime?.ready ? "本机 Agent 当前不可启动" : agentCapacityAvailable ? "本机 Agent 可以启动" : "本机 Agent 正在处理其他任务"}</b><span>{agentRuntime?.default_model || "未检测到默认模型"}</span><small>{agentRuntime?.ready ? `运行容量 ${agentCapacityUsed}/${agentCapacityLimit} · 单次最长 ${agentTimeoutMinutes} 分钟 · ${runtimeVersionLabel(agentRuntime.runtime_version)}` : agentRuntime?.error || "请在设置中完成登录或自检。"}</small><Link href={`/geo/${workspaceId}/settings`}>查看 Agent 设置</Link></div> : null}
					</div>
					<div className="pa-filters" aria-label="筛选行动机会">
						<label><Icon name="calendar" /><select aria-label="观测批次" value={selectedBatchId ?? ""} disabled={isScopePending || !opportunityScope.batches.length} onChange={(event) => changeScope({ batchId: Number(event.target.value) || null })}><option value="">暂无可用批次</option>{opportunityScope.batches.map((batch) => <option key={batch.id} value={batch.id}>批次 #{batch.id} · {batch.eligible_evidence_count} 条有效证据</option>)}</select><Icon name="chevron" /></label>
						<label><Icon name="filter" /><select aria-label="模型范围" value={selectedModel} disabled={isScopePending || !selectedBatch} onChange={(event) => changeScope({ modelKey: event.target.value })}><option value="all">全部模型</option>{models.map((model) => <option key={model.key} value={model.key}>{model.label}</option>)}</select><Icon name="chevron" /></label>
						<label><Icon name="spark" /><select aria-label="问题范围" value={selectedQuestion} disabled={isScopePending || !selectedBatch} onChange={(event) => changeScope({ questionPlanId: event.target.value === "all" ? null : Number(event.target.value) })}><option value="all">全部问题</option>{questions.map((question) => <option key={question.id} value={question.id}>{question.label}</option>)}</select><Icon name="chevron" /></label>
					</div>
					<div className="pa-discovery-row"><button type="button" onClick={refreshOpportunities} disabled={isSaving || isScopePending || !selectedBatchId}>{isSaving ? "正在分析真实证据…" : "按当前范围刷新机会"}</button><span>{isScopePending ? "正在切换范围，不显示旧结果…" : discoveryFeedback || (selectedBatch ? `当前范围来自批次 #${selectedBatch.id}` : "需要先完成一次真实联网观测")}</span></div>
				</div>
			</header>

			<section className="pa-summary" aria-label="行动状态摘要">
				<article><span className="pa-summary-icon is-warning"><Icon name="warning" /></span><div><small>待处理缺口</small><strong>{isScopePending ? "—" : actionable.length}</strong></div></article>
				<article><span className="pa-summary-icon is-trend"><Icon name="trend" /></span><div><small>高优先级</small><strong>{isScopePending ? "—" : high}</strong></div></article>
				<article><span className="pa-summary-icon is-draft"><Icon name="draft" /></span><div><small>草稿待确认</small><strong>{pendingActions}</strong></div></article>
				<article><span className="pa-summary-icon is-check"><Icon name="check" /></span><div><small>复测已完成</small><strong>{retestReady}</strong></div></article>
			</section>
		</section>

			{isScopePending ? <section className="pa-scope-loading" role="status" aria-live="polite"><div><i /><b>正在切换真实数据范围</b><span>新范围返回前不会继续展示旧机会。</span></div><div className="pa-scope-skeleton"><i /><i /><i /></div></section> : filtered.length === 0 ? <section className="pa-empty"><span><Icon name="spark" /></span><h2>当前范围没有达到门槛的机会</h2><p>{selectedBatch ? "这里只接受完整回答、真实搜索事件、来源 URL 和原始工件都齐全的证据。可以刷新当前范围，或返回决策地图发起新观测。" : "完成一次真实联网观测并归档完整证据后，系统才会识别行动机会。"}</p><div className="pa-empty-actions"><button type="button" onClick={refreshOpportunities} disabled={isSaving || !selectedBatchId}>{isSaving ? "正在分析…" : "刷新当前范围"}</button><Link href={`/geo/${workspaceId}`}>发起真实观测 <Icon name="arrow" /></Link></div></section> : <>
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
						<ActionStage index={2} label="Agent 调研与生成" state={runActive ? "active" : currentReviewPackage ? "done" : currentRun ? "idle" : stage === 1 ? "active" : "idle"}>
							{stage === 1 && selected.existingAction && !currentRun ? <div className="pa-stage-card"><b>目标平台</b><p>Codex 会先查阅平台官方规则，再根据真实观测和品牌官网生成差异化草稿。</p><div className="pa-platform-picker">{platformOptions.map((platform) => <label key={platform.key} className={targetPlatforms.includes(platform.key) ? "is-selected" : ""}><input type="checkbox" checked={targetPlatforms.includes(platform.key)} onChange={() => setTargetPlatforms((current) => current.includes(platform.key) ? current.filter((key) => key !== platform.key) : [...current, platform.key])} /><img src={platform.logo} alt={`${platform.label} 官方标志`} /><span>{platform.label}</span></label>)}</div><button disabled={isSaving || !targetPlatforms.length || !agentCanStart} type="button" onClick={beginAgent}><Icon name="spark" />{isSaving ? "正在入队…" : !agentRuntime?.ready ? "Codex 未就绪，请先去设置" : !agentCapacityAvailable ? "Agent 正忙，请等待当前任务" : "启动本机 Codex Agent"}</button></div> : null}
							{currentRun ? <div className="pa-agent-run">
								<div className="pa-agent-runtime">
									<span><img src="/brand/openai.svg" alt="OpenAI 官方标志" /></span>
									<div><b>{currentRun.model || "Local Codex"}</b><small>Run #{currentRun.id} · {agentStageLabels[currentRun.stage] || currentRun.stage}</small></div>
									{visibleAgentProgress ? <strong>{visibleAgentProgress.progress_percent}%</strong> : null}
								</div>
								<p>{agentEvents.at(-1)?.message || (currentRun.status === "queued" ? "已入队，等待 worker 接受。" : "正在读取持久化进度…")}</p>
								{visibleAgentProgress ? <>
									<div className="pa-agent-meter" role="progressbar" aria-label="Agent 确定阶段进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={visibleAgentProgress.progress_percent}><i style={{ width: `${visibleAgentProgress.progress_percent}%` }} /></div>
									<div className="pa-agent-run-meta">
										<span>{runActive ? "已运行" : "本次耗时"} {formatAgentDuration(visibleAgentProgress.elapsed_seconds)}</span>
										{visibleAgentProgress.timeout_remaining_seconds !== null && visibleAgentProgress.timeout_remaining_seconds !== undefined ? <span>距自动中止约 {formatAgentDuration(visibleAgentProgress.timeout_remaining_seconds)}</span> : null}
										<span className={`is-${agentTransport}`}>{agentTransportLabel}</span>
									</div>
									<ol className="pa-agent-stages" aria-label="Agent 五阶段真实进度">
										{visibleAgentProgress.stages.map((progressStage, index) => <li key={progressStage.key} className={`is-${progressStage.state}`}>
											<i>{progressStage.state === "done" ? <Icon name="check" /> : index + 1}</i>
											<div><b>{progressStage.label}</b>{progressStage.message ? <small>{progressStage.message}</small> : null}</div>
											<em>{progressStage.state === "failed" && currentRun.status === "cancelled" ? "已中止" : agentProgressStateLabels[progressStage.state]}</em>
										</li>)}
									</ol>
									<div className="pa-agent-artifacts">
										<b>已持久化结果</b>
										{visibleAgentProgress.artifacts.length ? visibleAgentProgress.artifacts.map((artifact) => <span key={artifact.id}>结构化结果 · {formatArtifactSize(artifact.size_bytes)} · 已校验归档</span>) : <span>尚未产生可审核工件</span>}
										{currentReviewPackage ? <span>内容资产 #{currentReviewPackage.asset.id} · {currentReviewPackage.variants.length} 个平台稿 · {currentReviewPackage.claims.length} 条主张</span> : null}
									</div>
									{visibleAgentProgress.event_count ? <button className="pa-agent-log-toggle" type="button" onClick={() => setAgentDetailsExpanded((value) => !value)} aria-expanded={agentDetailsExpanded}>{agentDetailsExpanded ? "收起执行记录" : `查看 ${visibleAgentProgress.event_count} 条执行记录`} <Icon name="chevron" /></button> : null}
									{agentDetailsExpanded ? <><small className="pa-agent-log-note">连续重复事件已合并展示，原始事件完整保留。</small><ul className="pa-agent-event-log">{groupedAgentEvents.map((event) => <li key={event.key}><time>{formatEventTime(event.firstAt)}{event.count > 1 ? `–${formatEventTime(event.lastAt)}` : ""}</time><span><b>{agentStageLabels[event.stage] || event.stage}{event.count > 1 ? ` · ${event.count} 次` : ""}</b>{event.message}</span></li>)}</ul></> : null}
								</> : null}
								{currentRun.status === "failed" && currentRun.error_message ? <p className="is-error">{currentRun.error_message}</p> : null}
								<div className="pa-agent-actions">{runActive && currentRun.status !== "cancelling" ? <button type="button" onClick={requestInterrupt} disabled={isSaving}>中止运行</button> : null}{["cancelled", "failed"].includes(currentRun.status) && currentRun.codex_thread_id ? <button type="button" onClick={requestResume} disabled={isSaving || !agentCanStart}>{agentCapacityAvailable ? "恢复原任务" : "Agent 正忙"}</button> : null}{["cancelled", "failed"].includes(currentRun.status) && !currentRun.codex_thread_id ? <button type="button" onClick={beginAgent} disabled={isSaving || !agentCanStart}>{agentCapacityAvailable ? "重新启动" : "Agent 正忙"}</button> : null}</div>
							</div> : null}
							{agentFeedback ? <p className="pa-agent-error" role="status">{agentFeedback}</p> : null}
						</ActionStage>
						<ActionStage index={3} label="人工审核" state={approvedPlatformKeys.length ? "done" : currentReviewPackage && !(reviewNeedsRevision && runActive) ? "active" : "idle"}>{currentReviewPackage ? <div className={`pa-stage-card${reviewNeedsRevision ? " is-revision" : ""}`}><b>{approvedPlatformKeys.length ? `已通过 ${approvedPlatformKeys.length} 个平台稿` : reviewNeedsRevision ? (runActive ? "正在根据意见修订" : "已退回，等待生成新版本") : "草稿已入库，等待你确认"}</b><p>内容资产 #{currentReviewPackage.asset.id} · v{currentReviewPackage.asset.version} · {currentReviewPackage.variants.length} 个平台版本 · {currentReviewPackage.pending_claim_count} 条主张需人工确认。</p>{reviewNeedsRevision && !runActive ? <button type="button" onClick={requestRevision} disabled={isSaving}>{isSaving ? "正在排队…" : "根据意见生成新版本"}</button> : <button type="button" onClick={openReviewWorkbench}>{approvedPlatformKeys.length ? "查看审核记录" : reviewNeedsRevision ? "查看退回意见" : "审阅内容与事实"}</button>}</div> : <p className="pa-stage-note">只有 Agent 成功生成并持久化内容后，审核才会开放。</p>}</ActionStage>
						<ActionStage index={4} label="写入平台草稿" state={allDraftsSaved ? "done" : approvedPlatformKeys.length ? "active" : "idle"}>{approvedPlatformKeys.length ? <div className="pa-stage-card"><b>{allDraftsSaved ? `${savedDraftCount} 个草稿已回读` : "已通过的平台稿可写入"}</b><p>{currentDistribution ? `同步任务 #${currentDistribution.id} · ${savedDraftCount}/${currentDistribution.targets.length} 个平台返回真实草稿。` : "打开同步助手后，你选择平台并确认写入；系统不会发布。"}</p><button type="button" onClick={openSyncAssistant} disabled={allDraftsSaved}>{allDraftsSaved ? "已写入平台草稿" : "打开文章同步助手"}</button></div> : <p className="pa-stage-note">只允许写入草稿，最终发布仍由人工确认。</p>}</ActionStage>
						<ActionStage index={5} label="人工发布" state={allTargetsPublished ? "done" : allDraftsSaved ? "active" : "idle"}>
							{allDraftsSaved && currentDistribution ? <div className="pa-publication-list">{currentDistribution.targets.map((target) => {
								const platform = platformOptions.find((item) => item.key === target.platform_key);
								const published = target.human_publish_status === "published" && Boolean(target.public_url);
								return <section key={target.id} className={published ? "is-published" : ""}><header><span>{platform ? <img src={platform.logo} alt="" /> : null}<b>{platform?.label || target.platform_key}</b></span><small>{publicationRecordsLocked ? "复测已开始，记录已锁定" : published ? "人工已记录" : "等待人工发布"}</small></header><div><input type="url" aria-label={`${platform?.label || target.platform_key}公开文章 URL`} placeholder="粘贴具体公开文章 URL" value={publicationUrls[target.id] ?? target.public_url ?? ""} disabled={publicationRecordsLocked} onChange={(event) => setPublicationUrls((current) => ({ ...current, [target.id]: event.target.value }))} /><button type="button" disabled={publicationRecordsLocked || isSaving || !((publicationUrls[target.id] ?? target.public_url ?? "").trim())} onClick={() => savePublication(target.id)}>{publicationRecordsLocked ? "已锁定" : published ? "更正记录" : "记录发布"}</button></div>{target.draft_url ? <a href={target.draft_url} target="_blank" rel="noreferrer">打开平台草稿</a> : null}{target.public_url ? <a href={target.public_url} target="_blank" rel="noreferrer">查看公开文章</a> : null}</section>;
							})}{publicationMessage ? <p className="pa-inline-feedback" role="status">{publicationMessage}</p> : null}</div> : <p className="pa-stage-note">草稿真实回读后，才可记录人工发布结果。</p>}
						</ActionStage>
						<ActionStage index={6} label="同口径复测" state={comparableRetestComplete ? "done" : retestActive || allTargetsPublished ? "active" : "idle"}>
							{allTargetsPublished ? <div className="pa-stage-card pa-retest-card"><b>{retestComplete ? retestConclusionLabel : retestActive ? "真实联网复测进行中" : "可以创建可比复测"}</b><p>{currentRetest ? `基线批次 #${currentRetest.baseline_batch_id} · ${retestProviderCount} 个模型 × ${retestRepeatCount} 次 · 原问题不变。` : "后端会复用基线问题、模型渠道、模型版本和重复次数；不允许前端自行改变口径。"}</p>{currentRetest?.batch ? <><div className="pa-retest-progress" aria-label={`复测进度 ${currentRetest.batch.progress_percent}%`}><i style={{ width: `${currentRetest.batch.progress_percent}%` }} /></div><small>{currentRetest.batch.succeeded + currentRetest.batch.failed}/{currentRetest.batch.total} 已结束 · 成功 {currentRetest.batch.succeeded} · 失败 {currentRetest.batch.failed}</small></> : null}{!retestActive && (!retestComplete || !comparableRetestComplete) ? <button type="button" onClick={beginRetest} disabled={isSaving}>{isSaving ? "正在创建…" : currentRetest?.conclusion === "insufficient_evidence" ? "重新创建同口径复测" : "创建真实复测"}</button> : null}{retestComplete ? <p className={comparableRetestComplete ? "is-success" : "is-warning"}>{comparableRetestComplete ? `结论：${retestConclusionLabel}。该结论只描述同口径观测差异，不宣称发布构成因果。` : "本轮已经结束，但样本或模型版本不完整，不能得出变化结论。"}</p> : null}{retestMessage ? <p className="pa-inline-feedback" role="status">{retestMessage}</p> : null}</div> : <p className="pa-stage-note">全部目标平台记录真实公开 URL 后，复测入口才会开放。</p>}
						</ActionStage>
					</ol> : !isTimelineCollapsed ? <p className="pa-empty-copy">调整筛选条件后，选择一个机会开始。</p> : null}
				</aside>
			</section>

			{actions.length > 0 ? <section className="pa-progress">
				<header><div><h2>内容与发布进度</h2><p>只由已持久化的 Agent 运行与人工状态推进；未运行不显示为生成中。</p></div></header>
				<div className="pa-progress-lanes"><div className={activeAgentRunCount ? "is-current" : ""}><b>Agent 生成</b><span>{generatedAssetCount}</span><p>{activeAgentRunCount ? `${activeAgentRunCount} 个任务正在调研与生成` : generatedAssetCount ? "已生成内容进入后续流程" : "还没有已持久化的生成结果"}</p></div><div className={currentRun?.stage === "researching_brand" ? "is-current" : ""}><b>事实校验</b><span>{currentReviewPackage?.claims.filter((claim) => claim.verification_status === "source_linked").length ?? 0}</span><p>可追溯主张与待人工确认项分开记录</p></div><div className={currentRun?.stage === "adapting_platforms" ? "is-current" : ""}><b>平台适配</b><span>{currentReviewPackage?.variants.length ?? 0}</span><p>每个平台保留独立标题、结构和语气</p></div><div className={currentReviewPackage && !approvedPlatformKeys.length ? "is-current" : ""}><b>人工审核</b><span>{pendingActions}</span><p>{approvedPlatformKeys.length ? `${approvedPlatformKeys.length} 个平台稿已通过` : "审核前不会触发同步"}</p></div><div className={approvedPlatformKeys.length && !allDraftsSaved ? "is-current" : ""}><b>写入草稿</b><span>{distributionRuns.reduce((count, run) => count + run.targets.filter((target) => target.draft_readback_status === "draft_saved").length, 0)}</span><p>{currentDistribution ? `${savedDraftCount}/${currentDistribution.targets.length} 个目标有真实草稿回读` : "等待审核通过后人工触发"}</p></div><div className={allDraftsSaved && !allTargetsPublished ? "is-current" : ""}><b>人工发布</b><span>{distributionRuns.reduce((count, run) => count + run.targets.filter((target) => target.human_publish_status === "published").length, 0)}</span><p>{currentDistribution ? `${publishedTargetCount}/${currentDistribution.targets.length} 个平台已记录公开 URL` : "发布始终由人工在平台完成"}</p></div><div className={retestActive ? "is-current" : ""}><b>同口径复测</b><span>{retests.filter((item) => item.status === "completed").length}</span><p>{currentRetest?.batch ? `真实队列 ${currentRetest.batch.progress_percent}%` : "发布完成后复用原问题与模型"}</p></div></div>
				<footer className="pa-progress-footer"><span><Icon name="eye" />生成、审核、草稿回读、发布与复测都使用独立真实状态</span><div><Link href={`/geo/${workspaceId}/content`}>查看内容库</Link><button type="button" onClick={currentReviewPackage ? openReviewWorkbench : () => setPreviewMessage("请先完成 Agent 调研与生成。")}>预览内容</button><button className="pa-sync-button" type="button" onClick={openSyncAssistant} disabled={!approvedPlatformKeys.length} title={approvedPlatformKeys.length ? "打开文章同步助手" : "请先通过至少一个平台稿"}>打开同步助手 <Icon name="arrow" /></button></div></footer>
				{previewMessage ? <p className="pa-front-notice" role="status">{previewMessage}</p> : null}
			</section> : null}
		{reviewOpen && currentReviewPackage ? <div className="pa-review-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !isSaving) setReviewOpen(false); }}>
			<section className="pa-review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-workbench-title">
				<header><div><small>人工审核 · 内容资产 #{currentReviewPackage.asset.id}</small><h2 id="review-workbench-title">确认事实，再决定哪些平台稿可以同步</h2><p>Agent 结果不会自动获得批准。平台稿可以分别通过或保留待修改。</p></div><button type="button" onClick={() => setReviewOpen(false)} disabled={isSaving} aria-label="关闭审核工作台">×</button></header>
				<nav className="pa-review-tabs" aria-label="内容版本">
					<button type="button" className={reviewTab === "master" ? "is-active" : ""} onClick={() => setReviewTab("master")}><Icon name="draft" />母稿</button>
					{currentReviewPackage.variants.map((variant) => {
						const platform = platformOptions.find((item) => item.key === variant.platform_key);
						return <button key={variant.id} type="button" className={reviewTab === variant.platform_key ? "is-active" : ""} onClick={() => setReviewTab(variant.platform_key)}>{platform ? <img src={platform.logo} alt="" /> : null}{platform?.label || variant.platform_key}<span>{variant.status === "approved" ? "已通过" : "待审"}</span></button>;
					})}
				</nav>
				<div className="pa-review-body">
					<article className="pa-review-document">
						{reviewTab === "master" ? <><small>母稿 · v{currentReviewPackage.asset.version}</small><h3>{currentReviewPackage.asset.title}</h3><p className="pa-review-summary">{currentReviewPackage.asset.summary}</p><div className="pa-review-copy" dangerouslySetInnerHTML={{ __html: basicMarkdownHtml(currentReviewPackage.asset.body_markdown) }} /></> : (() => {
							const variant = currentReviewPackage.variants.find((item) => item.platform_key === reviewTab);
							if (!variant) return null;
							return <><small>{platformOptions.find((item) => item.key === variant.platform_key)?.label || variant.platform_key} · {variant.policy_version}</small><h3>{variant.title}</h3><p className="pa-review-summary">{variant.summary}</p><div className="pa-review-copy" dangerouslySetInnerHTML={{ __html: basicMarkdownHtml(variant.body_markdown) }} /></>;
						})()}
					</article>
					<aside className="pa-review-checks">
						<section><header><div><b>事实与来源</b><small>{currentReviewPackage.claims.length - pendingClaims.length} 条已有来源 · {pendingClaims.length} 条待确认</small></div></header><div className="pa-claim-list">{currentReviewPackage.claims.map((claim) => {
							const confirmed = ["source_linked", "verified", "human_confirmed"].includes(claim.verification_status) || confirmedClaimIds.includes(claim.id);
							const needsHuman = !["source_linked", "verified", "human_confirmed"].includes(claim.verification_status);
							return <label key={claim.id} className={confirmed ? "is-confirmed" : "is-pending"}><input type="checkbox" checked={confirmed} disabled={!needsHuman || approvedPlatformKeys.length > 0} onChange={() => setConfirmedClaimIds((current) => current.includes(claim.id) ? current.filter((id) => id !== claim.id) : [...current, claim.id])} /><span><b>{needsHuman ? "需要你确认" : "已关联来源"}</b><small>{claim.claim_text}</small>{claim.source_url ? <a href={claim.source_url} target="_blank" rel="noreferrer">查看来源</a> : <em>无外部来源，勾选表示你对该品牌事实负责</em>}</span></label>;
						})}</div></section>
						<section><header><div><b>通过的平台稿</b><small>只有选中的版本会开放同步</small></div></header><div className="pa-review-platforms">{currentReviewPackage.variants.map((variant) => { const platform = platformOptions.find((item) => item.key === variant.platform_key); return <label key={variant.id}><input type="checkbox" checked={reviewPlatformKeys.includes(variant.platform_key) || approvedPlatformKeys.includes(variant.platform_key)} disabled={approvedPlatformKeys.includes(variant.platform_key)} onChange={() => setReviewPlatformKeys((current) => current.includes(variant.platform_key) ? current.filter((key) => key !== variant.platform_key) : [...current, variant.platform_key])} />{platform ? <img src={platform.logo} alt="" /> : null}<span><b>{platform?.label || variant.platform_key}</b><small>{variant.title}</small></span></label>; })}</div></section>
						<label className="pa-review-note"><span>审核意见</span><textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="退回修改时必填；通过时可记录核对说明。" rows={3} /></label>
						{reviewFeedback ? <p className="pa-review-feedback" role="status">{reviewFeedback}</p> : null}
					</aside>
				</div>
				<footer><span>{reviewNeedsRevision ? "旧版本和退回意见都会保留，新版本需重新审核。" : approvedPlatformKeys.length ? `审核已记录：${approvedPlatformKeys.length} 个平台稿已通过。` : `已确认 ${confirmedPendingClaimCount}/${pendingClaims.length} 条待确认事实 · 已选择 ${reviewPlatformKeys.length} 个平台稿。通过后仍不会写入草稿或发布。`}</span><div>{reviewNeedsRevision ? <button className="is-primary" type="button" onClick={requestRevision} disabled={isSaving || runActive}>{isSaving ? "正在排队…" : runActive ? "新版本生成中" : "根据意见生成新版本"}</button> : <><button type="button" onClick={() => submitReview("changes_requested")} disabled={isSaving || !reviewNote.trim()}>退回修改</button><button className="is-primary" type="button" onClick={() => submitReview("approved")} disabled={isSaving || !reviewPlatformKeys.length || remainingPendingClaimCount > 0 || approvedPlatformKeys.length > 0}>{isSaving ? "正在保存…" : approvedPlatformKeys.length ? "审核已记录" : remainingPendingClaimCount > 0 ? `还需确认 ${remainingPendingClaimCount} 条事实` : `通过 ${reviewPlatformKeys.length} 个平台稿`}</button></>}</div></footer>
			</section>
		</div> : null}
		{syncOpen ? <div className="pa-sync-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && syncPhase !== "syncing") setSyncOpen(false); }}>
			<section className="pa-sync-dialog" role="dialog" aria-modal="true" aria-labelledby="sync-assistant-title">
				<header><div><small>文章同步助手</small><h2 id="sync-assistant-title">选择平台并确认写入</h2></div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"} aria-label="关闭同步助手">×</button></header>
				<div className="pa-sync-body">
					<div className="pa-sync-summary"><b>{currentReviewPackage?.asset.title || syncAction?.title}</b><p>将按平台分别使用已审核的标题和正文；只保存草稿，不执行发布。</p></div>
					<ol className="pa-sync-progress" aria-label="同步助手进度">{syncProgressSteps.map((step, index) => <li className={`is-${step.state}`} key={step.label}><i>{step.state === "done" ? "✓" : step.state === "issue" ? "!" : index + 1}</i><span><b>{step.label}</b><small>{step.hint}</small></span></li>)}</ol>
					<p className={`pa-sync-message is-${syncPhase}`} role="status">{syncMessage}</p>
					{syncAccounts.length ? <div className="pa-sync-platforms">{syncAccounts.map((account) => {
						const disabled = syncPhase !== "confirm";
						const checked = selectedSyncAccounts.includes(account.type);
						return <label key={account.type} className={checked ? "is-selected" : ""}><input type="checkbox" checked={checked} disabled={disabled} onChange={() => setSelectedSyncAccounts((current) => current.includes(account.type) ? current.filter((value) => value !== account.type) : [...current, account.type])} /><span><b>{account.displayName || account.title}</b><small>{account.status === "done" ? "草稿已返回" : account.status === "failed" ? (account.error || "写入失败") : account.msg || account.title}</small></span>{account.editResp?.draftLink ? <a href={account.editResp.draftLink} target="_blank" rel="noreferrer">打开草稿</a> : null}</label>;
					})}</div> : null}
				</div>
				<footer><span>确认只会触发草稿写入，不会点击平台发布。</span><div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"}>取消</button>{syncPhase === "confirm" ? <button className="is-primary" type="button" onClick={confirmSync} disabled={!selectedSyncAccounts.length}>确认写入 {selectedSyncAccounts.length} 个平台</button> : null}{syncPhase === "error" ? <button className="is-primary" type="button" onClick={openSyncAssistant}>重新检测</button> : null}</div></footer>
			</section>
		</div> : null}
		</>}
	</main>;
}
