"use client";

import { useEffect, useMemo, useState, useTransition, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";
import type {
	ActionExecutionDetail,
	ActionExecutionView,
	CleanroomDistributionRun,
	WorkspaceMembership,
} from "@/lib/cleanroom-v1-api";
import styles from "./action-command-center.module.css";

type Props = {
	workspaceId: string;
	initialActions: ActionExecutionDetail[];
	initialSelectedActionId?: number | null;
	initialShowLegacy?: boolean;
	viewActionIds: Record<ActionExecutionView, number[]>;
	members: WorkspaceMembership[];
	initialDistributionRuns: CleanroomDistributionRun[];
	legacyWorkbench: ReactNode;
	onAccept: (actionId: number, assigneeUserId: number, dueAt: string) => Promise<ActionExecutionDetail>;
	onTransition: (actionId: number, targetId: number, toStatus: string) => Promise<ActionExecutionDetail>;
	onSubmitEvidence: (actionId: number, targetId: number, sourceUrl: string) => Promise<ActionExecutionDetail>;
	onRequestApproval: (actionId: number, targetId: number, reviewerUserId: number, dueAt: string) => Promise<ActionExecutionDetail>;
	onDecideApproval: (actionId: number, approvalId: number, decision: "approved" | "changes_requested") => Promise<ActionExecutionDetail>;
	onSelfApprove: (actionId: number, targetId: number) => Promise<ActionExecutionDetail>;
	onConfirmDraftReadback: (runId: number, targetId: number) => Promise<CleanroomDistributionRun>;
	onBlock: (actionId: number, note: string) => Promise<ActionExecutionDetail>;
	onUnblock: (actionId: number) => Promise<ActionExecutionDetail>;
	onRetest: (actionId: number, targetIds: number[]) => Promise<ActionExecutionDetail>;
};

const ACTIONS_PER_PAGE = 5;

const typeMeta = {
	article: { label: "发布平台文章", tone: "blue" },
	official_site: { label: "修改官网页面", tone: "indigo" },
	structured_data: { label: "补充结构化数据", tone: "violet" },
	third_party_source: { label: "建设第三方信源", tone: "cyan" },
	analysis: { label: "调研与分析", tone: "slate" },
	legacy_unclassified: { label: "待确认行动类型", tone: "slate" },
} as const;

function ActionTypeGlyph({ type }: { type: string }) {
	if (type === "article") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.5 3.75h6.75l3.75 3.75v12.75H7.5z" /><path d="M14.25 3.75V7.5H18M10 11h5.5M10 14h5.5M10 17h3.75" /></svg>;
	if (type === "official_site") return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.75" y="5" width="16.5" height="14" rx="2.25" /><path d="M3.75 8.75h16.5M7 6.9h.01M9.25 6.9h.01M8 15.75l2.25-2.25 1.75 1.75 3.75-4" /></svg>;
	if (type === "structured_data") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.25 5.25 3.75 12l4.5 6.75M15.75 5.25 20.25 12l-4.5 6.75M14 3.75 10 20.25" /></svg>;
	if (type === "third_party_source") return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="12" r="2.25" /><circle cx="17.75" cy="6" r="2.25" /><circle cx="17.75" cy="18" r="2.25" /><path d="m8 11 7.75-4M8 13l7.75 4" /></svg>;
	if (type === "analysis") return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.75" /><path d="m14.75 14.75 4.5 4.5M8 10.5h5M10.5 8v5" /></svg>;
	return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.25" /><path d="M9.8 9.25a2.35 2.35 0 0 1 4.55.8c0 1.8-2.35 2-2.35 3.7M12 17.25h.01" /></svg>;
}

const workflow: Record<string, string[]> = {
	article: ["target_selected", "variant_generating", "awaiting_fact_review", "awaiting_platform_review", "draft_ready", "draft_write_requested", "draft_link_returned", "draft_saved", "awaiting_human_publish", "publicly_verified"],
	official_site: ["gap_confirmed", "change_proposed", "awaiting_brand_legal_review", "handed_to_web_owner", "deployed", "same_domain_readback_verified"],
	structured_data: ["schema_gap_confirmed", "jsonld_proposed", "awaiting_technical_review", "deployed", "source_readback_verified", "schema_validated"],
	third_party_source: ["source_selected", "cooperation_briefed", "external_execution", "external_content_live", "public_readback_verified"],
	analysis: ["scope_confirmed", "analysis_in_progress", "awaiting_analysis_review", "analysis_verified"],
};

const visibleWorkflow: Record<string, Array<{ label: string; states: string[] }>> = {
	article: [
		{ label: "准备内容", states: ["target_selected", "variant_generating"] },
		{ label: "审核内容", states: ["awaiting_fact_review", "awaiting_platform_review"] },
		{ label: "写入草稿", states: ["draft_ready", "draft_write_requested", "draft_link_returned", "draft_saved"] },
		{ label: "发布核验", states: ["awaiting_human_publish", "publicly_verified"] },
	],
	official_site: [
		{ label: "确认缺口", states: ["gap_confirmed"] },
		{ label: "确认方案", states: ["change_proposed", "awaiting_brand_legal_review"] },
		{ label: "上线修改", states: ["handed_to_web_owner", "deployed"] },
		{ label: "核验完成", states: ["same_domain_readback_verified"] },
	],
	structured_data: [
		{ label: "确认缺口", states: ["schema_gap_confirmed"] },
		{ label: "确认方案", states: ["jsonld_proposed", "awaiting_technical_review"] },
		{ label: "上线数据", states: ["deployed", "source_readback_verified"] },
		{ label: "校验完成", states: ["schema_validated"] },
	],
	third_party_source: [
		{ label: "选择信源", states: ["source_selected"] },
		{ label: "准备合作", states: ["cooperation_briefed"] },
		{ label: "执行上线", states: ["external_execution", "external_content_live"] },
		{ label: "核验完成", states: ["public_readback_verified"] },
	],
	analysis: [
		{ label: "确认范围", states: ["scope_confirmed"] },
		{ label: "执行分析", states: ["analysis_in_progress"] },
		{ label: "审核结论", states: ["awaiting_analysis_review"] },
		{ label: "完成留证", states: ["analysis_verified"] },
	],
};

const statusLabel: Record<string, string> = {
	target_selected: "确定平台",
	variant_generating: "生成适配稿",
	awaiting_fact_review: "事实审核",
	awaiting_platform_review: "平台审核",
	draft_ready: "平台稿已审核",
	draft_write_requested: "写入草稿",
	draft_link_returned: "草稿待确认",
	draft_saved: "草稿已回读",
	awaiting_human_publish: "等待人工发布",
	publicly_verified: "公开页已核验",
	gap_confirmed: "确认页面缺口",
	change_proposed: "形成修改建议",
	awaiting_brand_legal_review: "品牌/法务审核",
	handed_to_web_owner: "交给网站负责人",
	deployed: "已上线",
	same_domain_readback_verified: "同域回读完成",
	schema_gap_confirmed: "确认 Schema 缺口",
	jsonld_proposed: "生成 JSON-LD",
	awaiting_technical_review: "技术审核",
	source_readback_verified: "源码回读完成",
	schema_validated: "Schema 校验通过",
	source_selected: "确定目标信源",
	cooperation_briefed: "合作简报完成",
	external_execution: "外部执行中",
	external_content_live: "内容已公开",
	public_readback_verified: "公网回读完成",
	scope_confirmed: "确认分析范围",
	analysis_in_progress: "开始分析",
	awaiting_analysis_review: "审核分析结论",
	analysis_verified: "分析结论已留证",
};

const approvalTypeByStatus: Record<string, string> = {
	awaiting_fact_review: "fact",
	awaiting_platform_review: "platform_draft",
	awaiting_brand_legal_review: "brand_legal",
	awaiting_technical_review: "technical",
	awaiting_analysis_review: "analysis",
};

const requiredEvidenceByAction: Record<string, string[]> = {
	article: ["public_url"],
	official_site: ["same_domain_readback"],
	structured_data: ["source_code", "schema_validation"],
	third_party_source: ["external_publication"],
	analysis: ["analysis_report"],
};

const targetLogoByPlatform: Record<string, string> = {
	zhihu: "/brand/zhihu.svg",
	juejin: "https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/static/favicons/favicon-32x32.png",
	csdn: "https://g.csdnimg.cn/static/logo/favicon32.ico",
	"51cto": "https://blog.51cto.com/favicon.ico",
	wechat: "/brand/wechat.svg",
};

function targetLogo(actionType: string, platformKey?: string | null, targetRef?: string | null) {
	if (actionType === "official_site") return "/brand/spring-yuan-workspace.svg";
	if (platformKey && targetLogoByPlatform[platformKey.toLowerCase()]) return targetLogoByPlatform[platformKey.toLowerCase()];
	const reference = String(targetRef || "").toLowerCase();
	if (reference.includes("zhihu.com") || reference === "zhihu") return targetLogoByPlatform.zhihu;
	if (reference.includes("juejin.cn") || reference === "juejin") return targetLogoByPlatform.juejin;
	if (reference.includes("csdn.net") || reference === "csdn") return targetLogoByPlatform.csdn;
	if (reference.includes("51cto.com") || reference === "51cto") return targetLogoByPlatform["51cto"];
	if (reference.includes("mp.weixin.qq.com") || reference === "wechat") return targetLogoByPlatform.wechat;
	return null;
}

const viewLabel: Record<ActionExecutionView, string> = {
	all: "全部行动",
	mine: "我的行动",
	approvals: "待我审批",
	overdue_blocked: "逾期与阻塞",
};

function localDate(value?: string | null) {
	if (!value) return "未设置";
	const date = new Date(value);
	return Number.isNaN(date.getTime()) ? "未设置" : new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}

function memberName(members: WorkspaceMembership[], userId?: number | null) {
	return members.find((item) => item.user_id === userId)?.user.name || (userId ? `成员 #${userId}` : "待分配");
}

function nextTargetStatus(action: ActionExecutionDetail, status: string) {
	const states = workflow[action.action_type] || [];
	const index = states.indexOf(status);
	return index >= 0 ? states[index + 1] || null : null;
}

function nextActionLabel(value: string) {
	return statusLabel[value] || value;
}

function actionProgressLabel(action: ActionExecutionDetail) {
	const phases = visibleWorkflow[action.action_type] || [];
	const activeTarget = action.targets.find((target) => nextTargetStatus(action, target.delivery_status)) || action.targets[0];
	if (!activeTarget) return nextActionLabel(action.next_action);
	return phases.find((phase) => phase.states.includes(activeTarget.delivery_status))?.label || nextActionLabel(action.next_action);
}

const targetCtaLabel: Record<string, string> = {
	variant_generating: "开始准备内容",
	awaiting_fact_review: "内容已就绪，提交确认",
	draft_ready: "打开 GEO 文章助手",
	draft_write_requested: "写入平台草稿",
	draft_link_returned: "打开并确认草稿",
	draft_saved: "确认草稿已写入",
	awaiting_human_publish: "进入人工发布",
	change_proposed: "准备修改方案",
	handed_to_web_owner: "交付官网负责人",
	deployed: "确认已上线",
	jsonld_proposed: "准备结构化数据",
	source_readback_verified: "回读上线源码",
	cooperation_briefed: "准备合作方案",
	external_execution: "开始外部执行",
	external_content_live: "确认内容已上线",
	analysis_in_progress: "开始分析",
	awaiting_analysis_review: "提交分析结论",
};

function dueInput(days = 3) {
	const date = new Date(Date.now() + days * 86400000);
	date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
	return date.toISOString().slice(0, 16);
}

export function ActionCommandCenter({ workspaceId, initialActions, initialSelectedActionId, initialShowLegacy = false, viewActionIds, members, initialDistributionRuns, legacyWorkbench, onAccept, onTransition, onSubmitEvidence, onRequestApproval, onDecideApproval, onSelfApprove, onConfirmDraftReadback, onBlock, onUnblock, onRetest }: Props) {
	const router = useRouter();
	const [actions, setActions] = useState(initialActions);
	const [distributionRuns, setDistributionRuns] = useState(initialDistributionRuns);
	const initialSelectedIndex = initialActions.findIndex((action) => action.id === initialSelectedActionId);
	const [selectedId, setSelectedId] = useState(initialSelectedIndex >= 0 ? initialActions[initialSelectedIndex].id : initialActions[0]?.id ?? 0);
	const [page, setPage] = useState(initialSelectedIndex >= 0 ? Math.floor(initialSelectedIndex / ACTIONS_PER_PAGE) + 1 : 1);
	const [view, setView] = useState<ActionExecutionView>("all");
	const [showLegacy, setShowLegacy] = useState(initialShowLegacy);
	const [message, setMessage] = useState("");
	const [isPending, startTransition] = useTransition();
	const [assigneeId, setAssigneeId] = useState(members.find((member) => member.role !== "viewer")?.user_id ?? 0);
	const teamReviewers = members.filter((member) => ["owner", "admin", "reviewer"].includes(member.role));
	const [reviewerId, setReviewerId] = useState(teamReviewers[0]?.user_id ?? 0);
	const [dueAt, setDueAt] = useState(dueInput(5));
	const [approvalDueAt, setApprovalDueAt] = useState(dueInput(1));
	const [sourceUrls, setSourceUrls] = useState<Record<number, string>>({});
	const [blockNote, setBlockNote] = useState("");
	const [selectedRetestTargets, setSelectedRetestTargets] = useState<number[]>([]);

	useEffect(() => setActions(initialActions), [initialActions]);
	useEffect(() => setDistributionRuns(initialDistributionRuns), [initialDistributionRuns]);

	const filteredActions = useMemo(() => {
		const allowedIds = new Set(viewActionIds[view]);
		return actions.filter((action) => allowedIds.has(action.id));
	}, [actions, view, viewActionIds]);
	const pageCount = Math.max(1, Math.ceil(filteredActions.length / ACTIONS_PER_PAGE));
	const currentPage = Math.min(page, pageCount);
	const pageStart = (currentPage - 1) * ACTIONS_PER_PAGE;
	const visibleActions = filteredActions.slice(pageStart, pageStart + ACTIONS_PER_PAGE);
	const selected = filteredActions.find((action) => action.id === selectedId) || filteredActions[0] || null;

	function changeView(nextView: ActionExecutionView) {
		const allowedIds = new Set(viewActionIds[nextView]);
		const firstVisibleAction = actions.find((action) => allowedIds.has(action.id));
		setView(nextView);
		setPage(1);
		setSelectedId((current) => allowedIds.has(current) ? current : firstVisibleAction?.id ?? 0);
		setSelectedRetestTargets([]);
		setMessage("");
	}

	function selectAction(actionId: number) {
		setSelectedId(actionId);
		setSelectedRetestTargets([]);
		setMessage("");
		const url = new URL(window.location.href);
		url.searchParams.set("action_id", String(actionId));
		window.history.replaceState(window.history.state, "", url.toString());
	}

	function updateAction(next: ActionExecutionDetail) {
		setActions((current) => current.map((item) => item.id === next.id ? next : item));
		setSelectedId(next.id);
	}

	function run(task: () => Promise<ActionExecutionDetail>, success: string) {
		setMessage("");
		startTransition(async () => {
			try {
				const next = await task();
				updateAction(next);
				setMessage(success);
				router.refresh();
			} catch (error) {
				setMessage(error instanceof Error ? error.message : "操作未完成，请稍后重试");
			}
		});
	}

	function confirmDraft(runId: number, targetId: number, platformName: string) {
		setMessage("");
		startTransition(async () => {
			try {
				const next = await onConfirmDraftReadback(runId, targetId);
				setDistributionRuns((current) => [next, ...current.filter((item) => item.id !== next.id)]);
				setMessage(`${platformName}草稿已确认可见，请在平台完成人工发布。`);
				router.refresh();
			} catch (error) {
				setMessage(error instanceof Error ? error.message : "草稿确认失败，请重试");
			}
		});
	}

	function openLegacyForAction(actionId: number) {
		const url = new URL(window.location.href);
		url.searchParams.set("action_id", String(actionId));
		url.searchParams.set("mode", "legacy");
		window.location.assign(url.toString());
	}

	function toggleRetestTarget(targetId: number) {
		setSelectedRetestTargets((current) => current.includes(targetId) ? current.filter((id) => id !== targetId) : [...current, targetId]);
	}

	return <main className={styles.shell}>
		<header className={styles.pageHeader}>
			<div><p>企业执行工作台</p><h1>优化行动</h1><span>每项工作都有人负责、有截止、有证据，也能单独复测。</span></div>
			<button type="button" className={styles.secondaryButton} onClick={() => setShowLegacy((value) => !value)}>{showLegacy ? "返回行动总览" : "打开原执行工作台"}</button>
		</header>
		<GeoGlobalScopeBar workspaceId={workspaceId} support="single-batch" />
		{showLegacy ? <section className={styles.legacy}>{legacyWorkbench}</section> : <>
			<nav className={styles.viewTabs} aria-label="行动视图">
				{(Object.keys(viewLabel) as ActionExecutionView[]).map((key) => <button key={key} type="button" className={view === key ? styles.activeTab : ""} onClick={() => changeView(key)}>{viewLabel[key]}<span>{viewActionIds[key].length}</span></button>)}
			</nav>
			<div className={styles.workspace}>
				<section className={styles.actionList} aria-label="行动列表">
					<header><strong>{filteredActions.length} 个行动</strong><small>按真实执行状态排列</small></header>
					{filteredActions.length ? visibleActions.map((action) => {
						const meta = typeMeta[action.action_type] || typeMeta.legacy_unclassified;
						return <button type="button" key={action.id} className={`${styles.actionCard} ${styles[meta.tone]} ${selected?.id === action.id ? styles.selectedCard : ""}`} onClick={() => selectAction(action.id)}>
							<i><ActionTypeGlyph type={action.action_type} /></i><div><span><b>{meta.label}</b><em>{action.stage === "blocked" ? "已阻塞" : action.is_overdue ? "已逾期" : actionProgressLabel(action)}</em></span><h2>{action.title}</h2><p><strong>{memberName(members, action.assignee_user_id)}</strong><span>截止 {localDate(action.due_at)}</span><span>目标 {action.completed_target_count}/{action.targets.length}</span></p>{action.blocked_note ? <small>阻塞：{action.blocked_note}</small> : null}</div><mark>›</mark>
						</button>;
					}) : <div className={styles.empty}><b>当前视图没有行动</b><span>切换其它视图即可查看完整工作。</span></div>}
					{filteredActions.length > ACTIONS_PER_PAGE ? <nav className={styles.pagination} aria-label="行动列表分页">
						<span>{pageStart + 1}–{Math.min(pageStart + ACTIONS_PER_PAGE, filteredActions.length)} / {filteredActions.length}</span>
						<div>
							<button type="button" aria-label="上一页" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>‹</button>
							{Array.from({ length: pageCount }, (_, index) => index + 1).map((pageNumber) => <button key={pageNumber} type="button" aria-label={`第 ${pageNumber} 页`} aria-current={currentPage === pageNumber ? "page" : undefined} className={currentPage === pageNumber ? styles.currentPage : ""} onClick={() => setPage(pageNumber)}>{pageNumber}</button>)}
							<button type="button" aria-label="下一页" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>›</button>
						</div>
					</nav> : null}
				</section>

				{selected ? <section className={styles.detail}>
					<header className={styles.detailHeader}><div><p>{typeMeta[selected.action_type]?.label || "优化行动"}<span>{selected.stage === "blocked" ? "已阻塞" : selected.is_overdue ? "已逾期" : actionProgressLabel(selected)}</span></p><h2>{selected.title}</h2><div><b>{memberName(members, selected.assignee_user_id)}</b><span>截止 {localDate(selected.due_at)}</span><span>{selected.affected_question_ids.length} 个问题</span><span>{selected.affected_model_keys.length} 个模型</span></div></div><div className={styles.score}><small>已完成目标</small><strong>{selected.completed_target_count}<i>/{selected.targets.length}</i></strong></div></header>

					{!selected.assignee_user_id || !selected.due_at ? <section className={styles.setupCard}><div><b>先明确负责人和交付时间</b><span>{members.some((member) => member.role !== "viewer") ? "这两项确定后，行动才正式进入企业执行。" : "当前工作区还没有可承接行动的成员。"}{!members.some((member) => member.role !== "viewer") ? <a href={`/geo/${workspaceId}/settings`}>去管理中添加成员</a> : null}</span></div>{members.some((member) => member.role !== "viewer") ? <><label>负责人<select value={assigneeId} onChange={(event) => setAssigneeId(Number(event.target.value))}>{members.filter((member) => member.role !== "viewer").map((member) => <option key={member.id} value={member.user_id}>{member.user.name}</option>)}</select></label><label>截止时间<input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label><button type="button" disabled={isPending || !assigneeId || !dueAt} onClick={() => run(() => onAccept(selected.id, assigneeId, new Date(dueAt).toISOString()), "行动已进入执行")}>接受行动</button></> : null}</section> : null}

					<section className={styles.workflowCard}><header><div><b>交付进度</b><span>每个目标独立推进，已完成的目标不再等待其它目标。</span></div>{selected.stage === "blocked" ? <button type="button" onClick={() => run(() => onUnblock(selected.id), "阻塞已解除")}>解除阻塞</button> : <button type="button" onClick={() => setBlockNote((value) => value || "等待外部协作")}>记录阻塞</button>}</header>
						{blockNote && selected.stage !== "blocked" ? <div className={styles.inlineForm}><input value={blockNote} onChange={(event) => setBlockNote(event.target.value)} placeholder="说明卡在哪里" /><button type="button" disabled={isPending || !blockNote.trim()} onClick={() => run(() => onBlock(selected.id, blockNote.trim()), "阻塞已记录")}>确认</button><button type="button" onClick={() => setBlockNote("")}>取消</button></div> : null}
						<div className={styles.targetTable}>
							{selected.targets.map((target) => {
								const states = workflow[selected.action_type] || [];
								const phases = visibleWorkflow[selected.action_type] || [];
								const currentPhaseIndex = phases.findIndex((phase) => phase.states.includes(target.delivery_status));
								const next = nextTargetStatus(selected, target.delivery_status);
								const approvalType = approvalTypeByStatus[target.delivery_status];
								const approval = selected.approvals.find((item) => item.target_id === target.id && item.approval_type === approvalType && item.status === "pending");
								const approved = selected.approvals.some((item) => item.target_id === target.id && item.approval_type === approvalType && item.status === "approved");
								const finalStep = next && states.indexOf(next) === states.length - 1;
								const verifiedEvidenceTypes = new Set(selected.evidence.filter((item) => item.target_id === target.id && item.verification_status === "verified").map((item) => item.evidence_type));
								const evidenceReady = (requiredEvidenceByAction[selected.action_type] || []).every((evidenceType) => verifiedEvidenceTypes.has(evidenceType));
								const logo = targetLogo(selected.action_type, target.platform_key, target.target_ref);
								const distributionMatch = distributionRuns
									.filter((run) => run.action_id === selected.id)
									.sort((a, b) => b.id - a.id)
									.flatMap((run) => run.targets.map((distributionTarget) => ({ run, target: distributionTarget })))
									.find((item) => item.target.platform_key === target.platform_key);
								const confirmedDraftUrl = distributionMatch?.target.draft_url || null;
								const candidateDraftUrl = distributionMatch?.target.candidate_draft_url || null;
								const sourceUrl = sourceUrls[target.id] || "";
								const isArticle = selected.action_type === "article";
								const preparingArticle = ["target_selected", "variant_generating"].includes(target.delivery_status);
								const reviewingArticle = ["awaiting_fact_review", "awaiting_platform_review"].includes(target.delivery_status);
								return <article key={target.id} className={styles.targetRow}>
									<div className={styles.targetIdentity}><i>{logo ? <img src={logo} alt={`${target.display_name}标志`} /> : <ActionTypeGlyph type={selected.action_type} />}</i><span><b>{target.display_name}</b><small>{target.target_ref}</small></span></div>
									<div className={styles.steps} aria-label={`${target.display_name}流程`}>
										{phases.map((phase, index) => {
											const completed = index < currentPhaseIndex || (index === currentPhaseIndex && !next);
											const current = index === currentPhaseIndex && !completed;
											return <span key={phase.label} className={completed ? styles.doneStep : current ? styles.currentStep : ""} title={phase.label}><i>{completed ? "✓" : index + 1}</i><small>{phase.label}</small></span>;
										})}
									</div>
									<div className={styles.targetAction}>
										{!isArticle && approval && <><span className={styles.pendingTag}>等待 {memberName(members, approval.reviewer_user_id)} 审批</span><div><button type="button" onClick={() => run(() => onDecideApproval(selected.id, approval.id, "approved"), "审批已通过")}>通过</button><button type="button" onClick={() => run(() => onDecideApproval(selected.id, approval.id, "changes_requested"), "已退回修改")}>退回</button></div></>}
										{!isArticle && approvalType && !approval && !approved ? <div className={styles.approvalChoice}>
											<button type="button" className={styles.primaryButton} disabled={isPending} onClick={() => run(() => onSelfApprove(selected.id, target.id), "已由当前账号确认，行动继续推进")}>由我确认并继续</button>
											{teamReviewers.length ? <details className={styles.teamApproval}><summary>交给团队审批</summary><div className={styles.compactForm}><label>审批人<select aria-label="审批人" value={reviewerId} onChange={(event) => setReviewerId(Number(event.target.value))}>{teamReviewers.map((member) => <option key={member.id} value={member.user_id}>{member.user.name}</option>)}</select></label><label>审批截止时间<input aria-label="审批截止时间" type="datetime-local" value={approvalDueAt} onChange={(event) => setApprovalDueAt(event.target.value)} /></label><button type="button" disabled={isPending || !reviewerId || !approvalDueAt} onClick={() => run(() => onRequestApproval(selected.id, target.id, reviewerId, new Date(approvalDueAt).toISOString()), "已交给团队审批")}>发送审批</button></div></details> : <span className={styles.teamFuture}>团队审批 · 接入企业微信后可用</span>}
										</div> : null}
										{isArticle && preparingArticle ? <div className={styles.draftPublishFlow}><button type="button" className={styles.primaryButton} onClick={() => openLegacyForAction(selected.id)}>{target.delivery_status === "target_selected" ? "去生成平台稿" : "查看内容生成进度"}</button><small className={styles.draftNote}>{target.status_note}</small></div> : null}
										{isArticle && reviewingArticle ? <div className={styles.draftPublishFlow}><button type="button" className={styles.primaryButton} onClick={() => openLegacyForAction(selected.id)}>去审核内容</button><small className={styles.draftNote}>{target.status_note}</small></div> : null}
										{isArticle && target.delivery_status === "draft_ready" ? <div className={styles.draftPublishFlow}><button type="button" className={styles.primaryButton} onClick={() => openLegacyForAction(selected.id)}>打开 GEO 文章助手</button><small className={styles.draftNote}>{target.status_note}</small></div> : null}
										{isArticle && target.delivery_status === "draft_write_requested" ? <div className={styles.draftPublishFlow}><button type="button" onClick={() => openLegacyForAction(selected.id)}>查看草稿写入结果</button><small className={styles.draftNote}>{target.status_note}</small></div> : null}
										{isArticle && target.delivery_status === "draft_link_returned" && candidateDraftUrl && distributionMatch ? <div className={styles.draftPublishFlow}><a className={styles.draftLink} href={candidateDraftUrl} target="_blank" rel="noopener noreferrer">打开{target.display_name}草稿核对 <span aria-hidden="true">↗</span></a><button type="button" disabled={isPending} onClick={() => confirmDraft(distributionMatch.run.id, distributionMatch.target.id, target.display_name)}>我已打开，确认正文可见</button><small className={styles.draftNote}>{target.status_note}</small></div> : null}
										{isArticle && ["draft_saved", "awaiting_human_publish"].includes(target.delivery_status) ? <div className={styles.draftPublishFlow}>{confirmedDraftUrl ? <a className={styles.draftLink} href={confirmedDraftUrl} target="_blank" rel="noopener noreferrer">打开{target.display_name}草稿并人工发布 <span aria-hidden="true">↗</span></a> : <button type="button" onClick={() => openLegacyForAction(selected.id)}>查看草稿回读</button>}<details className={styles.publicationDetails}><summary>我已在平台发布</summary><div className={styles.compactForm}><input type="url" aria-label={`${target.display_name}公开文章地址`} value={sourceUrl} onChange={(event) => setSourceUrls((current) => ({ ...current, [target.id]: event.target.value }))} placeholder="粘贴发布后的公开文章地址" /><button type="button" disabled={!sourceUrl.trim()} onClick={() => run(() => onSubmitEvidence(selected.id, target.id, sourceUrl.trim()), "公开文章已核验，该平台目标已完成")}>核验并完成</button></div></details><small className={styles.draftNote}>{target.status_note}</small></div> : null}
										{finalStep && !evidenceReady && selected.action_type !== "article" && (!approvalType || approved) ? <div className={styles.compactForm}><input value={sourceUrl} onChange={(event) => setSourceUrls((current) => ({ ...current, [target.id]: event.target.value }))} placeholder={selected.action_type === "analysis" ? "填写分析结论（至少 20 字）" : "粘贴已上线的公开地址"} /><button type="button" disabled={selected.action_type === "analysis" ? sourceUrl.trim().length < 20 : !sourceUrl.trim()} onClick={() => run(() => onSubmitEvidence(selected.id, target.id, sourceUrl.trim()), selected.action_type === "analysis" ? "分析结论已留证，行动已完成" : "所需完成证据已全部核验，可以推进最终状态")}>{selected.action_type === "analysis" ? "记录结论" : "核验全部证据"}</button></div> : null}
										{!isArticle && next && (!approvalType || approved) && (!finalStep || evidenceReady) ? <button type="button" className={styles.primaryButton} onClick={() => run(() => onTransition(selected.id, target.id, next), `已进入：${statusLabel[next]}`)}>{targetCtaLabel[next] || `继续到“${statusLabel[next]}”`}</button> : null}
										{!next ? <span className={styles.completeTag}>✓ 已完成并留证</span> : null}
									</div>
								</article>;
							})}
						</div>
					</section>

					<section className={styles.retestCard}><div><p><b>局部复测</b><span>只测已经完成并有核验证据的目标，无需等待全部交付。</span></p><div className={styles.eligibleTargets}>{selected.targets.filter((target) => selected.eligible_target_ids.includes(target.id)).map((target) => <label key={target.id}><input type="checkbox" checked={selectedRetestTargets.includes(target.id)} onChange={() => toggleRetestTarget(target.id)} /><span>✓ {target.display_name}</span></label>)}{!selected.eligible_target_ids.length ? <small>暂无可复测目标</small> : null}</div></div><button type="button" className={styles.primaryButton} disabled={isPending || !selectedRetestTargets.length} onClick={() => run(() => onRetest(selected.id, selectedRetestTargets), "局部复测已创建")}>复测所选目标</button></section>
					{message ? <div className={styles.feedback} role="status">{message}</div> : null}
				</section> : <section className={styles.detail}><div className={styles.empty}><b>还没有优化行动</b><span>先从洞察中选择一个真实机会。</span></div></section>}
			</div>
		</>}
	</main>;
}
