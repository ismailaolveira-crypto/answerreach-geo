import Link from "next/link";
import type { Route } from "next";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";
import {
	getCleanroomActions,
	getGeoBusinessGoal,
	getGeoResultsOverview,
	getWorkspaceMembers,
	upsertGeoBusinessGoal,
	type CleanroomAction,
	type GeoBusinessGoal,
} from "@/lib/cleanroom-v1-api";
import styles from "./business-dashboard.module.css";

type DashboardQuery = {
	range?: string;
	batch?: string | string[];
	model?: string | string[];
	question?: string | string[];
	goal?: string;
	notice?: string;
};

type Props = {
	workspaceId: string;
	query: DashboardQuery;
};

type GoalView = Omit<GeoBusinessGoal, "id" | "workspace_id" | "created_at" | "updated_at"> & {
	id?: number;
	workspace_id?: number;
	created_at?: string;
	updated_at?: string;
	isSuggested: boolean;
};

function values(value: string | string[] | undefined) {
	return (Array.isArray(value) ? value : value ? [value] : []).filter(Boolean);
}

function ids(value: string | string[] | undefined) {
	return values(value).map(Number).filter((item) => Number.isInteger(item) && item > 0);
}

function periodDays(range?: string) {
	const days = Number(String(range ?? "30d").replace("d", ""));
	return [7, 30, 90, 365].includes(days) ? days : 30;
}

function asDate(value: Date | string) {
	const date = typeof value === "string" ? new Date(value) : value;
	return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}

function dateInput(value: Date | string) {
	const date = typeof value === "string" ? new Date(value) : value;
	return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function number(value: number | null | undefined, suffix = "%") {
	return value == null ? "—" : `${value.toFixed(1)}${suffix}`;
}

function money(minor: number, currency?: string | null) {
	if (!minor) return "—";
	return new Intl.NumberFormat("zh-CN", {
		style: "currency",
		currency: currency || "CNY",
		maximumFractionDigits: 0,
	}).format(minor / 100);
}

function queryHref(workspaceId: string, query: DashboardQuery, overrides: Record<string, string | null>) {
	const params = new URLSearchParams();
	for (const key of ["range", "batch", "model", "question"] as const) {
		for (const value of values(query[key])) params.append(key, value);
	}
	for (const [key, value] of Object.entries(overrides)) {
		params.delete(key);
		if (value) params.set(key, value);
	}
	return `/geo/${workspaceId}${params.size ? `?${params}` : ""}` as Route;
}

function actionState(action: CleanroomAction) {
	if (action.blocked_reason || action.stage === "blocked" || action.status === "blocked") {
		return { label: "阻塞中", tone: "blocked" as const };
	}
	if (["verified", "completed", "closed"].includes(action.stage || action.status)) {
		return { label: "已验证", tone: "done" as const };
	}
	return { label: "执行中", tone: "active" as const };
}

function addDays(date: Date, days: number) {
	const next = new Date(date);
	next.setDate(next.getDate() + days);
	return next;
}

function suggestedTarget(current: number | null) {
	if (current == null) return 25;
	return Math.min(100, Math.max(5, Math.ceil((current + 5) / 5) * 5));
}

function suggestedGoal(
	series: Array<{ shortlist_rate: number; captured_at: string }>,
	members: Awaited<ReturnType<typeof getWorkspaceMembers>>,
	query: DashboardQuery,
	actions: CleanroomAction[],
): GoalView {
	const baseline = series[0]?.shortlist_rate ?? null;
	const current = series.at(-1)?.shortlist_rate ?? null;
	const target = suggestedTarget(current);
	const span = baseline == null ? null : target - baseline;
	const progress = current == null || baseline == null || span == null || span <= 0
		? null
		: Math.max(0, Math.min(100, (current - baseline) / span * 100));
	return {
		title: "90 天提升核心采购问题的候选进入率",
		metric_key: "shortlist_rate",
		metric_label: "候选进入率",
		baseline_value: baseline,
		current_value: current,
		target_value: target,
		progress_percent: progress == null ? null : Math.round(progress * 10) / 10,
		remaining_value: current == null ? null : Math.max(0, target - current),
		start_at: series[0]?.captured_at ?? new Date().toISOString(),
		due_at: addDays(new Date(), 90).toISOString(),
		owner_user_id: members[0]?.user_id ?? null,
		owner_name: members[0]?.user.name ?? null,
		status: "active",
		question_plan_ids: ids(query.question),
		model_keys: values(query.model),
		action_ids: actions.map((action) => action.id),
		scope_snapshot: {
			period_days: periodDays(query.range),
			batch_ids: ids(query.batch),
			model_keys: values(query.model),
			question_plan_ids: ids(query.question),
			metric_contract: "evidence-gated-shortlist-rate/v1",
		},
		isSuggested: true,
	};
}

function GoalFlag() {
	return <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M9 26V6m0 2h13l-2.7 4L22 16H9" /></svg>;
}

export async function BusinessDashboard({ workspaceId, query }: Props) {
	const filters = {
		period_days: periodDays(query.range),
		model_keys: values(query.model),
		batch_ids: ids(query.batch),
		question_plan_ids: ids(query.question),
	};
	const [overview, actions, members, persistedGoal] = await Promise.all([
		getGeoResultsOverview(workspaceId, filters),
		getCleanroomActions(workspaceId),
		getWorkspaceMembers(workspaceId),
		getGeoBusinessGoal(workspaceId),
	]);
	const series = overview.effect.historical.series;
	const goal: GoalView = persistedGoal
		? { ...persistedGoal, isSuggested: false }
		: suggestedGoal(series, members, query, actions);
	const scopedActions = (goal.action_ids.length ? actions.filter((action) => goal.action_ids.includes(action.id)) : actions)
		.filter((action) => !goal.question_plan_ids.length || !action.question_plan_id || goal.question_plan_ids.includes(action.question_plan_id));
	const actionCounts = scopedActions.reduce((acc, action) => {
		acc[actionState(action).tone] += 1;
		return acc;
	}, { done: 0, active: 0, blocked: 0 });
	const relevantActions = [...scopedActions].sort((a, b) => {
		const order = { blocked: 0, active: 1, done: 2 };
		return order[actionState(a).tone] - order[actionState(b).tone];
	}).slice(0, 2);
	const nextAction = scopedActions.find((action) => actionState(action).tone === "blocked")
		?? scopedActions.find((action) => actionState(action).tone === "active")
		?? scopedActions[0];
	const nextStep = nextAction
		? actionState(nextAction).tone === "blocked"
			? `先处理「${nextAction.title}」的阻塞，再继续验证目标`
			: `继续推进「${nextAction.title}」，完成后按同口径复测`
		: "从当前洞察创建第一项优化行动，再用同口径复测验证结果";
	const now = new Date();
	const due = new Date(goal.due_at);
	const daysLeft = Math.max(0, Math.ceil((due.getTime() - now.getTime()) / 86_400_000));
	const atRisk = goal.progress_percent != null && daysLeft < 30 && goal.progress_percent < 70;
	const delta = goal.current_value == null || goal.baseline_value == null ? null : goal.current_value - goal.baseline_value;
	const editorOpen = query.goal === "edit";

	async function saveGoal(formData: FormData) {
		"use server";
		const target = Number(formData.get("target_value"));
		const dueDate = String(formData.get("due_at") || "");
		const owner = Number(formData.get("owner_user_id"));
		await upsertGeoBusinessGoal(workspaceId, {
			title: String(formData.get("title") || "").trim(),
			metric_key: "shortlist_rate",
			target_value: target,
			due_at: `${dueDate}T23:59:00+08:00`,
			owner_user_id: Number.isInteger(owner) && owner > 0 ? owner : null,
			question_plan_ids: formData.getAll("question_plan_ids").map(Number).filter(Number.isInteger),
			model_keys: formData.getAll("model_keys").map(String),
			action_ids: formData.getAll("action_ids").map(Number).filter(Number.isInteger),
			period_days: Number(formData.get("period_days")) || 30,
			batch_ids: formData.getAll("batch_ids").map(Number).filter(Number.isInteger),
		});
		revalidatePath(`/geo/${workspaceId}`);
		redirect(queryHref(workspaceId, query, { goal: null, notice: "goal-saved" }));
	}

	return <main className={styles.page}>
		<header className={styles.heading}>
			<div><h1>经营驾驶舱</h1><p>把观测、行动和结果统一到一个明确目标</p></div>
		</header>
		<GeoGlobalScopeBar workspaceId={workspaceId} />
		{query.notice === "goal-saved" ? <div className={styles.saved} role="status">经营目标已保存，完成度已按真实观测重新计算。</div> : null}

		<section className={styles.hero} aria-labelledby="operating-goal-title">
			<div className={styles.heroHead}>
				<div>
					<small>{goal.isSuggested ? "建议经营目标" : "当前经营目标"}</small>
					<h2 id="operating-goal-title">{goal.title}</h2>
					<div className={styles.meta}>
						<span>负责人 <b>{goal.owner_name || "待设置"}</b></span><i />
						<span>截止 {asDate(goal.due_at)}</span><i /><span>剩余 {daysLeft} 天</span>
					</div>
				</div>
				<span className={`${styles.risk} ${atRisk ? styles.atRisk : ""}`}>{atRisk ? "存在风险" : goal.isSuggested ? "待确认" : "进度正常"}</span>
			</div>
			<div className={styles.heroMetrics}>
				<div className={styles.progressMetric}>
					<strong>{goal.progress_percent == null ? "—" : `${Math.round(goal.progress_percent)}%`}</strong>
					<div className={styles.progressTrack}><i style={{ width: `${goal.progress_percent ?? 0}%` }} /></div>
					<small>目标完成进度</small>
				</div>
				<div className={styles.metricFlow}>
					<span><small>基线</small><b>{number(goal.baseline_value)}</b></span><i>→</i>
					<span className={styles.current}><small>当前</small><b>{number(goal.current_value)}</b></span><i>→</i>
					<span><small>目标</small><b>{number(goal.target_value)}</b></span>
				</div>
				<div className={styles.delta}>
					<span>较基线 <b>{delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`}</b> 个百分点</span>
					<span>距离目标还差 <b>{goal.remaining_value == null ? "—" : goal.remaining_value.toFixed(1)}</b> 个百分点</span>
				</div>
			</div>
			<footer className={styles.heroFooter}>
				<div><span>{goal.question_plan_ids.length || filters.question_plan_ids.length} 个核心问题</span><span>{goal.model_keys.length || filters.model_keys.length} 个模型</span><span>范围已冻结</span></div>
				<div><Link className={styles.primary} href={queryHref(workspaceId, query, { goal: "edit" })}>查看目标详情 <b>›</b></Link><Link href={queryHref(workspaceId, query, { goal: "edit" })}>{goal.isSuggested ? "设置目标" : "调整目标"}</Link></div>
			</footer>
		</section>

		<section className={styles.dashboardGrid}>
			<article className={styles.card}>
				<h3>目标进展</h3>
				<div className={styles.miniTrend}>
					<svg viewBox="0 0 310 86" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="goal-line" x1="0" x2="1"><stop stopColor="#39c8ef"/><stop offset=".52" stopColor="#5b65ff"/><stop offset="1" stopColor="#c474f2"/></linearGradient></defs><path d="M18 67 L145 48 L286 20"/><circle cx="18" cy="67" r="7"/><circle cx="145" cy="48" r="8"/><circle className={styles.targetDot} cx="286" cy="20" r="7"/></svg>
					<div><span><b>基线</b>{number(goal.baseline_value)}<small>{asDate(goal.start_at)}</small></span><span><b>当前</b>{number(goal.current_value)}<small>{series.at(-1) ? asDate(series.at(-1)!.captured_at) : "暂无观测"}</small></span><span><b>目标</b>{number(goal.target_value)}<small>{asDate(goal.due_at)}</small></span></div>
				</div>
			</article>
			<article className={styles.card}>
				<header><h3>关联行动</h3><Link href={`/geo/${workspaceId}/actions` as Route}>›</Link></header>
				<p className={styles.actionSummary}>{scopedActions.length} 个行动　·　{actionCounts.done} 个已验证　·　{actionCounts.active} 个执行中　·　{actionCounts.blocked} 个阻塞</p>
				<div className={styles.actionList}>{relevantActions.length ? relevantActions.map((action) => {
					const state = actionState(action);
					return <Link key={action.id} href={`/geo/${workspaceId}/actions?action=${action.id}` as Route}><span>▤</span><div><b>{action.title}</b><small>{action.question_plan_id ? `问题 #${action.question_plan_id}` : "跨问题行动"}</small></div><em data-tone={state.tone}>{state.label}</em><i>›</i></Link>;
				}) : <p className={styles.empty}>当前目标还没有关联行动。</p>}</div>
			</article>
			<article className={styles.card}>
				<header><h3>投入与回报</h3><Link href={`/geo/${workspaceId}/results?tab=roi` as Route}>查看明细</Link></header>
				<div className={styles.roiGrid}>
					<span><small>已投入</small><b>{money(overview.roi.total_cost_minor, overview.roi.currency)}</b></span>
					<span><small>可归因收入</small><b>{money(overview.roi.direct_revenue_minor, overview.roi.currency)}</b></span>
					<span><small>ROI</small><b className={styles.roiValue}>{overview.roi.roi_percent == null ? "—" : `${overview.roi.roi_percent.toFixed(1)}%`}</b></span>
				</div>
				<p className={styles.roiNote}>{overview.roi.status_label} · 只计算已确认且可回读的业务记录</p>
			</article>
		</section>

		<section className={styles.island} aria-label="本周最重要的下一步">
			<span className={styles.flag}><GoalFlag /></span><div><small>本周最重要的下一步</small><b>{nextStep}</b></div><Link href={`/geo/${workspaceId}/actions${nextAction ? `?action=${nextAction.id}` : ""}` as Route}>查看行动 <span>›</span></Link>
		</section>

		{editorOpen ? <div className={styles.editorLayer} role="dialog" aria-modal="true" aria-labelledby="goal-editor-title">
			<Link className={styles.scrim} href={queryHref(workspaceId, query, { goal: null })} aria-label="关闭目标设置" />
			<section className={styles.editor} id="goal-editor">
				<header><div><small>经营目标</small><h2 id="goal-editor-title">{goal.isSuggested ? "确认第一个经营目标" : "调整经营目标"}</h2><p>保存后以当前范围的第一轮真实观测作为基线，后续自动更新完成度。</p></div><Link href={queryHref(workspaceId, query, { goal: null })} aria-label="关闭">×</Link></header>
				<form action={saveGoal}>
					<label className={styles.wide}><span>目标名称</span><input name="title" defaultValue={goal.title} required minLength={4} maxLength={255}/></label>
					<label><span>目标候选进入率</span><input name="target_value" type="number" min="0.1" max="100" step="0.1" defaultValue={goal.target_value} required/></label>
					<label><span>截止日期</span><input name="due_at" type="date" min={dateInput(addDays(new Date(), 1))} defaultValue={dateInput(goal.due_at)} required/></label>
					<label className={styles.wide}><span>负责人</span><select name="owner_user_id" defaultValue={goal.owner_user_id ?? ""}><option value="">暂不指定</option>{members.map((member) => <option key={member.id} value={member.user_id}>{member.user.name} · {member.role}</option>)}</select></label>
					<fieldset className={styles.wide}><legend>关联行动</legend>{actions.map((action) => <label key={action.id}><input name="action_ids" type="checkbox" value={action.id} defaultChecked={!goal.action_ids.length || goal.action_ids.includes(action.id)}/><span>{action.title}</span></label>)}</fieldset>
					<input type="hidden" name="period_days" value={filters.period_days}/>{filters.batch_ids.map((id) => <input key={`batch-${id}`} type="hidden" name="batch_ids" value={id}/>)}{filters.model_keys.map((key) => <input key={`model-${key}`} type="hidden" name="model_keys" value={key}/>)}{filters.question_plan_ids.map((id) => <input key={`question-${id}`} type="hidden" name="question_plan_ids" value={id}/>)}
					<footer className={styles.wide}><Link href={queryHref(workspaceId, query, { goal: null })}>取消</Link><button type="submit">保存目标</button></footer>
				</form>
			</section>
		</div> : null}
	</main>;
}
