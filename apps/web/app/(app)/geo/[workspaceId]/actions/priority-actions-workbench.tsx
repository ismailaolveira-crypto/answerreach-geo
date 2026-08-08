"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";
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
	CleanroomOpportunityAnalysisRun,
	CleanroomPlatformVariant,
	WebsiteGapAnalysisRun,
} from "@/lib/cleanroom-v1-api";
import {
	articleSyncAccountKey,
	articleSyncPlatformKey,
	discoverArticleSyncAccounts,
	getArticleSyncPageApi,
	type ArticleSyncAccount,
	type ArticleSyncPageApi,
} from "@/lib/article-sync-page-bridge";
import { capturedVisualPurpose } from "@/lib/captured-visual";
import { markdownToSafeHtml } from "@/lib/markdown-html";
import type { PriorityActionOpportunity } from "./priority-action-opportunities";

type Props = {
	workspaceId: string;
	opportunities: PriorityActionOpportunity[];
	opportunityScope: CleanroomActionOpportunityScope;
	initialScope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null };
	initialSelectedId?: string;
	actions: CleanroomAction[];
	agentRuntime: AgentRuntime | null;
	activeSourcedBrandFactCount: number;
	websiteUrl: string | null;
	initialOpportunityAnalysis: CleanroomOpportunityAnalysisRun | null;
	initialWebsiteGapAnalysis: WebsiteGapAnalysisRun | null;
	initialAgentRuns: CleanroomAgentRun[];
	initialReviewPackages: CleanroomContentReviewPackage[];
	initialDistributionRuns: CleanroomDistributionRun[];
	initialRetests: CleanroomActionRetest[];
	createAction: (formData: FormData) => Promise<void>;
	startAgent: (actionId: number, platforms: string[]) => Promise<CleanroomAgentRun>;
	interruptAgent: (runId: number) => Promise<CleanroomAgentRun>;
	resumeAgent: (runId: number) => Promise<CleanroomAgentRun>;
	reviseAgent: (runId: number, contentAssetId: number) => Promise<CleanroomAgentRun>;
	captureAgentVisuals: (runId: number) => Promise<CleanroomAgentRunProgress>;
	readAgentProgress: (actionId: number) => Promise<{ runs: CleanroomAgentRun[]; progress: CleanroomAgentRunProgress | null }>;
	decideReview: (assetId: number, payload: { verdict: "approved" | "changes_requested"; confirmed_claim_ids: number[]; unverified_claim_ids: number[]; platform_keys: string[]; reviewed_platform_keys: string[]; note?: string | null }) => Promise<CleanroomContentReviewPackage>;
	savePlatformVariant: (variantId: number, payload: { title: string; summary: string; body_markdown: string; tags?: string[]; category?: string | null }) => Promise<CleanroomPlatformVariant>;
	createDistribution: (assetId: number, platformKeys: string[]) => Promise<CleanroomDistributionRun>;
	recordDistributionResults: (runId: number, targets: Array<{ platform_key: string; request_status: "draft_link_returned" | "draft_saved" | "failed" | "cancelled"; draft_url?: string | null; external_draft_id?: string | null; message?: string | null }>) => Promise<CleanroomDistributionRun>;
	confirmDraftReadback: (runId: number, targetId: number) => Promise<CleanroomDistributionRun>;
	recordHumanPublication: (runId: number, targetId: number, publicUrl: string) => Promise<CleanroomDistributionRun>;
	createRetest: (actionId: number) => Promise<CleanroomActionRetest>;
	readRetest: (actionId: number) => Promise<CleanroomActionRetest>;
	discoverActions: (scope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null }) => Promise<CleanroomOpportunityAnalysisRun>;
	readOpportunityAnalysis: (jobId: number) => Promise<CleanroomOpportunityAnalysisRun>;
	analyzeWebsiteGap: (scope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null }) => Promise<WebsiteGapAnalysisRun>;
	readWebsiteGapAnalysis: (jobId: number) => Promise<WebsiteGapAnalysisRun>;
};

function syncVariant(
	api: ArticleSyncPageApi,
	account: ArticleSyncAccount,
	variant: CleanroomPlatformVariant,
	onUpdate: (account: ArticleSyncAccount) => void,
) {
	return new Promise<ArticleSyncAccount>((resolve) => {
		let settled = false;
		const finish = (result: ArticleSyncAccount) => {
			if (settled) return;
			settled = true;
			window.clearTimeout(timeout);
			onUpdate(result);
			resolve(result);
		};
		const timeout = window.setTimeout(() => finish({ ...account, status: "failed", error: "写入等待超时" }), 180_000);
		onUpdate({ ...account, status: "uploading", msg: "准备写入平台草稿…" });
		api.addTask(
			{
				post: {
					title: variant.title,
					content: markdownToSafeHtml(variant.body_markdown),
					markdown: variant.body_markdown,
				},
				accounts: [account],
			},
			(task) => {
				const result = task.accounts?.[0];
				if (result) onUpdate(result);
				if (result?.status === "done" || result?.status === "failed") finish(result);
			},
			() => undefined,
		);
	});
}

const priorityLabel = { high: "高优先级", medium: "中优先级", low: "持续观察" } as const;
const typeLabel = { visibility: "候选缺口", citation: "引用缺口", competitor: "竞品领先", website: "官网审计" } as const;

type ReviewVisualAsset = {
	artifactId: number;
	altText: string;
	purpose: string;
	sourceHost: string;
	sourceUrl: string;
	sha256: string;
};

function reviewVisualAssets(variants: CleanroomPlatformVariant[]): ReviewVisualAsset[] {
	const items = new Map<number, ReviewVisualAsset>();
	for (const variant of variants) {
		for (const manifest of variant.image_manifest) {
			const artifactId = Number(manifest.artifact_id || 0);
			const sourceUrl = typeof manifest.source_url === "string" ? manifest.source_url : "";
			if (artifactId < 1 || !sourceUrl || manifest.quality_gate !== "passed") continue;
			let sourceHost = sourceUrl;
			try {
				sourceHost = new URL(sourceUrl).hostname;
			} catch {
				continue;
			}
			items.set(artifactId, {
				artifactId,
				altText: typeof manifest.alt_text === "string" ? manifest.alt_text : "官网归档素材",
				purpose: capturedVisualPurpose(manifest.purpose),
				sourceHost,
				sourceUrl,
				sha256: typeof manifest.sha256 === "string" ? manifest.sha256 : "",
			});
		}
	}
	return [...items.values()];
}

function suggestedSources(type: PriorityActionOpportunity["type"]) {
	if (type === "website") return ["服务端正文", "页面标题结构", "结构化数据"];
	if (type === "citation") return ["关键指标释义", "应用场景说明", "行业解决方案"];
	if (type === "competitor") return ["客户证言", "权威媒体报道", "第三方评测"];
	return ["企业选型对比", "私有化部署说明", "真实客户案例"];
}

function suggestedCarrier(type: PriorityActionOpportunity["type"]) {
	if (type === "website") return "官网服务端正文 + FAQ";
	if (type === "citation") return "官网解决方案页 + 技术文章";
	if (type === "competitor") return "深度回答 + 媒体稿件";
	return "官网专题页 + 深度回答";
}

function modelBrand(label: string) {
	const value = label.toLowerCase();
	if (value.includes("deepseek")) return "deepseek";
	if (value.includes("doubao") || value.includes("豆包")) return "doubao";
	if (value.includes("qwen") || value.includes("qianwen") || value.includes("千问")) return "qwen";
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

function initialSelectedOpportunityId(opportunities: PriorityActionOpportunity[]) {
	const latestAction = opportunities
		.filter((item) => item.existingAction)
		.sort((left, right) => (right.existingAction?.id ?? 0) - (left.existingAction?.id ?? 0))[0];
	return latestAction?.id ?? opportunities[0]?.id ?? "";
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
	{ key: "official_site", label: "春秋元泉官网", logo: "/icon.svg" },
	{ key: "zhihu", label: "知乎", logo: "/brand/zhihu.svg" },
	{ key: "juejin", label: "掘金", logo: "https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/static/favicons/favicon-32x32.png" },
	{ key: "csdn", label: "CSDN", logo: "https://g.csdnimg.cn/static/logo/favicon32.ico" },
	{ key: "51cto", label: "51CTO", logo: "https://blog.51cto.com/favicon.ico" },
	{ key: "wechat", label: "公众号", logo: "/brand/wechat.svg" },
] as const;

const syncablePlatformKeys = new Set(["zhihu", "juejin", "csdn", "51cto", "wechat"]);

function platformDisplayName(platformKey: string) {
	return platformOptions.find((platform) => platform.key === platformKey)?.label || platformKey;
}

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

function agentArtifactLabel(kind: string) {
	if (kind === "official_page_screenshot") return "官网截图";
	if (kind === "invalid_page_screenshot") return "无效截图（未使用）";
	if (kind === "structured_result") return "结构化结果";
	return "Agent 工件";
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

export function PriorityActionsWorkbench({ workspaceId, opportunities, opportunityScope, initialScope, initialSelectedId, actions, agentRuntime, activeSourcedBrandFactCount, websiteUrl, initialOpportunityAnalysis, initialWebsiteGapAnalysis, initialAgentRuns, initialReviewPackages, initialDistributionRuns, initialRetests, createAction, startAgent, interruptAgent, resumeAgent, reviseAgent, captureAgentVisuals, readAgentProgress, decideReview, savePlatformVariant, createDistribution, recordDistributionResults, confirmDraftReadback, recordHumanPublication, createRetest, readRetest, discoverActions, readOpportunityAnalysis, analyzeWebsiteGap, readWebsiteGapAnalysis }: Props) {
	const router = useRouter();
	const [selectedId, setSelectedId] = useState(() => initialSelectedId && opportunities.some((item) => item.id === initialSelectedId)
		? initialSelectedId
		: initialSelectedOpportunityId(opportunities));
	const [selectedBatchId, setSelectedBatchId] = useState(initialScope.batchId);
	const [selectedModel, setSelectedModel] = useState(initialScope.modelKey ?? "all");
	const [selectedQuestion, setSelectedQuestion] = useState(initialScope.questionPlanId ? String(initialScope.questionPlanId) : "all");
	const [discoveryFeedback, setDiscoveryFeedback] = useState("");
	const [opportunityAnalysis, setOpportunityAnalysis] = useState(initialOpportunityAnalysis);
	const [websiteGapAnalysis, setWebsiteGapAnalysis] = useState(initialWebsiteGapAnalysis);
	const [websiteGapFeedback, setWebsiteGapFeedback] = useState("");
	const [expandedOpportunityId, setExpandedOpportunityId] = useState<string | null>(null);
	const [runtimeExpanded, setRuntimeExpanded] = useState(false);
	const [isTimelineCollapsed, setIsTimelineCollapsed] = useState(false);
	const timelineHeaderRef = useRef<HTMLElement>(null);
	const [previewMessage, setPreviewMessage] = useState("");
	const [syncOpen, setSyncOpen] = useState(false);
	const [syncPhase, setSyncPhase] = useState<"idle" | "discovering" | "confirm" | "syncing" | "complete" | "partial" | "error">("idle");
	const [syncAccounts, setSyncAccounts] = useState<ArticleSyncAccount[]>([]);
	const [selectedSyncAccounts, setSelectedSyncAccounts] = useState<string[]>([]);
	const [syncMessage, setSyncMessage] = useState("");
	const [agentRuns, setAgentRuns] = useState(initialAgentRuns);
	const [agentEvents, setAgentEvents] = useState<CleanroomAgentEvent[]>([]);
	const [agentProgress, setAgentProgress] = useState<CleanroomAgentRunProgress | null>(null);
	const [agentDetailsExpanded, setAgentDetailsExpanded] = useState(false);
	const agentLogToggleRef = useRef<HTMLButtonElement>(null);
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
	const [unverifiedClaimIds, setUnverifiedClaimIds] = useState<number[]>([]);
	const [reviewPlatformKeys, setReviewPlatformKeys] = useState<string[]>([]);
	const [viewedPlatformKeys, setViewedPlatformKeys] = useState<string[]>([]);
	const [reviewNote, setReviewNote] = useState("");
	const [reviewFeedback, setReviewFeedback] = useState("");
	const [editingVariantId, setEditingVariantId] = useState<number | null>(null);
	const [variantEdits, setVariantEdits] = useState<Record<number, { title: string; summary: string; body_markdown: string }>>({});
	const [targetPlatforms, setTargetPlatforms] = useState<string[]>(["zhihu", "juejin"]);
	function collapseTimeline() {
		setIsTimelineCollapsed(true);
		window.requestAnimationFrame(() => {
			const header = timelineHeaderRef.current;
			const toggle = header?.querySelector("button");
			if (toggle instanceof HTMLButtonElement) toggle.focus({ preventScroll: true });
			header?.scrollIntoView({
				behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
				block: "center",
			});
		});
	}
	function collapseAgentLog() {
		setAgentDetailsExpanded(false);
		window.requestAnimationFrame(() => {
			const toggle = agentLogToggleRef.current;
			toggle?.focus({ preventScroll: true });
			toggle?.scrollIntoView({
				behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
				block: "center",
			});
		});
	}
	function collapseOpportunityDetails(itemId: string) {
		setExpandedOpportunityId(null);
		window.requestAnimationFrame(() => {
			const card = document.getElementById(`opportunity-card-${itemId}`);
			card?.focus({ preventScroll: true });
			card?.scrollIntoView({
				behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
				block: "center",
			});
		});
	}
	const [isSaving, startSaving] = useTransition();
	const [isVariantSaving, startVariantSaving] = useTransition();
	const [isScopePending, startScopeTransition] = useTransition();
	const [isWebsiteGapPending, startWebsiteGapTransition] = useTransition();
	const reviewDialogRef = useRef<HTMLElement | null>(null);
	const syncDialogRef = useRef<HTMLElement | null>(null);

	const selectedBatch = opportunityScope.batches.find((batch) => batch.id === selectedBatchId);
	const models = opportunityScope.models.filter((model) => selectedBatch?.model_keys.includes(model.key));
	const questions = opportunityScope.questions.filter((question) => selectedBatch?.question_plan_ids.includes(question.id));
	const selectedModelLabel = selectedModel === "all"
		? "全部模型"
		: models.find((model) => model.key === selectedModel)?.label ?? selectedModel;
	const selectedQuestionLabel = selectedQuestion === "all"
		? "全部问题"
		: questions.find((question) => String(question.id) === selectedQuestion)?.label ?? `问题 #${selectedQuestion}`;
	// The server has already applied the exact batch/model/question scope. Do not
	// compare model keys with user-facing model labels a second time in the client.
	const filtered = opportunities;
	const opportunityAnalysisActive = Boolean(opportunityAnalysis && ["queued", "running"].includes(opportunityAnalysis.status));
	const websiteGapAnalysisActive = Boolean(websiteGapAnalysis && ["queued", "running"].includes(websiteGapAnalysis.status));
	useEffect(() => { if (!filtered.some((item) => item.id === selectedId)) setSelectedId(filtered[0]?.id ?? ""); }, [filtered, selectedId]);
	const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
	const unresolved = filtered.filter((item) => !item.existingAction || !["verified", "closed"].includes(item.existingAction.status));
	const unselected = unresolved.filter((item) => !item.existingAction).length;
	const inProgress = unresolved.filter((item) => item.existingAction).length;
	const high = unresolved.filter((item) => item.priority === "high").length;
	const pendingDraftPackages = agentRuns
		.filter((run) => run.status === "awaiting_review")
		.map((run) => reviewPackages.find((item) => item.asset.id === Number(run.result_snapshot.asset_id)))
		.filter((reviewPackage): reviewPackage is CleanroomContentReviewPackage => Boolean(reviewPackage && !reviewPackage.approved_platform_keys.length));
	const regenerationDraftCount = pendingDraftPackages.filter((reviewPackage) => (
		reviewPackage.asset.status === "changes_requested"
		|| (reviewPackage.requires_sourced_brand_facts && reviewPackage.sourced_brand_fact_count === 0)
		|| (
			reviewPackage.available_sourced_brand_fact_count > 0
			&& reviewPackage.sourced_brand_fact_count === 0
		)
	)).length;
	const reviewReadyDraftCount = pendingDraftPackages.length - regenerationDraftCount;
	const retestReady = retests.filter((item) => item.status === "completed").length;
	const stage = actionStage(selected?.existingAction);
	const syncAction = selected?.existingAction ?? actions[0];
	const currentRun = useMemo(() => agentRuns
		.filter((run) => run.action_id === selected?.existingAction?.id)
		.sort((a, b) => b.id - a.id)[0], [agentRuns, selected?.existingAction?.id]);
	const activeAgentRunCount = agentRuns.filter((run) => ["queued", "resuming", "running", "cancelling"].includes(run.status)).length;
	const agentCapacityLimit = Math.max(1, agentRuntime?.max_concurrent_runs ?? 1);
	const agentCapacityUsed = Math.max(agentRuntime?.active_run_count ?? 0, activeAgentRunCount + (opportunityAnalysisActive ? 1 : 0) + (websiteGapAnalysisActive ? 1 : 0));
	const agentCapacityAvailable = agentCapacityUsed < agentCapacityLimit;
	const agentCanStart = Boolean(agentRuntime?.ready && agentCapacityAvailable);
	const websiteRecommendations = websiteGapAnalysis?.recommendations ?? [];
	const websiteAnalysisState = isScopePending
		? "switching"
		: isWebsiteGapPending
			? "submitting"
			: websiteGapAnalysisActive
				? "running"
				: websiteGapAnalysis?.status === "failed"
					? "failed"
					: websiteGapAnalysis?.status === "succeeded"
						? websiteGapAnalysis.result_count > 0 ? "success" : "empty"
						: !selectedBatchId
							? "missing-batch"
							: !websiteUrl
								? "missing-website"
								: !agentRuntime?.ready
									? "not-ready"
									: !agentCapacityAvailable
										? "busy"
										: "idle";
	const websiteCitationCount = Number(websiteGapAnalysis?.official_metrics.official_cited_answer_count || 0);
	const websiteEligibleCount = Number(websiteGapAnalysis?.official_metrics.eligible_answer_count || 0);
	const agentTimeoutMinutes = Math.max(1, Math.round((agentRuntime?.run_timeout_seconds ?? 900) / 60));
	const runActive = Boolean(currentRun && ["queued", "resuming", "running", "cancelling"].includes(currentRun.status));
	const currentRunId = currentRun?.id;
	const currentRunStatus = currentRun?.status;
	const currentAssetId = Number(currentRun?.result_snapshot.asset_id) || null;
	const currentReviewPackage = reviewPackages.find((item) => item.asset.id === currentAssetId);
	const reviewVisuals = reviewVisualAssets(currentReviewPackage?.variants ?? []);
	const websiteGenerationReady = !selected?.requiresSourcedBrandFacts || activeSourcedBrandFactCount > 0;
	const websiteDraftReadyForApproval = !currentReviewPackage?.requires_sourced_brand_facts
		|| currentReviewPackage.sourced_brand_fact_count > 0;
	const brandFactVerificationRequired = Boolean(
		currentReviewPackage?.requires_sourced_brand_facts
		&& currentReviewPackage.sourced_brand_fact_count === 0
		&& currentReviewPackage.unverified_brand_fact_count > 0,
	);
	const draftUsesUnverifiedBrandFacts = Boolean(
		brandFactVerificationRequired
		&& currentReviewPackage
		&& currentReviewPackage.used_unverified_brand_fact_count > 0,
	);
	const draftMissesAvailableBrandFacts = Boolean(
		currentReviewPackage
		&& currentReviewPackage.available_sourced_brand_fact_count > 0
		&& currentReviewPackage.sourced_brand_fact_count === 0,
	);
	const reviewNeedsRevision = currentReviewPackage?.asset.status === "changes_requested";
	const approvedPlatformKeys = currentReviewPackage?.approved_platform_keys ?? [];
	const syncableApprovedPlatformKeys = approvedPlatformKeys.filter((key) => syncablePlatformKeys.has(key));
	const hasApprovedOfficialSiteDraft = approvedPlatformKeys.includes("official_site");
	const resolvedClaimStatuses = ["source_linked", "verified", "human_confirmed", "explicitly_unverified"];
	const pendingClaims = currentReviewPackage?.claims.filter((claim) => !resolvedClaimStatuses.includes(claim.verification_status)) ?? [];
	const confirmedPendingClaimCount = pendingClaims.filter((claim) => confirmedClaimIds.includes(claim.id)).length;
	const unverifiedPendingClaimCount = pendingClaims.filter((claim) => unverifiedClaimIds.includes(claim.id)).length;
	const reviewedPendingClaimCount = confirmedPendingClaimCount + unverifiedPendingClaimCount;
	const remainingPendingClaimCount = Math.max(0, pendingClaims.length - reviewedPendingClaimCount);
	const selectedUnviewedPlatformCount = reviewPlatformKeys.filter((key) => !viewedPlatformKeys.includes(key)).length;
	const currentDistribution = currentAssetId ? distributionRuns
		.filter((run) => run.action_id === selected?.existingAction?.id && run.content_asset_id === currentAssetId)
		.sort((a, b) => b.id - a.id)[0] : undefined;
	const websiteHandoffTarget = currentDistribution && currentDistribution.content_asset_id === currentReviewPackage?.asset.id
		? currentDistribution.targets.find((target) => target.platform_key === "official_site" && target.adapter_version === "manual-website.v1")
		: undefined;
	const websiteHandoffReady = Boolean(
		websiteHandoffTarget
		&& websiteHandoffTarget.request_status === "handoff_ready"
		&& websiteHandoffTarget.draft_readback_status === "not_required",
	);
	const savedDraftCount = currentDistribution?.targets.filter((target) => target.draft_readback_status === "draft_saved").length ?? 0;
	const pendingDraftReadbackTargets = currentDistribution?.targets.filter((target) => (
		target.draft_readback_status === "awaiting_human_confirmation"
		&& Boolean(target.candidate_draft_url)
	)) ?? [];
	const pendingDraftReadbackCount = pendingDraftReadbackTargets.length;
	const allDraftsSaved = Boolean(currentDistribution?.targets.length && savedDraftCount === currentDistribution.targets.length);
	const platformKeysNeedingSync = syncableApprovedPlatformKeys.filter((platformKey) => {
		const target = currentDistribution?.targets.find((item) => item.platform_key === platformKey);
		return !target || !["draft_saved", "awaiting_human_confirmation"].includes(target.draft_readback_status);
	});
	const deliveryComplete = selected?.type === "website" ? websiteHandoffReady : allDraftsSaved;
	const publicationReady = selected?.type === "website" ? websiteHandoffReady : allDraftsSaved;
	const publishedTargetCount = currentDistribution?.targets.filter((target) => target.human_publish_status === "published" && target.public_url && target.publication_verification_status === "publicly_verified").length ?? 0;
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
	const syncConnectionReady = ["confirm", "syncing", "complete", "partial"].includes(syncPhase) || (syncPhase === "error" && syncAccounts.length > 0);
	const syncSelectionReady = ["syncing", "complete", "partial"].includes(syncPhase) || (syncPhase === "error" && selectedSyncAccounts.length > 0);
	const syncMatchedPlatformCount = new Set(syncAccounts.map(articleSyncPlatformKey).filter(Boolean)).size;
	const syncSavedTargetCount = currentDistribution?.targets.filter((target) => target.draft_readback_status === "draft_saved").length ?? 0;
	const syncAwaitingConfirmationCount = currentDistribution?.targets.filter((target) => target.draft_readback_status === "awaiting_human_confirmation").length ?? 0;
	const syncFailedTargetCount = currentDistribution?.targets.filter((target) => target.draft_readback_status === "failed").length ?? 0;
	const syncPendingTargetCount = currentDistribution?.targets.filter((target) => !["draft_saved", "awaiting_human_confirmation", "failed"].includes(target.draft_readback_status)).length ?? 0;
	const syncProgressSteps = [
		{
			label: "连接助手",
			hint: syncConnectionReady ? `${syncMatchedPlatformCount} 个平台 · ${syncAccounts.length} 个匹配账号` : "检查扩展与登录状态",
			state: syncConnectionReady ? "done" : syncPhase === "discovering" ? "current" : syncPhase === "error" ? "issue" : "waiting",
		},
		{
			label: "确认平台",
			hint: syncPhase === "confirm" ? `已选择 ${selectedSyncAccounts.length}/${syncAccounts.length}` : syncSelectionReady ? `${selectedSyncAccounts.length} 个平台已确认` : "由你决定写入范围",
			state: syncSelectionReady ? "done" : syncPhase === "confirm" ? "current" : "waiting",
		},
		{
			label: "写入并回读",
			hint: syncPhase === "complete"
				? "所有草稿已由你打开确认"
				: syncPhase === "partial"
					? `${syncAwaitingConfirmationCount} 个待打开确认 · ${syncSavedTargetCount} 个已确认 · ${syncPendingTargetCount} 个待写入 · ${syncFailedTargetCount} 个失败`
					: "返回链接后仍需打开确认",
			state: syncPhase === "complete"
				? "done"
				: syncPhase === "syncing" || syncAwaitingConfirmationCount > 0
					? "current"
					: ["partial", "error"].includes(syncPhase) && selectedSyncAccounts.length > 0
						? "issue"
						: "waiting",
		},
	] as const;
	const visibleAgentProgress = agentProgress?.run.id === currentRunId ? agentProgress : null;
	const hasCapturedVisual = visibleAgentProgress?.artifacts.some((artifact) => artifact.artifact_kind === "official_page_screenshot") ?? false;
	const groupedAgentEvents = useMemo(() => groupAgentEvents(visibleAgentProgress?.events ?? []), [visibleAgentProgress?.events]);
	const agentTransportLabel = agentTransport === "live"
		? "实时事件已连接"
		: agentTransport === "fallback"
			? "实时连接中断，正在回读数据库"
			: agentTransport === "connecting"
				? "正在连接实时事件"
				: visibleAgentProgress
					? visibleAgentProgress.attempt_number > 1
						? `本轮 ${visibleAgentProgress.attempt_event_count} 条 · 累计 ${visibleAgentProgress.event_count} 条事件`
						: `${visibleAgentProgress.event_count} 条持久化事件`
					: "正在读取持久化进度";
	const availableTargetPlatforms = selected?.type === "website"
		? platformOptions.filter((platform) => platform.key === "official_site")
		: platformOptions.filter((platform) => platform.key !== "official_site");

	useEffect(() => {
		setSelectedBatchId(initialScope.batchId);
		setSelectedModel(initialScope.modelKey ?? "all");
		setSelectedQuestion(initialScope.questionPlanId ? String(initialScope.questionPlanId) : "all");
	}, [initialScope.batchId, initialScope.modelKey, initialScope.questionPlanId]);
	useEffect(() => setOpportunityAnalysis(initialOpportunityAnalysis), [initialOpportunityAnalysis]);
	useEffect(() => setWebsiteGapAnalysis(initialWebsiteGapAnalysis), [initialWebsiteGapAnalysis]);
	useEffect(() => {
		if (!opportunityAnalysisActive || !opportunityAnalysis) return;
		let cancelled = false;
		async function refreshAnalysis() {
			try {
				const result = await readOpportunityAnalysis(opportunityAnalysis!.job_id);
				if (cancelled) return;
				setOpportunityAnalysis(result);
				if (result.status === "succeeded") {
					setDiscoveryFeedback(result.result_count > 0
						? `Codex 已完成判断，找到 ${result.result_count} 个优先机会。`
						: "Codex 已完成判断，当前证据不足以形成优先机会。");
					router.refresh();
				} else if (result.status === "failed") {
					setDiscoveryFeedback(result.error_message || "Codex 未完成机会判断，没有产生新机会。");
				}
			} catch (error) {
				if (!cancelled) setDiscoveryFeedback(error instanceof Error ? error.message : "无法读取 Codex 判断进度");
			}
		}
		void refreshAnalysis();
		const timer = window.setInterval(refreshAnalysis, 1800);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
		};
	}, [opportunityAnalysis?.job_id, opportunityAnalysisActive, readOpportunityAnalysis, router]);
	useEffect(() => {
		if (!websiteGapAnalysisActive || !websiteGapAnalysis) return;
		let cancelled = false;
		async function refreshAnalysis() {
			try {
				const result = await readWebsiteGapAnalysis(websiteGapAnalysis!.job_id);
				if (cancelled) return;
				setWebsiteGapAnalysis(result);
				if (result.status === "succeeded") {
					setWebsiteGapFeedback(result.result_count > 0
						? `Codex 已根据当前范围形成 ${result.recommendation_count} 项官网诊断建议。`
						: "Codex 已完成分析，当前范围未发现需补齐的官网差距。");
					router.refresh();
				} else if (result.status === "failed") {
					setWebsiteGapFeedback(result.error_message || "Codex 官网差距分析失败，没有产生建议。");
				}
			} catch (error) {
				if (!cancelled) setWebsiteGapFeedback(error instanceof Error ? error.message : "无法读取官网分析进度");
			}
		}
		void refreshAnalysis();
		const timer = window.setInterval(refreshAnalysis, 1800);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
		};
	}, [websiteGapAnalysis?.job_id, websiteGapAnalysisActive, readWebsiteGapAnalysis, router]);

	useEffect(() => setReviewPackages(initialReviewPackages), [initialReviewPackages]);
	useEffect(() => setDistributionRuns(initialDistributionRuns), [initialDistributionRuns]);
	useEffect(() => setRetests(initialRetests), [initialRetests]);
	useEffect(() => {
		if (!selected) return;
		const recommended = selected.recommendedPlatforms.filter((key) => (
			key !== "official_site" && platformOptions.some((platform) => platform.key === key)
		));
		setTargetPlatforms(selected.type === "website"
			? ["official_site"]
			: (recommended.length ? recommended.slice(0, 2) : ["zhihu", "juejin"]));
	}, [selected?.id, selected?.type]);
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
		if (!reviewOpen && !syncOpen) return;
		const dialog = reviewOpen ? reviewDialogRef.current : syncDialogRef.current;
		const returnTarget = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		const focusFrame = window.requestAnimationFrame(() => {
			const closeButton = dialog?.querySelector<HTMLElement>('button[aria-label^="关闭"]');
			(closeButton ?? dialog)?.focus();
		});
		function keepFocusInside(event: KeyboardEvent) {
			if (event.key !== "Tab" || !dialog) return;
			const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
				'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
			)).filter((element) => element.getClientRects().length > 0);
			if (!focusable.length) {
				event.preventDefault();
				dialog.focus();
				return;
			}
			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			if (event.shiftKey && document.activeElement === first) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && document.activeElement === last) {
				event.preventDefault();
				first.focus();
			}
		}
		document.addEventListener("keydown", keepFocusInside);
		return () => {
			window.cancelAnimationFrame(focusFrame);
			document.removeEventListener("keydown", keepFocusInside);
			if (returnTarget?.isConnected) returnTarget.focus();
		};
	}, [reviewOpen, syncOpen]);

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
		setWebsiteGapFeedback("");
		setWebsiteGapAnalysis(null);
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
				const run = await discoverActions({
					batchId: selectedBatchId,
					modelKey: selectedModel === "all" ? null : selectedModel,
					questionPlanId: selectedQuestion === "all" ? null : Number(selectedQuestion),
				});
				setOpportunityAnalysis(run);
				setDiscoveryFeedback(`Codex 已接收批次 #${run.batch_id} 的 ${run.evidence_count} 条真实证据，完成前不会显示新机会。`);
			} catch (error) {
				setDiscoveryFeedback(error instanceof Error ? error.message : "无法启动 Codex 机会判断");
			}
		});
	}

	function startWebsiteGapAnalysis() {
		setWebsiteGapFeedback("");
		startWebsiteGapTransition(async () => {
			try {
				const run = await analyzeWebsiteGap({
					batchId: selectedBatchId,
					modelKey: selectedModel === "all" ? null : selectedModel,
					questionPlanId: selectedQuestion === "all" ? null : Number(selectedQuestion),
				});
				setWebsiteGapAnalysis(run);
				setWebsiteGapFeedback(`Codex 已接收当前范围的 ${run.evidence_count} 条真实证据；完成前不会显示诊断结论。`);
			} catch (error) {
				setWebsiteGapFeedback(error instanceof Error ? error.message : "无法启动 Codex 官网差距分析");
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

	function requestVisualCapture() {
		if (!currentRun) return;
		setAgentFeedback("");
		startSaving(async () => {
			try {
				const progress = await captureAgentVisuals(currentRun.id);
				setAgentProgress(progress);
				setAgentEvents(progress.events);
				setAgentRuns((current) => current.map((item) => item.id === progress.run.id ? progress.run : item));
				setAgentFeedback("官网截图已归档，可在内容库查看原图与来源。");
				router.refresh();
			} catch (error) {
				setAgentFeedback(error instanceof Error ? error.message : "官网素材采集失败");
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
		setUnverifiedClaimIds([]);
		setReviewPlatformKeys([]);
		setViewedPlatformKeys(currentReviewPackage.approved_platform_keys);
		setReviewNote("");
		setReviewFeedback("");
		setEditingVariantId(null);
		setVariantEdits({});
		setReviewOpen(true);
	}

	function openPlatformReview(platformKey: string) {
		setReviewTab(platformKey);
		setViewedPlatformKeys((current) => [...new Set([...current, platformKey])]);
	}

	function beginVariantEdit(variant: CleanroomPlatformVariant) {
		setEditingVariantId(variant.id);
		setVariantEdits((current) => ({
			...current,
			[variant.id]: current[variant.id] ?? {
				title: variant.title,
				summary: variant.summary,
				body_markdown: variant.body_markdown,
			},
		}));
		setReviewFeedback("");
	}

	function updateVariantEdit(variantId: number, field: "title" | "summary" | "body_markdown", value: string) {
		setVariantEdits((current) => ({
			...current,
			[variantId]: { ...current[variantId], [field]: value },
		}));
	}

	function persistVariantEdit(variant: CleanroomPlatformVariant) {
		const draft = variantEdits[variant.id];
		if (!draft || !draft.title.trim() || !draft.summary.trim() || !draft.body_markdown.trim()) {
			setReviewFeedback("标题、摘要和正文都不能为空。");
			return;
		}
		startVariantSaving(async () => {
			try {
				const saved = await savePlatformVariant(variant.id, {
					...draft,
					tags: variant.tags,
					category: variant.category,
				});
				setReviewPackages((current) => current.map((reviewPackage) => reviewPackage.asset.id === saved.content_asset_id
					? { ...reviewPackage, variants: reviewPackage.variants.map((item) => item.id === saved.id ? saved : item) }
					: reviewPackage));
				setEditingVariantId(null);
				setReviewFeedback(`${platformOptions.find((item) => item.key === saved.platform_key)?.label || saved.platform_key} 稿已保存，新内容将用于人工审核和后续写入。`);
			} catch (error) {
				setReviewFeedback(error instanceof Error ? error.message : "平台稿保存失败。");
			}
		});
	}

	function submitReview(verdict: "approved" | "changes_requested") {
		if (!currentReviewPackage) return;
		setReviewFeedback("");
		startSaving(async () => {
			try {
				const result = await decideReview(currentReviewPackage.asset.id, {
					verdict,
					confirmed_claim_ids: confirmedClaimIds,
					unverified_claim_ids: unverifiedClaimIds,
					platform_keys: reviewPlatformKeys,
					reviewed_platform_keys: viewedPlatformKeys,
					note: reviewNote || null,
				});
				setReviewPackages((current) => [result, ...current.filter((item) => item.asset.id !== result.asset.id)]);
				setReviewFeedback(verdict === "approved"
					? result.approved_platform_keys.some((key) => syncablePlatformKeys.has(key))
						? "审核已记录，已通过的外部平台稿可以交给文章同步助手。"
						: "官网稿审核已记录；请交给网站负责人部署，系统不会把审核当作已上线。"
					: "修改要求已记录，本版本不会进入同步。");
				router.refresh();
			} catch (error) {
				setReviewFeedback(error instanceof Error ? error.message : "无法保存审核结果");
			}
		});
	}

	function setClaimReviewDecision(claimId: number, decision: "confirmed" | "unverified") {
		setConfirmedClaimIds((current) => decision === "confirmed"
			? [...new Set([...current, claimId])]
			: current.filter((id) => id !== claimId));
		setUnverifiedClaimIds((current) => decision === "unverified"
			? [...new Set([...current, claimId])]
			: current.filter((id) => id !== claimId));
	}

	function updateSyncAccount(next: ArticleSyncAccount) {
		const key = articleSyncAccountKey(next);
		setSyncAccounts((current) => current.map((account) => articleSyncAccountKey(account) === key ? { ...account, ...next } : account));
	}

	function toggleSyncAccount(account: ArticleSyncAccount) {
		const key = articleSyncAccountKey(account);
		const platformKey = articleSyncPlatformKey(account);
		setSelectedSyncAccounts((current) => {
			if (current.includes(key)) return current.filter((value) => value !== key);
			const withoutSamePlatform = current.filter((value) => {
				const selectedAccount = syncAccounts.find((item) => articleSyncAccountKey(item) === value);
				return !platformKey || !selectedAccount || articleSyncPlatformKey(selectedAccount) !== platformKey;
			});
			return [...withoutSamePlatform, key];
		});
	}

	async function openSyncAssistant() {
		if (!syncAction || !currentReviewPackage || !syncableApprovedPlatformKeys.length) {
			setPreviewMessage("请先完成人工审核，至少通过一个平台稿。");
			return;
		}
		if (allDraftsSaved) {
			setPreviewMessage("已审核平台稿均已打开并确认可见，无需重复写入。");
			return;
		}
		if (!platformKeysNeedingSync.length && pendingDraftReadbackCount) {
			setPreviewMessage(`同步助手已返回 ${pendingDraftReadbackCount} 个草稿地址。请在「写入平台草稿」中逐个打开，确认正文可见后再继续。`);
			return;
		}
		setSyncOpen(true);
		setSyncPhase("discovering");
		setSyncMessage("正在通过文章同步助手检查已登录平台…");
		setSyncAccounts([]);
		setSelectedSyncAccounts([]);
		const api = getArticleSyncPageApi();
		if (!api) {
			setSyncPhase("error");
			setSyncMessage("当前网页没有检测到文章同步助手。请在 EgoLite 中启用扩展并刷新本页。");
			return;
		}
		try {
			const accounts = await discoverArticleSyncAccounts(api);
			const platformAccounts = accounts.filter((account) => {
				const platformKey = articleSyncPlatformKey(account);
				return platformKey !== null && platformKeysNeedingSync.includes(platformKey);
			});
			setSyncAccounts(platformAccounts);
			if (!platformAccounts.length) {
				setSyncPhase("error");
				const pendingLabels = [...platformKeysNeedingSync]
					.map((key) => platformOptions.find((platform) => platform.key === key)?.label || key)
					.join("、");
				setSyncMessage(`没有检测到与已审核稿匹配的登录平台。请先在 EgoLite 中登录对应账号（${pendingLabels}）。`);
				return;
			}
			setSyncPhase("confirm");
			const preservedCount = syncableApprovedPlatformKeys.length - platformKeysNeedingSync.length;
			const matchedPlatformCount = new Set(platformAccounts.map(articleSyncPlatformKey).filter(Boolean)).size;
			setSyncMessage(matchedPlatformCount === 1
				? preservedCount ? `已有 ${preservedCount} 个平台无需重复写入（已确认或等待打开确认），本次只处理剩余平台。` : "当前只检测到 1 个已登录平台；如需双平台，请先在 EgoLite 中登录另一个平台。"
				: `已检测到 ${matchedPlatformCount} 个待写入平台、${platformAccounts.length} 个可用账号。选择目标后由你确认，系统不会自动发布。`);
		} catch (error) {
			setSyncPhase("error");
			setSyncMessage(error instanceof Error ? error.message : "文章同步助手连接失败。");
		}
	}

	async function confirmSync() {
		const api = getArticleSyncPageApi();
		const accounts = syncAccounts.filter((account) => selectedSyncAccounts.includes(articleSyncAccountKey(account)));
		if (!api || !syncAction || !currentReviewPackage || accounts.length === 0) return;
		const accountVariants = accounts.flatMap((account) => {
			const platformKey = articleSyncPlatformKey(account);
			const variant = currentReviewPackage.variants.find((item) => item.platform_key === platformKey && approvedPlatformKeys.includes(item.platform_key));
			return platformKey && variant ? [{ account, platformKey, variant }] : [];
		});
		if (!accountVariants.length) return;
		const draftWindows = new Map<string, Window | null>();
		for (const { platformKey } of accountVariants) {
			const draftWindow = window.open("about:blank", `geo-platform-draft-${platformKey}`);
			if (draftWindow) draftWindow.opener = null;
			draftWindows.set(platformKey, draftWindow);
		}
		setSyncPhase("syncing");
		try {
			const distributionTargetPlatformKeys = syncableApprovedPlatformKeys;
			const canReuseCurrent = currentDistribution?.content_asset_id === currentReviewPackage.asset.id
				&& distributionTargetPlatformKeys.every((platformKey) => currentDistribution.targets.some((target) => target.platform_key === platformKey));
			const distribution = canReuseCurrent
				? currentDistribution
				: await createDistribution(currentReviewPackage.asset.id, distributionTargetPlatformKeys);
			setDistributionRuns((current) => [distribution, ...current.filter((item) => item.id !== distribution.id)]);
			let persisted = distribution;
			for (const [index, { account, platformKey, variant }] of accountVariants.entries()) {
				const platformLabel = platformOptions.find((item) => item.key === platformKey)?.label || platformKey;
				setSyncMessage(`正在写入 ${platformLabel}（${index + 1}/${accountVariants.length}）；前一平台完成并回读后才继续…`);
				const result = await syncVariant(api, account, variant, updateSyncAccount);
				const draftWindow = draftWindows.get(platformKey);
				if (result.status === "done" && result.editResp?.draftLink) {
					if (draftWindow && !draftWindow.closed) draftWindow.location.replace(result.editResp.draftLink);
				} else if (draftWindow && !draftWindow.closed) draftWindow.close();
				draftWindows.delete(platformKey);
				persisted = await recordDistributionResults(distribution.id, [{
					platform_key: platformKey,
					request_status: result.status === "done" && result.editResp?.draftLink ? "draft_link_returned" as const : "failed" as const,
					draft_url: result.editResp?.draftLink || null,
					message: result.error || result.msg || null,
				}]);
				setDistributionRuns((current) => [persisted, ...current.filter((item) => item.id !== persisted.id)]);
				// The official bridge keeps one global currentSyncId. Yield after its
				// terminal result so SYNC_COMPLETE can release that slot before the
				// next platform-specific draft starts.
				if (index < accountVariants.length - 1) await new Promise<void>((resolve) => window.setTimeout(resolve, 200));
			}
			const saved = persisted.targets.filter((target) => target.draft_readback_status === "draft_saved").length;
			const awaitingConfirmation = persisted.targets.filter((target) => target.draft_readback_status === "awaiting_human_confirmation").length;
			const failed = persisted.targets.filter((target) => target.draft_readback_status === "failed").length;
			const pending = persisted.targets.length - saved - awaitingConfirmation - failed;
			if (saved === persisted.targets.length) {
				setSyncPhase("complete");
				setSyncMessage(`${saved} 个平台草稿均已打开并由你确认可见；最终发布仍由你确认。`);
			} else if (awaitingConfirmation > 0 || saved > 0 || failed > 0) {
				setSyncPhase("partial");
				const remaining = [
					awaitingConfirmation ? `${awaitingConfirmation} 个草稿地址等待你打开确认` : "",
					pending ? `${pending} 个平台等待登录或写入` : "",
					failed ? `${failed} 个平台写入失败` : "",
				].filter(Boolean).join("，");
				setSyncMessage(`${saved} 个平台草稿已确认，${remaining}。草稿链接本身不等于草稿已保存。`);
			} else {
				setSyncPhase("error");
				setSyncMessage("没有平台返回可核验的草稿链接，本次不计为已保存。请检查登录状态后重试。");
			}
			router.refresh();
		} catch (error) {
			for (const draftWindow of draftWindows.values()) {
				if (draftWindow && !draftWindow.closed) draftWindow.close();
			}
			setSyncPhase("error");
			setSyncMessage(error instanceof Error ? error.message : "文章同步助手写入失败。");
		}
	}

	function confirmDraftTarget(targetId: number) {
		if (!currentDistribution) return;
		const target = currentDistribution.targets.find((item) => item.id === targetId);
		const platformLabel = platformOptions.find((item) => item.key === target?.platform_key)?.label || target?.platform_key || "平台";
		startSaving(async () => {
			try {
				const result = await confirmDraftReadback(currentDistribution.id, targetId);
				setDistributionRuns((current) => [result, ...current.filter((item) => item.id !== result.id)]);
				const saved = result.targets.filter((item) => item.draft_readback_status === "draft_saved").length;
				const awaiting = result.targets.filter((item) => item.draft_readback_status === "awaiting_human_confirmation").length;
				const complete = saved === result.targets.length;
				setSyncPhase(complete ? "complete" : "partial");
				setSyncMessage(complete
					? `${saved} 个平台草稿均已由你打开确认，现在可以进入人工发布。`
					: `${platformLabel} 草稿已确认可见；还有 ${awaiting} 个草稿等待确认。`);
				setPreviewMessage(`${platformLabel} 草稿已人工确认可见。`);
				router.refresh();
			} catch (error) {
				setPreviewMessage(error instanceof Error ? error.message : "草稿回读确认失败。");
			}
		});
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
				const verified = result.targets.filter((item) => item.publication_verification_status === "publicly_verified").length;
				setPublicationMessage(`${verified}/${result.targets.length} 个公开页面已通过公网校验。系统没有代替你点击发布。`);
				router.refresh();
			} catch (error) {
				setPublicationMessage(error instanceof Error ? error.message : "无法保存发布结果");
			}
		});
	}

	function beginWebsiteHandoff() {
		if (!currentReviewPackage || !hasApprovedOfficialSiteDraft || websiteHandoffReady) return;
		setPublicationMessage("");
		startSaving(async () => {
			try {
				const result = await createDistribution(currentReviewPackage.asset.id, ["official_site"]);
				setDistributionRuns((current) => [result, ...current.filter((item) => item.id !== result.id)]);
				setPublicationMessage("官网交付记录已建立。部署完成前不会计为已上线；请由网站负责人上线后回填公开 URL。");
				router.refresh();
			} catch (error) {
				setPublicationMessage(error instanceof Error ? error.message : "无法建立官网交付记录");
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
				<div><h1>优先行动</h1><span>Codex 生成平台稿 → 你修改并审核 → 写入草稿 → 人工发布。</span>
					<div className="pa-runtime-wrap">
						<button type="button" className={`pa-runtime-status${!agentRuntime?.ready ? " is-warning" : agentCapacityAvailable ? " is-ready" : " is-busy"}`} onClick={() => setRuntimeExpanded((value) => !value)} aria-expanded={runtimeExpanded}>
							<i />{!agentRuntime?.ready ? "Codex 需要处理" : agentCapacityAvailable ? agentRuntime.connection_status === "warm" ? "Codex 常驻已连接" : "Codex 已就绪" : `Codex 正在执行 ${agentCapacityUsed}/${agentCapacityLimit}`}<Icon name="chevron" />
						</button>
						{runtimeExpanded ? <div className="pa-runtime-popover" role="status"><b>{!agentRuntime?.ready ? "本机 Agent 当前不可启动" : agentCapacityAvailable ? agentRuntime.connection_status === "warm" ? "常驻进程正在复用" : "首次任务时建立常驻连接" : "本机 Agent 正在处理其他任务"}</b><span>{agentRuntime?.default_model || "未检测到默认模型"}</span><small>{agentRuntime?.ready ? `当前进程已复用 ${agentRuntime.reuse_count ?? 0} 次 · 运行容量 ${agentCapacityUsed}/${agentCapacityLimit} · 单次最长 ${agentTimeoutMinutes} 分钟 · ${runtimeVersionLabel(agentRuntime.runtime_version)}` : agentRuntime?.error || "请在设置中完成登录或自检。"}</small><Link href={`/geo/${workspaceId}/settings`}>查看 Agent 设置</Link></div> : null}
					</div>
				</div>
			</header>

			<section className="pa-summary" aria-label="行动状态摘要">
				<article><span className="pa-summary-icon is-warning"><Icon name="warning" /></span><div><small>未闭环机会</small><strong>{isScopePending ? "—" : unresolved.length}</strong></div></article>
				<article><span className="pa-summary-icon is-trend"><Icon name="trend" /></span><div><small>其中高优先级</small><strong>{isScopePending ? "—" : high}</strong></div></article>
				<article><span className="pa-summary-icon is-draft"><Icon name="draft" /></span><div><small>待处理稿件</small><strong>{pendingDraftPackages.length}</strong><em>待审 {reviewReadyDraftCount} · 重生成 {regenerationDraftCount}</em></div></article>
				<article><span className="pa-summary-icon is-check"><Icon name="check" /></span><div><small>复测已完成</small><strong>{retestReady}</strong></div></article>
			</section>

			<div className="pa-top-controls">
				<div className="pa-filters" aria-label="筛选行动机会">
					<label><Icon name="calendar" /><select aria-label="观测批次" value={selectedBatchId ?? ""} disabled={isScopePending || !opportunityScope.batches.length} onChange={(event) => changeScope({ batchId: Number(event.target.value) || null })}><option value="">暂无可用批次</option>{opportunityScope.batches.map((batch) => <option key={batch.id} value={batch.id}>批次 #{batch.id} · {batch.eligible_evidence_count} 条有效证据</option>)}</select><Icon name="chevron" /></label>
					<label><Icon name="filter" /><select aria-label="模型范围" value={selectedModel} disabled={isScopePending || !selectedBatch} onChange={(event) => changeScope({ modelKey: event.target.value })}><option value="all">全部模型</option>{models.map((model) => <option key={model.key} value={model.key}>{model.label}</option>)}</select><Icon name="chevron" /></label>
					<label><Icon name="spark" /><select aria-label="问题范围" value={selectedQuestion} disabled={isScopePending || !selectedBatch} onChange={(event) => changeScope({ questionPlanId: event.target.value === "all" ? null : Number(event.target.value) })}><option value="all">全部问题</option>{questions.map((question) => <option key={question.id} value={question.id}>{question.label}</option>)}</select><Icon name="chevron" /></label>
				</div>
				<div className="pa-discovery-row"><button type="button" onClick={refreshOpportunities} disabled={isSaving || isScopePending || opportunityAnalysisActive || !selectedBatchId || !agentRuntime?.ready}>{isSaving ? "正在提交…" : opportunityAnalysisActive ? opportunityAnalysis?.status === "queued" ? "Codex 等待执行…" : "Codex 正在判断…" : "让 Codex 分析当前批次"}</button><span>{isScopePending ? "正在切换范围，不显示旧结果…" : discoveryFeedback || (opportunityAnalysis?.status === "succeeded" ? `Codex Run #${opportunityAnalysis.job_id} 已分析批次 #${opportunityAnalysis.batch_id}` : selectedBatch ? `选定批次 #${selectedBatch.id}；点击后 Codex 才会发现机会` : "需要先完成一次真实联网观测")}</span></div>
			</div>
		</section>

		<section className={`pa-website-analysis is-${websiteAnalysisState}`} aria-labelledby="website-analysis-title" aria-live="polite">
			<div className="pa-website-analysis-inner">
				<span className="pa-website-analysis-icon"><Icon name={websiteAnalysisState === "success" ? "check" : websiteAnalysisState === "failed" ? "warning" : "spark"} /></span>
				<small>Codex 官网差距分析 · 独立诊断</small>
				<h2 id="website-analysis-title">{websiteAnalysisState === "switching" ? "正在切换官网分析范围" : ["submitting", "running"].includes(websiteAnalysisState) ? "Codex 正在分析官网差距" : websiteAnalysisState === "failed" ? "官网分析未完成" : websiteAnalysisState === "success" ? "官网差距分析已完成" : websiteAnalysisState === "empty" ? "当前范围未发现官网差距" : websiteAnalysisState === "missing-batch" ? "请先选择真实观测批次" : websiteAnalysisState === "missing-website" ? "请先配置官网地址" : websiteAnalysisState === "not-ready" ? "Codex 尚未就绪" : websiteAnalysisState === "busy" ? "Codex 正在处理其他任务" : "让 Codex 分析官网差距"}</h2>
				<p>{websiteAnalysisState === "switching" ? "新范围返回前不展示旧结果。" : ["submitting", "running"].includes(websiteAnalysisState) ? websiteGapFeedback || `正在读取 ${websiteGapAnalysis?.evidence_count ?? 0} 条真实证据；诊断不会进入内容发布流程。` : websiteAnalysisState === "failed" ? websiteGapFeedback || websiteGapAnalysis?.error_message || "Codex 未能返回通过证据校验的官网诊断。" : websiteAnalysisState === "success" ? `已形成 ${websiteGapAnalysis?.recommendation_count ?? 0} 项官网诊断建议；它们不会变成优先机会，也不会启动写稿和发布。` : websiteAnalysisState === "empty" ? "Codex 已完成分析，但当前数据不支持具体官网改进结论。" : websiteAnalysisState === "missing-batch" ? "官网分析只使用你选定的批次、模型和问题数据。" : websiteAnalysisState === "missing-website" ? "官网地址用来限定诊断边界，系统不会接受任意站点。" : websiteAnalysisState === "not-ready" ? "完成本机 Codex 登录与自检后才能运行官网分析。" : websiteAnalysisState === "busy" ? `当前运行容量 ${agentCapacityUsed}/${agentCapacityLimit}，有空位后可继续。` : "只有你点击后，Codex 才会读取当前范围的官网表现和竞品内容。"}</p>
				{selectedBatchId ? <span className="pa-website-analysis-scope">批次 #{selectedBatchId} · {selectedModelLabel} · {selectedQuestionLabel}</span> : null}
				{websiteAnalysisState === "success" ? <div className="pa-website-analysis-results">
					<div className="pa-website-analysis-metric"><b>官网引用 {websiteCitationCount}/{websiteEligibleCount}</b><span>{websiteGapAnalysis?.recommendation_count ?? 0} 项诊断建议</span></div>
					{websiteRecommendations.slice(0, 3).map((recommendation, index) => <article key={`${recommendation.title}-${index}`}><div><em>{recommendation.priority === "high" ? "高优先级" : recommendation.priority === "medium" ? "中优先级" : "低优先级"}</em><b>{recommendation.title}</b></div><span>{recommendation.required_content.slice(0, 3).join(" · ") || recommendation.target_page}</span></article>)}
				</div> : null}
				<div className="pa-website-analysis-actions">
					{["idle", "failed", "success", "empty"].includes(websiteAnalysisState) ? <button type="button" onClick={startWebsiteGapAnalysis} disabled={!selectedBatchId || !websiteUrl || !agentRuntime?.ready || !agentCapacityAvailable}>{["success", "empty"].includes(websiteAnalysisState) ? "重新分析当前范围" : "让 Codex 分析官网"}</button> : null}
					{websiteAnalysisState === "missing-website" || websiteAnalysisState === "not-ready" ? <Link href={`/geo/${workspaceId}/settings`}>前往设置 <Icon name="arrow" /></Link> : null}
				</div>
			</div>
		</section>

			{isScopePending ? <section className="pa-scope-loading" role="status" aria-live="polite"><div><i /><b>正在切换真实数据范围</b><span>新范围返回前不会继续展示旧机会。</span></div><div className="pa-scope-skeleton"><i /><i /><i /></div></section> : filtered.length === 0 ? <section className="pa-empty"><span><Icon name="spark" /></span><h2>{opportunityAnalysisActive ? "Codex 正在判断优先机会" : opportunityAnalysis?.status === "succeeded" ? "Codex 未发现足够可靠的优先机会" : "尚未让 Codex 分析这个批次"}</h2><p>{opportunityAnalysisActive ? `正在阅读批次 #${opportunityAnalysis?.batch_id} 的 ${opportunityAnalysis?.evidence_count ?? 0} 条真实证据；完成并通过证据校验前，这里保持为空。` : opportunityAnalysis?.status === "succeeded" ? opportunityAnalysis.analysis_summary || "Codex 已完成分析，但当前数据不足以支持具体行动。" : selectedBatch ? `已选定批次 #${selectedBatch.id}。只有你点击后，Codex 才会阅读该批次的回答、信源和竞品内容并给出判断。` : "请先完成一次真实联网观测。"}</p><div className="pa-empty-actions"><button type="button" onClick={refreshOpportunities} disabled={isSaving || opportunityAnalysisActive || !selectedBatchId || !agentRuntime?.ready}>{isSaving ? "正在提交…" : opportunityAnalysisActive ? "Codex 正在判断…" : "让 Codex 分析当前批次"}</button><Link href={`/geo/${workspaceId}`}>发起真实观测 <Icon name="arrow" /></Link></div></section> : <>
			<section className="pa-workspace">
				<div className="pa-opportunity-panel">
					<header><div><h2>系统发现的优先机会</h2><p>仅显示真实观测形成的运营机会；点击卡片查看详细判断。</p></div><small>{unselected} 待选择 · {inProgress} 进行中</small></header>
					<div className="pa-opportunity-list">
						{filtered.map((item) => <article id={`opportunity-card-${item.id}`} key={item.id} tabIndex={0} aria-expanded={expandedOpportunityId === item.id} aria-label={`${item.title}，点击查看详细判断`} className={selected?.id === item.id ? "is-selected" : ""} onClick={() => { setSelectedId(item.id); setExpandedOpportunityId((current) => current === item.id ? null : item.id); }} onKeyDown={(event) => { if (event.target !== event.currentTarget || !["Enter", " "].includes(event.key)) return; event.preventDefault(); setSelectedId(item.id); setExpandedOpportunityId((current) => current === item.id ? null : item.id); }}>
							<div className="pa-opportunity-main"><span className={`pa-priority ${item.priority}`}>{priorityLabel[item.priority]}</span><h3>{item.title}</h3>{item.sourceType === "website_audit" ? <div className="pa-opportunity-source"><img src="/icon.svg" alt="春秋元泉 GEO 标志" /><span><b>官网原始响应</b><small>审计 #{item.websiteAuditId} · 不计为模型观测</small></span></div> : <div className="pa-models">{item.modelLabels.slice(0, 4).map((label) => <ModelBadge key={label} label={label} />)}</div>}<small className="pa-opportunity-proof">{item.proof}</small></div>
							<div className="pa-gap"><small>{item.type === "website" ? "开发团队待补齐" : item.sourceStrategy === "direct_operable_source" ? "可直接运营的信源" : item.sourceStrategy === "build_controlled_alternative" ? "外部参考 → 建立可控信源" : "建议补齐的信源"}</small><div className="pa-source-tags">{item.sourceTargetLabel ? <span>{item.sourceTargetLabel}</span> : suggestedSources(item.type).map((source) => <span key={source}>{source}</span>)}{item.type !== "website" ? item.recommendedPlatforms.slice(0, 3).map((platformKey) => <span key={platformKey}>{platformDisplayName(platformKey)}</span>) : null}</div><em>{item.sourceTargetDetail || `建议载体 · ${suggestedCarrier(item.type)}`}</em></div>
							<div className="pa-opportunity-actions" onClick={(event) => event.stopPropagation()}><span className={item.existingAction ? "pa-action-current" : item.generationReady ? "pa-evidence-ok" : "pa-action-blocked"}><Icon name={item.existingAction ? "arrow" : item.generationReady ? "check" : "warning"} />{item.existingAction ? "行动进行中" : item.generationReady ? "证据充分" : "检查受阻"}</span><button type="button" onClick={() => setSelectedId(item.id)}>{item.existingAction ? "继续行动" : "选择并开始"}</button>{item.websiteAuditId ? <a href="#website-audit">查看官网证据 <Icon name="arrow" /></a> : item.evidenceIds[0] ? <Link href={`/geo/${workspaceId}/evidence/${item.evidenceIds[0]}`}>查看 {item.evidenceIds.length} 条证据 <Icon name="arrow" /></Link> : null}</div>
							{expandedOpportunityId === item.id ? <section className="pa-opportunity-details" aria-label="Codex 机会判断详情" onClick={(event) => event.stopPropagation()}>
								<div className="pa-opportunity-detail-grid">
									<div><b>建议补齐的内容</b>{item.missingContent.length ? <ul>{item.missingContent.map((value) => <li key={value}>{value}</li>)}</ul> : <p>当前判断未拆分更细的内容项。</p>}</div>
									<div><b>同信源竞品内容规律</b>{item.competitorContentPatterns.length ? <ul>{item.competitorContentPatterns.map((value) => <li key={value}>{value}</li>)}</ul> : <p>未发现足够稳定的竞品内容规律。</p>}</div>
									<div><b>边界与待确认项</b>{item.uncertainties.length ? <ul>{item.uncertainties.map((value) => <li key={value}>{value}</li>)}</ul> : <p>本轮没有额外的待确认项。</p>}</div>
								</div>
								<footer><span>{item.proof}{item.codexThreadId ? ` · Thread ${item.codexThreadId.slice(0, 8)}` : ""}</span><button type="button" onClick={() => collapseOpportunityDetails(item.id)}>收起详情 <Icon name="chevron" /></button></footer>
							</section> : null}
						</article>)}
					</div>
				</div>

				<aside className={`pa-current-action ${isTimelineCollapsed ? "is-collapsed" : ""}`}>
					<header ref={timelineHeaderRef}><h2>本次行动</h2><button type="button" onClick={() => setIsTimelineCollapsed((value) => !value)} aria-expanded={!isTimelineCollapsed} aria-controls="pa-current-action-timeline">{isTimelineCollapsed ? "展开" : "收起"} <Icon name="chevron" /></button></header>
					{!isTimelineCollapsed && selected ? <ol id="pa-current-action-timeline">
						<ActionStage index={1} label="选择信源" state={stage >= 1 ? "done" : "active"}>{stage === 0 ? <div className="pa-stage-card"><b>目标载体</b><p>{selected.recommendedAsset}</p><form action={(formData) => startSaving(() => createAction(formData))}><input type="hidden" name="title" value={`${selected.title}：${selected.questionText}`} /><input type="hidden" name="rationale" value={selected.summary} /><input type="hidden" name="hypothesis" value={selected.type === "website" ? "完成官网内容修复后，以新一轮同版本审计验证服务端可读性与页面结构变化。" : `下一轮相同问题中，期待“${selected.recommendedAsset}”补齐后，春秋元泉进入候选或获得引用。`} /><input type="hidden" name="priority" value={selected.priority} />{selected.questionId ? <input type="hidden" name="question_plan_id" value={selected.questionId} /> : null}{selected.evidenceIds[0] ? <input type="hidden" name="source_evidence_id" value={selected.evidenceIds[0]} /> : null}{selected.backendId ? <input type="hidden" name="opportunity_id" value={selected.backendId} /> : null}<button disabled={isSaving} type="submit">{isSaving ? "正在保存行动…" : "选择这个行动"}</button></form></div> : <p className="pa-stage-note">{selected.sourceType === "website_audit" ? `已关联官网审计 #${selected.websiteAuditId} 的原始响应与问题清单。` : "已关联当前问题的真实模型观测与行动记录。"}</p>}</ActionStage>
						<ActionStage index={2} label="Agent 调研与生成" state={runActive ? "active" : currentReviewPackage ? "done" : currentRun ? "idle" : stage === 1 ? "active" : "idle"}>
							{stage === 1 && selected.existingAction && !currentRun ? <div className="pa-stage-card"><b>目标平台</b><p>{selected.type === "website" ? !selected.generationReady ? "本轮没有回读到完整官网原始 HTML。请先恢复公网访问并重新检查，当前不会伪装生成内容。" : !websiteGenerationReady ? "官网没有可回读的产品正文，品牌事实库也为空。先补齐至少一条带公开来源的事实，避免只生成通用整改框架。" : "Codex 会读取官网审计和品牌事实库，再生成仅用于官网修复的待审核稿。" : "Codex 会先查阅平台官方规则，再根据真实观测和品牌官网生成差异化草稿。"}</p>{selected.type === "website" && !websiteGenerationReady ? <Link href={`/geo/${workspaceId}/settings#brand-facts`}>去设置补齐品牌事实 →</Link> : null}<div className="pa-platform-picker">{availableTargetPlatforms.map((platform) => <label key={platform.key} className={targetPlatforms.includes(platform.key) ? "is-selected" : ""}><input type="checkbox" checked={targetPlatforms.includes(platform.key)} disabled={selected.type === "website"} onChange={() => setTargetPlatforms((current) => current.includes(platform.key) ? current.filter((key) => key !== platform.key) : [...current, platform.key])} /><img src={platform.logo} alt={platform.key === "official_site" ? "春秋元泉 GEO 标志" : `${platform.label} 官方标志`} /><span>{platform.label}</span></label>)}</div><button disabled={isSaving || !targetPlatforms.length || !agentCanStart || !selected.generationReady || !websiteGenerationReady} type="button" onClick={beginAgent}><Icon name="spark" />{isSaving ? "正在入队…" : !selected.generationReady ? "等待官网重新检查" : !websiteGenerationReady ? "先补齐品牌事实" : !agentRuntime?.ready ? "Codex 未就绪，请先去设置" : !agentCapacityAvailable ? "Agent 正忙，请等待当前任务" : "启动本机 Codex Agent"}</button></div> : null}
							{currentRun ? <div className="pa-agent-run">
								<div className="pa-agent-runtime">
									<span><img src="/brand/openai.svg" alt="OpenAI 官方标志" /></span>
									<div><b>{currentRun.model || "Local Codex"}</b><small>Run #{currentRun.id}{visibleAgentProgress && visibleAgentProgress.attempt_number > 1 ? ` · 第 ${visibleAgentProgress.attempt_number} 轮执行` : ""} · {agentStageLabels[currentRun.stage] || currentRun.stage}</small></div>
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
										<b>本轮持久化结果</b>
										{visibleAgentProgress.artifacts.length ? visibleAgentProgress.artifacts.map((artifact) => <span key={artifact.id}>{agentArtifactLabel(artifact.artifact_kind)} · {formatArtifactSize(artifact.size_bytes)} · 已校验归档</span>) : <span>尚未产生可审核工件</span>}
										{currentReviewPackage && !(reviewNeedsRevision && runActive) ? <span>内容资产 #{currentReviewPackage.asset.id} · {currentReviewPackage.variants.length} 个平台稿 · {currentReviewPackage.claims.length} 条主张</span> : null}
									</div>
									{visibleAgentProgress.event_count ? <button ref={agentLogToggleRef} className="pa-agent-log-toggle" type="button" onClick={() => setAgentDetailsExpanded((value) => !value)} aria-expanded={agentDetailsExpanded}>{agentDetailsExpanded ? "收起执行记录" : `查看 ${visibleAgentProgress.event_count} 条执行记录`} <Icon name="chevron" /></button> : null}
									{agentDetailsExpanded ? <><small className="pa-agent-log-note">{visibleAgentProgress.attempt_number > 1 ? `当前为第 ${visibleAgentProgress.attempt_number} 轮；下方保留全部历史事件，` : ""}连续重复事件已合并展示，原始事件完整保留。</small><ul className="pa-agent-event-log">{groupedAgentEvents.map((event) => <li key={event.key}><time>{formatEventTime(event.firstAt)}{event.count > 1 ? `–${formatEventTime(event.lastAt)}` : ""}</time><span><b>{agentStageLabels[event.stage] || event.stage}{event.count > 1 ? ` · ${event.count} 次` : ""}</b>{event.message}</span></li>)}</ul><button className="pa-agent-log-bottom-collapse" type="button" onClick={collapseAgentLog}><span aria-hidden="true">↑</span>收起执行记录</button></> : null}
								</> : null}
								{currentRun.status === "failed" && currentRun.error_message ? <p className="is-error">{currentRun.error_message}</p> : null}
								<div className="pa-agent-actions">{runActive && currentRun.status !== "cancelling" ? <button type="button" onClick={requestInterrupt} disabled={isSaving}>中止运行</button> : null}{currentRun.status === "awaiting_review" && !hasCapturedVisual ? <button type="button" onClick={requestVisualCapture} disabled={isSaving}>{isSaving ? "正在采集…" : "补采官网素材"}</button> : null}{["cancelled", "failed"].includes(currentRun.status) && currentRun.codex_thread_id ? <button type="button" onClick={requestResume} disabled={isSaving || !agentCanStart}>{agentCapacityAvailable ? "恢复原任务" : "Agent 正忙"}</button> : null}{["cancelled", "failed"].includes(currentRun.status) && !currentRun.codex_thread_id ? <button type="button" onClick={beginAgent} disabled={isSaving || !agentCanStart}>{agentCapacityAvailable ? "重新启动" : "Agent 正忙"}</button> : null}</div>
							</div> : null}
							{agentFeedback ? <p className="pa-agent-error" role="status">{agentFeedback}</p> : null}
						</ActionStage>
						<ActionStage index={3} label="人工审核" state={approvedPlatformKeys.length ? "done" : currentReviewPackage && !(reviewNeedsRevision && runActive) ? "active" : "idle"}>
							{currentReviewPackage ? <div className={`pa-stage-card${reviewNeedsRevision || draftMissesAvailableBrandFacts || brandFactVerificationRequired ? " is-revision" : ""}`}>
								<b>{approvedPlatformKeys.length
									? `已通过 ${approvedPlatformKeys.length} 个平台稿`
									: reviewNeedsRevision
										? (runActive ? "正在根据意见修订" : "已退回，等待生成新版本")
										: brandFactVerificationRequired
											? (draftUsesUnverifiedBrandFacts ? `稿件引用了 ${currentReviewPackage.used_unverified_brand_fact_count} 条未核验品牌事实` : "品牌事实尚未通过原文核验")
										: draftMissesAvailableBrandFacts
											? "品牌事实已更新，需要退回生成新版"
											: "草稿已入库，等待你确认"}</b>
								<p>内容资产 #{currentReviewPackage.asset.id} · v{currentReviewPackage.asset.version} · {currentReviewPackage.variants.length} 个平台版本 · {currentReviewPackage.pending_claim_count} 条主张待人工判断。</p>
								{reviewNeedsRevision && !runActive
									? <button type="button" onClick={requestRevision} disabled={isSaving}>{isSaving ? "正在排队…" : "根据意见生成新版本"}</button>
									: <button type="button" onClick={openReviewWorkbench}>{approvedPlatformKeys.length
										? "查看审核记录"
										: reviewNeedsRevision
											? "查看退回意见"
											: brandFactVerificationRequired
												? "查看未核验事实"
											: draftMissesAvailableBrandFacts
												? "处理旧稿并填写修改意见"
												: "审阅内容与事实"}</button>}
							</div> : <p className="pa-stage-note">只有 Agent 成功生成并持久化内容后，审核才会开放。</p>}
						</ActionStage>
						<ActionStage index={4} label={selected.type === "website" ? "交付官网稿" : "写入平台草稿"} state={deliveryComplete ? "done" : approvedPlatformKeys.length ? "active" : "idle"}>
							{approvedPlatformKeys.length ? hasApprovedOfficialSiteDraft && !syncableApprovedPlatformKeys.length ? <div className="pa-stage-card">
								<b>{websiteHandoffReady ? "官网交付记录已建立" : "官网稿已通过审核，可以交付"}</b>
								<p>{websiteHandoffReady ? "稿件等待网站负责人部署。只有回填同域公开 URL 后，系统才会记录为已上线并开放复测。" : "先在内容库查看或导出已审核稿，再建立交付记录。建立记录不等于官网已经上线。"}</p>
								<Link href={`/geo/${workspaceId}/content`}>查看并导出官网稿</Link>
								{!websiteHandoffReady ? <button type="button" onClick={beginWebsiteHandoff} disabled={isSaving}>{isSaving ? "正在建立…" : "建立官网交付记录"}</button> : null}
								{publicationMessage && !publicationReady ? <p className="pa-inline-feedback" role="status">{publicationMessage}</p> : null}
							</div> : <div className="pa-stage-card">
								<b>{allDraftsSaved ? `${savedDraftCount} 个草稿已人工确认` : pendingDraftReadbackCount ? `${pendingDraftReadbackCount} 个草稿等待你打开确认` : "已通过的平台稿可写入"}</b>
								<p>{currentDistribution ? `同步任务 #${currentDistribution.id} · ${savedDraftCount} 个已确认，${pendingDraftReadbackCount} 个待打开确认。` : "打开同步助手后，你选择平台并确认写入；系统不会发布。"}</p>
								{pendingDraftReadbackTargets.length ? <div className="pa-draft-readback-list" aria-label="等待人工确认的草稿">{pendingDraftReadbackTargets.map((target) => {
									const platform = platformOptions.find((item) => item.key === target.platform_key);
									return <div key={target.id}>{platform ? <img src={platform.logo} alt="" /> : null}<span><b>{platform?.label || target.platform_key}</b><small>链接已返回，尚未计为草稿已保存</small></span><a href={target.candidate_draft_url || "#"} target="_blank" rel="noreferrer">打开草稿</a><button type="button" onClick={() => confirmDraftTarget(target.id)} disabled={isSaving}>{isSaving ? "正在确认…" : "我已打开并确认"}</button></div>;
								})}</div> : null}
								<button type="button" onClick={openSyncAssistant} disabled={allDraftsSaved || !syncableApprovedPlatformKeys.length || !platformKeysNeedingSync.length}>{allDraftsSaved ? "草稿已人工确认" : !platformKeysNeedingSync.length && pendingDraftReadbackCount ? "等待确认草稿" : "打开文章同步助手"}</button>
							</div> : <p className="pa-stage-note">{selected.type === "website" ? "只有官网稿通过人工审核后，才能建立交付记录；当前不会计为已上线。" : "只允许写入草稿，最终发布仍由人工确认。"}</p>}
						</ActionStage>
						<ActionStage index={5} label={selected.type === "website" ? "人工上线" : "人工发布"} state={allTargetsPublished ? "done" : publicationReady ? "active" : "idle"}>
							{publicationReady && currentDistribution ? <div className="pa-publication-list">{currentDistribution.targets.map((target) => {
								const platform = platformOptions.find((item) => item.key === target.platform_key);
								const published = target.human_publish_status === "published" && Boolean(target.public_url);
								const isWebsiteTarget = target.platform_key === "official_site";
								const publiclyVerified = target.publication_verification_status === "publicly_verified";
								return <section key={target.id} className={publiclyVerified ? "is-published" : ""}><header><span>{platform ? <img src={platform.logo} alt="" /> : null}<b>{platform?.label || target.platform_key}</b></span><small>{publicationRecordsLocked ? "复测已开始，记录已锁定" : publiclyVerified ? "公网已核验" : published ? "等待公网校验" : (isWebsiteTarget ? "等待网站负责人上线" : "等待人工发布")}</small></header><div><input type="url" aria-label={`${platform?.label || target.platform_key}${isWebsiteTarget ? "已上线页面" : "公开文章"} URL`} placeholder={isWebsiteTarget ? "粘贴已上线的同域官网 URL" : "粘贴具体公开文章 URL"} value={publicationUrls[target.id] ?? target.public_url ?? ""} disabled={publicationRecordsLocked} onChange={(event) => setPublicationUrls((current) => ({ ...current, [target.id]: event.target.value }))} /><button type="button" disabled={publicationRecordsLocked || isSaving || !((publicationUrls[target.id] ?? target.public_url ?? "").trim())} onClick={() => savePublication(target.id)}>{publicationRecordsLocked ? "已锁定" : isSaving ? "正在核验…" : publiclyVerified ? "更正并复验" : isWebsiteTarget ? "核验并记录上线" : "核验并记录发布"}</button></div>{target.draft_url ? <a href={target.draft_url} target="_blank" rel="noreferrer">打开平台草稿</a> : null}{target.public_url ? <a href={target.public_url} target="_blank" rel="noreferrer">{isWebsiteTarget ? "查看已上线页面" : "查看公开文章"}</a> : null}</section>;
							})}{publicationMessage ? <p className="pa-inline-feedback" role="status">{publicationMessage}</p> : null}</div> : <p className="pa-stage-note">{selected.type === "website" ? "官网交付记录建立后，才能回填真实上线 URL。" : "草稿真实回读后，才可记录人工发布结果。"}</p>}
						</ActionStage>
						<ActionStage index={6} label="同口径复测" state={comparableRetestComplete ? "done" : retestActive || allTargetsPublished ? "active" : "idle"}>
							{allTargetsPublished ? <div className="pa-stage-card pa-retest-card"><b>{retestComplete ? retestConclusionLabel : retestActive ? "真实联网复测进行中" : "可以创建可比复测"}</b><p>{currentRetest ? `基线批次 #${currentRetest.baseline_batch_id} · ${retestProviderCount} 个模型 × ${retestRepeatCount} 次 · 原问题不变。` : "后端会复用基线问题、模型渠道、模型版本和重复次数；不允许前端自行改变口径。"}</p>{currentRetest?.batch ? <><div className="pa-retest-progress" role="progressbar" aria-label="真实联网复测进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={currentRetest.batch.progress_percent}><i style={{ width: `${currentRetest.batch.progress_percent}%` }} /></div><small>{currentRetest.batch.succeeded + currentRetest.batch.failed}/{currentRetest.batch.total} 已结束 · 成功 {currentRetest.batch.succeeded} · 失败 {currentRetest.batch.failed}</small></> : null}{!retestActive && (!retestComplete || !comparableRetestComplete) ? <button type="button" onClick={beginRetest} disabled={isSaving}>{isSaving ? "正在创建…" : currentRetest?.conclusion === "insufficient_evidence" ? "重新创建同口径复测" : "创建真实复测"}</button> : null}{retestComplete ? <p className={comparableRetestComplete ? "is-success" : "is-warning"}>{comparableRetestComplete ? `结论：${retestConclusionLabel}。该结论只描述同口径观测差异，不宣称发布构成因果。` : "本轮已经结束，但样本或模型版本不完整，不能得出变化结论。"}</p> : null}{retestMessage ? <p className="pa-inline-feedback" role="status">{retestMessage}</p> : null}</div> : <p className="pa-stage-note">{selected.type === "website" ? "记录真实官网上线 URL 后，复测入口才会开放。" : "全部目标平台记录真实公开 URL 后，复测入口才会开放。"}</p>}
						</ActionStage>
					</ol> : !isTimelineCollapsed ? <p className="pa-empty-copy">调整筛选条件后，选择一个机会开始。</p> : null}
					{!isTimelineCollapsed && selected ? <div className="pa-current-action-collapse"><button type="button" onClick={collapseTimeline}><span aria-hidden="true">↑</span>收起本次行动</button></div> : null}
				</aside>
			</section>

			{actions.length > 0 ? <section className="pa-progress">
				<header><div><h2>当前行动的内容与发布进度</h2><p>只显示当前选中行动的持久化状态；不会混入其他行动或历史稿件。</p></div></header>
				<div className="pa-progress-lanes">
					<div className={runActive ? "is-current" : ""}><b>Agent 生成</b><span>{currentAssetId ? 1 : 0}</span><p>{runActive ? "当前任务正在调研与生成" : currentAssetId ? "当前内容版本已持久化" : "当前行动还没有生成结果"}</p></div>
					<div className={currentRun?.stage === "researching_brand" ? "is-current" : ""}><b>事实校验</b><span>{currentReviewPackage?.claims.filter((claim) => claim.verification_status === "source_linked").length ?? 0}</span><p>可追溯主张与待人工判断项分开记录</p></div>
					<div className={currentRun?.stage === "adapting_platforms" ? "is-current" : ""}><b>平台适配</b><span>{currentReviewPackage?.variants.length ?? 0}</span><p>每个平台保留独立标题、结构和语气</p></div>
					<div className={currentReviewPackage && !approvedPlatformKeys.length ? "is-current" : ""}><b>人工审核</b><span>{approvedPlatformKeys.length || (currentReviewPackage ? 1 : 0)}</span><p>{approvedPlatformKeys.length ? `${approvedPlatformKeys.length} 个平台稿已通过` : reviewNeedsRevision || draftMissesAvailableBrandFacts ? "当前版本需重新生成，不能进入交付" : currentReviewPackage ? `${currentReviewPackage.pending_claim_count} 条主张待人工判断` : "等待当前行动生成可审核内容"}</p></div>
					<div className={(selected.type === "website" ? hasApprovedOfficialSiteDraft && !websiteHandoffReady : syncableApprovedPlatformKeys.length > 0 && !allDraftsSaved) ? "is-current" : ""}><b>{selected.type === "website" ? "官网交付" : "写入草稿"}</b><span>{selected.type === "website" ? (websiteHandoffReady ? 1 : 0) : savedDraftCount}</span><p>{selected.type === "website" ? websiteHandoffReady ? "交付记录已建立，等待网站负责人上线" : "审核通过后由人工建立官网交付记录" : currentDistribution ? pendingDraftReadbackCount ? `${savedDraftCount} 个已确认 · ${pendingDraftReadbackCount} 个待打开确认` : `${savedDraftCount}/${currentDistribution.targets.length} 个目标已人工确认草稿可见` : "等待外部平台稿审核通过后人工触发"}</p></div>
					<div className={publicationReady && !allTargetsPublished ? "is-current" : ""}><b>{selected.type === "website" ? "人工上线" : "人工发布"}</b><span>{publishedTargetCount}</span><p>{currentDistribution ? `${publishedTargetCount}/${currentDistribution.targets.length} 个目标已记录公开 URL` : selected.type === "website" ? "上线始终由网站负责人完成" : "发布始终由人工在平台完成"}</p></div>
					<div className={retestActive ? "is-current" : ""}><b>同口径复测</b><span>{currentRetest?.status === "completed" ? 1 : 0}</span><p>{currentRetest?.batch ? `真实队列 ${currentRetest.batch.progress_percent}%` : "上线或发布完成后复用原问题与模型"}</p></div>
				</div>
				<footer className="pa-progress-footer"><span><Icon name="eye" />生成、审核、交付、上线/发布与复测都使用独立真实状态</span><div><Link href={`/geo/${workspaceId}/content`}>查看内容库</Link><button type="button" onClick={currentReviewPackage ? openReviewWorkbench : () => setPreviewMessage("请先完成 Agent 调研与生成。")}>预览内容</button><button className="pa-sync-button" type="button" onClick={selected.type === "website" ? beginWebsiteHandoff : openSyncAssistant} disabled={selected.type === "website" ? !hasApprovedOfficialSiteDraft || websiteHandoffReady || isSaving : !syncableApprovedPlatformKeys.length || allDraftsSaved || !platformKeysNeedingSync.length} title={selected.type === "website" ? !hasApprovedOfficialSiteDraft ? "请先通过官网稿人工审核" : websiteHandoffReady ? "官网交付记录已建立，等待人工上线" : "建立官网人工交付记录" : allDraftsSaved ? "已审核平台稿均已人工确认可见" : pendingDraftReadbackCount && !platformKeysNeedingSync.length ? "请在本次行动中打开草稿并确认" : syncableApprovedPlatformKeys.length ? "打开文章同步助手" : "请先通过至少一个外部平台稿"}>{selected.type === "website" ? !hasApprovedOfficialSiteDraft ? "等待官网稿审核" : websiteHandoffReady ? "等待人工上线" : "建立官网交付" : allDraftsSaved ? "草稿已确认" : pendingDraftReadbackCount && !platformKeysNeedingSync.length ? "等待确认草稿" : "打开同步助手"} <Icon name="arrow" /></button></div></footer>
				{previewMessage ? <p className="pa-front-notice" role="status">{previewMessage}</p> : null}
			</section> : null}
		{reviewOpen && currentReviewPackage ? <div className="pa-review-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !isSaving && !isVariantSaving) setReviewOpen(false); }}>
			<section ref={reviewDialogRef} className="pa-review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-workbench-title" tabIndex={-1}>
				<header><div><small>人工审核 · 内容资产 #{currentReviewPackage.asset.id}</small><h2 id="review-workbench-title">核对事实，再决定哪些平台稿进入后续流程</h2><p>平台稿可以直接编辑并保存；保存后再审核，审核通过后内容锁定。</p></div><button type="button" onClick={() => setReviewOpen(false)} disabled={isSaving || isVariantSaving} aria-label="关闭审核工作台">×</button></header>
				<nav className="pa-review-tabs" aria-label="内容版本">
					<button type="button" className={reviewTab === "master" ? "is-active" : ""} onClick={() => setReviewTab("master")}><Icon name="draft" />母稿</button>
					{currentReviewPackage.variants.map((variant) => {
						const platform = platformOptions.find((item) => item.key === variant.platform_key);
						const viewed = viewedPlatformKeys.includes(variant.platform_key);
						return <button key={variant.id} type="button" className={reviewTab === variant.platform_key ? "is-active" : ""} onClick={() => openPlatformReview(variant.platform_key)}>{platform ? <img src={platform.logo} alt="" /> : null}{platform?.label || variant.platform_key}<span>{variant.status === "approved" ? "已通过" : viewed ? "已查看" : "待查看"}</span></button>;
					})}
				</nav>
				{!websiteDraftReadyForApproval ? <div className="pa-review-readiness" role="status"><div><b>{draftUsesUnverifiedBrandFacts ? `这版稿件引用了 ${currentReviewPackage.used_unverified_brand_fact_count} 条尚未核验的品牌事实` : brandFactVerificationRequired ? "工作区已有品牌事实，但还没有通过原文核验" : "这版内容是整改框架，不是可上线的品牌成稿"}</b><p>{brandFactVerificationRequired ? `当前有 ${currentReviewPackage.unverified_brand_fact_count} 条活跃事实只配置了来源 URL，尚未完成公网与完整原文核验。请先在设置中核验，再退回生成新版本；系统不会把“有 URL”伪装成“事实已核验”。` : "生成时没有通过公网与原文核验的品牌事实。请先在设置中补齐并核验，再退回生成新版本。"}</p></div><Link href={`/geo/${workspaceId}/settings#brand-facts`}>{brandFactVerificationRequired ? "核验品牌事实" : "补齐品牌事实"} →</Link></div> : null}
				{websiteDraftReadyForApproval && draftMissesAvailableBrandFacts ? <div className="pa-review-readiness" role="status"><div><b>这版稿件没有使用当前品牌事实</b><p>工作区已有 {currentReviewPackage.available_sourced_brand_fact_count} 条带公开来源的品牌事实，但这版内容引用了 0 条。请填写修改意见并退回，然后生成新版本，避免继续审核过时的“待补证”稿。</p></div><Link href={`/geo/${workspaceId}/settings#brand-facts`}>查看品牌事实 →</Link></div> : null}
				<div className="pa-review-body">
					<article className="pa-review-document">
						{reviewTab === "master" ? <><small>母稿 · v{currentReviewPackage.asset.version}</small><h3>{currentReviewPackage.asset.title}</h3><p className="pa-review-summary">{currentReviewPackage.asset.summary}</p><div className="pa-review-copy" dangerouslySetInnerHTML={{ __html: markdownToSafeHtml(currentReviewPackage.asset.body_markdown) }} /></> : (() => {
							const variant = currentReviewPackage.variants.find((item) => item.platform_key === reviewTab);
							if (!variant) return null;
							const platformLabel = platformOptions.find((item) => item.key === variant.platform_key)?.label || variant.platform_key;
							const editing = editingVariantId === variant.id;
							const draft = variantEdits[variant.id] ?? { title: variant.title, summary: variant.summary, body_markdown: variant.body_markdown };
							const locked = approvedPlatformKeys.includes(variant.platform_key);
							return <>{editing ? <div className="pa-variant-editor">
								<header><div><small>{platformLabel} · 人工修订</small><b>直接修改本平台将要写入的稿件</b></div><span>保存后才能通过审核</span></header>
								<label><span>标题</span><input value={draft.title} onChange={(event) => updateVariantEdit(variant.id, "title", event.target.value)} /></label>
								<label><span>摘要</span><textarea rows={3} value={draft.summary} onChange={(event) => updateVariantEdit(variant.id, "summary", event.target.value)} /></label>
								<label><span>正文（Markdown）</span><textarea className="is-body" value={draft.body_markdown} onChange={(event) => updateVariantEdit(variant.id, "body_markdown", event.target.value)} /></label>
								<footer><button type="button" onClick={() => setEditingVariantId(null)} disabled={isVariantSaving}>取消</button><button className="is-primary" type="button" onClick={() => persistVariantEdit(variant)} disabled={isVariantSaving}>{isVariantSaving ? "正在保存…" : "保存平台稿"}</button></footer>
							</div> : <><div className="pa-review-document-head"><small>{platformLabel} · {variant.policy_version}</small>{!locked ? <button type="button" onClick={() => beginVariantEdit(variant)}>编辑这份稿</button> : <span>已审核锁定</span>}</div><h3>{variant.title}</h3><p className="pa-review-summary">{variant.summary}</p><div className="pa-review-copy" dangerouslySetInnerHTML={{ __html: markdownToSafeHtml(variant.body_markdown) }} /></> }</>;
						})()}
					</article>
					<aside className="pa-review-checks">
						{reviewVisuals.length ? <section className="pa-review-visuals"><header><div><b>官网素材</b><small>{reviewVisuals.length} 张真实截图 · 来源与文件哈希已校验</small></div></header><div className="pa-review-visual-list">{reviewVisuals.map((visual) => <article key={visual.artifactId}><a href={`/api/geo/${workspaceId}/agent-artifacts/${visual.artifactId}/content`} target="_blank" rel="noreferrer"><img src={`/api/geo/${workspaceId}/agent-artifacts/${visual.artifactId}/content`} alt={visual.altText} /></a><div><b>{visual.purpose}</b><small>{visual.sourceHost}{visual.sha256 ? ` · ${visual.sha256.slice(0, 10)}…` : ""}</small><a href={visual.sourceUrl} target="_blank" rel="noreferrer">查看官方来源</a></div></article>)}</div></section> : null}
						<section><header><div><b>事实与来源</b><small>{currentReviewPackage.claims.length - pendingClaims.length} 条已有处理结论 · {pendingClaims.length} 条待判断</small></div></header><div className="pa-claim-list">{currentReviewPackage.claims.map((claim) => {
							const needsHuman = !resolvedClaimStatuses.includes(claim.verification_status);
							const confirmed = claim.verification_status === "human_confirmed" || confirmedClaimIds.includes(claim.id);
							const keptUnverified = claim.verification_status === "explicitly_unverified" || unverifiedClaimIds.includes(claim.id);
							const sourceLinked = ["source_linked", "verified"].includes(claim.verification_status);
							return <div key={claim.id} className={`pa-claim-item ${sourceLinked || confirmed ? "is-confirmed" : keptUnverified ? "is-unverified" : "is-pending"}`}>
								<span><b>{sourceLinked ? "已关联来源" : confirmed ? "人工确认属实" : keptUnverified ? "明确保留未核验" : "需要你判断"}</b><small>{claim.claim_text}</small>{claim.source_url ? <a href={claim.source_url} target="_blank" rel="noreferrer">查看来源</a> : needsHuman ? <em>没有外部来源，请根据所选稿件中的实际表述作出判断。</em> : null}</span>
								{needsHuman && !approvedPlatformKeys.length ? <div className="pa-claim-choice" role="group" aria-label={`审核主张：${claim.claim_text}`}><button type="button" aria-pressed={confirmed} className={confirmed ? "is-selected" : ""} onClick={() => setClaimReviewDecision(claim.id, "confirmed")}>确认属实</button><button type="button" aria-pressed={keptUnverified} className={keptUnverified ? "is-selected is-safe" : ""} onClick={() => setClaimReviewDecision(claim.id, "unverified")}>保持未核验</button></div> : null}
							</div>;
						})}</div></section>
						<section><header><div><b>通过的平台稿</b><small>先打开平台版本，再明确决定是否通过</small></div></header><div className="pa-review-platforms">{currentReviewPackage.variants.map((variant) => {
							const platform = platformOptions.find((item) => item.key === variant.platform_key);
							const viewed = viewedPlatformKeys.includes(variant.platform_key) || approvedPlatformKeys.includes(variant.platform_key);
							return <div key={variant.id} className={viewed ? "is-viewed" : "is-unseen"}><label><input type="checkbox" checked={reviewPlatformKeys.includes(variant.platform_key) || approvedPlatformKeys.includes(variant.platform_key)} disabled={!viewed || approvedPlatformKeys.includes(variant.platform_key)} onChange={() => setReviewPlatformKeys((current) => current.includes(variant.platform_key) ? current.filter((key) => key !== variant.platform_key) : [...current, variant.platform_key])} />{platform ? <img src={platform.logo} alt="" /> : null}<span><b>{platform?.label || variant.platform_key}</b><small>{variant.title}</small></span></label><button type="button" onClick={() => openPlatformReview(variant.platform_key)}>{viewed ? "再看一遍" : "查看稿件"}</button></div>;
						})}</div></section>
						<label className="pa-review-note"><span>审核意见</span><textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="退回修改时必填；通过时可记录核对说明。" rows={3} /></label>
						{reviewFeedback ? <p className="pa-review-feedback" role="status">{reviewFeedback}</p> : null}
					</aside>
				</div>
				<footer><span>{reviewNeedsRevision ? "旧版本和退回意见都会保留，新版本需重新审核。" : approvedPlatformKeys.length ? `审核已记录：${approvedPlatformKeys.length} 个平台稿已通过。` : !websiteDraftReadyForApproval ? brandFactVerificationRequired ? `当前 ${currentReviewPackage.unverified_brand_fact_count} 条品牌事实尚未核验，本稿匹配 ${currentReviewPackage.used_unverified_brand_fact_count} 条；只能退回重新生成。` : "当前版本没有使用可追溯品牌事实，只能退回修改，不能批准上线。" : draftMissesAvailableBrandFacts ? `当前事实库有 ${currentReviewPackage.available_sourced_brand_fact_count} 条可追溯品牌事实，这版稿件使用了 0 条；请退回生成新版本。` : `已处理 ${reviewedPendingClaimCount}/${pendingClaims.length} 条待判断事实 · 已查看 ${viewedPlatformKeys.length}/${currentReviewPackage.variants.length} 个平台稿 · 已选择 ${reviewPlatformKeys.length} 个通过。`}</span><div>{reviewNeedsRevision ? <button className="is-primary" type="button" onClick={requestRevision} disabled={isSaving || runActive}>{isSaving ? "正在排队…" : runActive ? "新版本生成中" : "根据意见生成新版本"}</button> : <><button type="button" onClick={() => submitReview("changes_requested")} disabled={isSaving || isVariantSaving || !reviewNote.trim()}>退回修改</button><button className="is-primary" type="button" onClick={() => submitReview("approved")} disabled={isSaving || isVariantSaving || editingVariantId !== null || !reviewPlatformKeys.length || selectedUnviewedPlatformCount > 0 || remainingPendingClaimCount > 0 || approvedPlatformKeys.length > 0 || !websiteDraftReadyForApproval || draftMissesAvailableBrandFacts}>{isVariantSaving ? "先保存当前修订" : isSaving ? "正在保存…" : editingVariantId !== null ? "先保存平台稿" : approvedPlatformKeys.length ? "审核已记录" : !websiteDraftReadyForApproval ? brandFactVerificationRequired ? "先核验品牌事实并生成新版本" : "先补齐品牌事实并生成新版本" : draftMissesAvailableBrandFacts ? "先用当前品牌事实生成新版本" : remainingPendingClaimCount > 0 ? `还需处理 ${remainingPendingClaimCount} 条事实` : selectedUnviewedPlatformCount > 0 ? "先查看已选平台稿" : !reviewPlatformKeys.length ? "选择通过的平台稿" : `通过 ${reviewPlatformKeys.length} 个平台稿`}</button></>}</div></footer>
			</section>
		</div> : null}
		{syncOpen ? <div className="pa-sync-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && syncPhase !== "syncing") setSyncOpen(false); }}>
			<section ref={syncDialogRef} className="pa-sync-dialog" role="dialog" aria-modal="true" aria-labelledby="sync-assistant-title" tabIndex={-1}>
				<header><div><small>文章同步助手</small><h2 id="sync-assistant-title">选择平台并确认写入</h2></div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"} aria-label="关闭同步助手">×</button></header>
				<div className="pa-sync-body">
					<div className="pa-sync-summary"><b>{currentReviewPackage?.asset.title || syncAction?.title}</b><p>将按平台分别使用已审核的标题和正文；只保存草稿，不执行发布。</p></div>
					<ol className="pa-sync-progress" aria-label="同步助手进度">{syncProgressSteps.map((step, index) => <li className={`is-${step.state}`} key={step.label}><i>{step.state === "done" ? "✓" : step.state === "issue" ? "!" : index + 1}</i><span><b>{step.label}</b><small>{step.hint}</small></span></li>)}</ol>
					<p className={`pa-sync-message is-${syncPhase}`} role="status">{syncMessage}</p>
					{syncAccounts.length ? <div className="pa-sync-platforms">{syncAccounts.map((account) => {
						const disabled = syncPhase !== "confirm";
						const accountKey = articleSyncAccountKey(account);
						const checked = selectedSyncAccounts.includes(accountKey);
						const platformKey = articleSyncPlatformKey(account);
						const platform = platformOptions.find((item) => item.key === platformKey);
						return <label key={accountKey} className={checked ? "is-selected" : ""}><input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggleSyncAccount(account)} />{platform ? <img src={platform.logo} alt={`${platform.label} 官方标志`} /> : null}<span><b>{account.displayName || account.title}</b><small>{account.status === "done" ? "草稿链接已返回，还需你打开确认正文可见" : account.status === "failed" ? (account.error || "写入失败") : account.msg || (account.uid ? `账号 ${account.uid}` : platform?.label || account.title)}</small></span>{account.editResp?.draftLink ? <a href={account.editResp.draftLink} target="_blank" rel="noreferrer">打开草稿</a> : null}</label>;
					})}</div> : null}
				</div>
				<footer><span>各平台按顺序写入。链接返回后仍需你打开草稿确认；全程不会点击发布。</span><div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"}>{["complete", "partial"].includes(syncPhase) ? "关闭" : "取消"}</button>{syncPhase === "confirm" ? <button className="is-primary" type="button" onClick={confirmSync} disabled={!selectedSyncAccounts.length}>确认写入 {selectedSyncAccounts.length} 个平台</button> : null}{["error", "partial"].includes(syncPhase) && platformKeysNeedingSync.length ? <button className="is-primary" type="button" onClick={openSyncAssistant}>重新检测平台</button> : null}</div></footer>
			</section>
		</div> : null}
		</>}
	</main>;
}
