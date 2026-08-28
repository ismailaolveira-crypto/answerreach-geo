import Link from "next/link";
import type { Route } from "next";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { BrandLogo } from "@/components/brand-logo";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";
import {
	convertChangeAlertToAction,
	createObservationSchedule,
	getObservationAlertCenter,
	getQuestionLibrary,
	runObservationSchedule,
	updateChangeAlertStatus,
	updateObservationScheduleStatus,
	type GeoChangeAlert,
} from "@/lib/cleanroom-v1-api";
import { getLLMProviders } from "@/lib/geo-provider-api";
import styles from "./alerts.module.css";

type Props = {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const alertTypeLabels: Record<string, string> = {
	"brand.visibility_drop": "品牌可见度下降",
	"competitor.overtake": "竞品反超",
	"source.weight_shift": "重要信源变化",
	"model.failure_rate": "模型观测异常",
	"observation.incomplete": "样本不完整",
};

function first(value: string | string[] | undefined) {
	return Array.isArray(value) ? value[0] : value;
}

function providerBrand(provider: { provider_type: string; model_name: string; name: string; cost_rule: Record<string, unknown> }) {
	const value = `${String(provider.cost_rule.platform_key ?? "")} ${provider.provider_type} ${provider.model_name} ${provider.name}`.toLowerCase();
	if (value.includes("deepseek")) return "deepseek";
	if (value.includes("qwen") || value.includes("qianwen")) return "qwen";
	if (value.includes("doubao")) return "doubao";
	if (value.includes("glm")) return "glm";
	if (value.includes("kimi")) return "kimi";
	if (value.includes("hunyuan") || value.includes("yuanbao")) return "yuanbao";
	return "";
}

function formatTime(value?: string | null) {
	if (!value) return "尚未运行";
	return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function percent(value: unknown) {
	return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function AlertMetric({ alert }: { alert: GeoChangeAlert }) {
	const before = alert.metric_snapshot.baseline;
	const current = alert.metric_snapshot.current;
	const delta = alert.metric_snapshot.delta;
	if (typeof before === "number" && typeof current === "number") {
		return <div className={styles.metricFlow}><span><small>基准</small><b>{percent(before)}</b></span><i>→</i><span><small>当前</small><b>{percent(current)}</b></span><em>{typeof delta === "number" ? `${delta > 0 ? "+" : ""}${Math.round(delta * 100)}pp` : ""}</em></div>;
	}
	if (typeof alert.metric_snapshot.failure_rate === "number") return <strong className={styles.singleMetric}>异常占比 {percent(alert.metric_snapshot.failure_rate)}</strong>;
	return <strong className={styles.singleMetric}>{alert.summary}</strong>;
}

export default async function ObservationAlertsPage({ params, searchParams }: Props) {
	const [{ workspaceId }, query] = await Promise.all([params, searchParams]);
	const [center, questionLibrary, providers] = await Promise.all([
		getObservationAlertCenter(workspaceId),
		getQuestionLibrary(workspaceId),
		getLLMProviders(),
	]);
	const usableQuestions = questionLibrary.questions.filter((item) => item.active && ["approved", "active"].includes(item.status));
	const usableProviders = providers.filter((item) => item.status === "active");
	const requestedAlert = Number(first(query.alert));
	const selected = center.alerts.find((item) => item.id === requestedAlert) ?? center.alerts[0] ?? null;
	const alertFilter = first(query.filter) ?? "all";
	const visibleAlerts = center.alerts.filter((item) => alertFilter === "all" || (alertFilter === "critical" ? item.severity === "critical" : item.alert_type === "observation.incomplete"));

	async function createScheduleAction(formData: FormData) {
		"use server";
		const providerIds = formData.getAll("provider_id").map(Number).filter(Boolean);
		const questionIds = formData.getAll("question_id").map(Number).filter(Boolean);
		await createObservationSchedule(workspaceId, {
			name: String(formData.get("name") || "定时 GEO 观测"),
			cadence: String(formData.get("cadence") || "daily") as "daily" | "weekly" | "custom",
			weekdays: formData.getAll("weekday").map(Number),
			local_time: String(formData.get("local_time") || "09:00"),
			timezone_name: "Asia/Shanghai",
			provider_ids: providerIds,
			question_plan_ids: questionIds,
			repeat_count: Number(formData.get("repeat_count") || 2),
		});
		revalidatePath(`/geo/${workspaceId}/alerts`);
		redirect(`/geo/${workspaceId}/alerts` as Route);
	}

	async function alertStatusAction(formData: FormData) {
		"use server";
		await updateChangeAlertStatus(workspaceId, Number(formData.get("alert_id")), String(formData.get("status")) as "confirmed" | "ignored");
		revalidatePath(`/geo/${workspaceId}/alerts`);
	}

	async function convertAlertAction(formData: FormData) {
		"use server";
		const result = await convertChangeAlertToAction(workspaceId, Number(formData.get("alert_id")));
		revalidatePath(`/geo/${workspaceId}/alerts`);
		redirect(`/geo/${workspaceId}/actions?action_id=${result.action_id}` as Route);
	}

	async function scheduleAction(formData: FormData) {
		"use server";
		const scheduleId = Number(formData.get("schedule_id"));
		const intent = String(formData.get("intent"));
		if (intent === "run") await runObservationSchedule(workspaceId, scheduleId);
		else await updateObservationScheduleStatus(workspaceId, scheduleId, intent as "active" | "paused");
		revalidatePath(`/geo/${workspaceId}/alerts`);
	}

	return <main className={styles.page}>
		<header className={styles.hero}><div><h1>观测与告警</h1><p>固定同一范围持续观测，变化出现时直接定位到证据。</p></div><details className={styles.createPanel}><summary className="geo-alert-create-summary">新建观测计划</summary><form action={createScheduleAction}>
			<label><span>计划名称</span><input name="name" defaultValue="品牌健康每日观测" required /></label>
			<div className={styles.formGrid}><label><span>频率</span><select name="cadence"><option value="daily">每天</option><option value="weekly">每周</option><option value="custom">指定星期</option></select></label><label><span>运行时间</span><input name="local_time" type="time" defaultValue="09:00" required /></label><label><span>重复次数</span><select name="repeat_count" defaultValue="2"><option value="1">1 次</option><option value="2">2 次</option><option value="3">3 次</option><option value="5">5 次</option></select></label></div>
			<fieldset><legend>模型范围</legend>{usableProviders.map((provider) => { const brand = providerBrand(provider); return <label key={provider.id}><input type="checkbox" name="provider_id" value={provider.id} defaultChecked={usableProviders.indexOf(provider) < 3} />{brand ? <BrandLogo brand={brand} label={provider.name} className={styles.formLogo} /> : <i>AI</i>}<span>{provider.name}</span></label>; })}</fieldset>
			<fieldset><legend>问题范围</legend>{usableQuestions.slice(0, 12).map((question, index) => <label key={question.id}><input type="checkbox" name="question_id" value={question.id} defaultChecked={index < 5} /><span>{question.question_text}</span></label>)}</fieldset>
			<div className={styles.weekdays}>{["一","二","三","四","五","六","日"].map((day,index)=><label key={day}><input type="checkbox" name="weekday" value={index}/><span>周{day}</span></label>)}</div>
			<button type="submit">保存观测计划</button>
		</form></details></header>
		<GeoGlobalScopeBar workspaceId={workspaceId} />
		<section className={`${styles.stats} geo-alert-stats`}>
			<article><i>⌁</i><span>运行中的计划</span><strong>{center.summary.active_schedules}</strong></article>
			<article><i>◎</i><span>今日观测</span><strong>{center.summary.today_runs}</strong></article>
			<article className={center.summary.open_alerts ? styles.riskStat : ""}><i>!</i><span>待处理告警</span><strong>{center.summary.open_alerts}</strong></article>
			<article><i>✓</i><span>数据完整度</span><strong>{center.summary.data_completeness == null ? "—" : percent(center.summary.data_completeness)}</strong></article>
		</section>
		<section className={styles.alertWorkspace}>
			<div className={styles.alertList}><header><h2>变化告警</h2><nav><Link className={alertFilter === "all" ? styles.activeFilter : ""} href={`/geo/${workspaceId}/alerts?filter=all` as Route}>全部 {center.alerts.length}</Link><Link className={alertFilter === "critical" ? styles.activeFilter : ""} href={`/geo/${workspaceId}/alerts?filter=critical` as Route}>严重 {center.alerts.filter((item)=>item.severity === "critical").length}</Link><Link className={alertFilter === "anomaly" ? styles.activeFilter : ""} href={`/geo/${workspaceId}/alerts?filter=anomaly` as Route}>观察异常 {center.alerts.filter((item)=>item.alert_type === "observation.incomplete").length}</Link></nav></header>
				{visibleAlerts.length ? visibleAlerts.map((alert) => <Link key={alert.id} href={`/geo/${workspaceId}/alerts?filter=${alertFilter}&alert=${alert.id}` as Route} className={`${styles.alertRow} ${selected?.id === alert.id ? styles.selectedAlert : ""} ${styles[alert.severity]}`}>
					<span className={styles.alertIcon}>{alert.severity === "critical" ? "!" : alert.severity === "warning" ? "△" : "◎"}</span><div><small>{alertTypeLabels[alert.alert_type] ?? alert.title}</small><b>{alert.summary}</b><em>批次 #{alert.baseline_batch_id ?? "—"} → #{alert.current_batch_id ?? "—"}</em></div><span className={styles.rowScope}>{Number(alert.completeness.current_eligible || 0)} / {Number(alert.completeness.expected || 0)} 样本<br/><time>{formatTime(alert.created_at)}</time></span><i className={styles.rowStatus}>{alert.status === "open" ? "待确认" : alert.status === "confirmed" ? "已确认" : "已忽略"}</i>
				</Link>) : <div className={styles.empty}><b>当前没有符合条件的告警</b><span>真实变化出现后会在这里留下可回查记录。</span></div>}
			</div>
			<aside className={styles.alertDetail}>{selected ? <><header><span className={styles[selected.severity]}>{selected.severity === "critical" ? "严重" : selected.severity === "warning" ? "注意" : "变化"}</span><small>{alertTypeLabels[selected.alert_type] ?? "变化告警"}</small></header><h2>{selected.title}</h2><p>{selected.summary}</p><AlertMetric alert={selected}/><dl><div><dt>证据范围</dt><dd>{((selected.scope_snapshot.question_plan_ids as number[] | undefined)?.length ?? 0)} 个问题 · {((selected.scope_snapshot.provider_ids as number[] | undefined)?.length ?? 0)} 个模型 · 重复 {Number(selected.scope_snapshot.repeat_count || 0)} 次</dd></div><div><dt>样本完整度</dt><dd>{Number(selected.completeness.current_eligible || 0)} / {Number(selected.completeness.expected || 0)}</dd></div><div><dt>关联批次</dt><dd>#{selected.baseline_batch_id ?? "—"} → #{selected.current_batch_id ?? "—"}</dd></div><div><dt>原始证据</dt><dd>{selected.evidence_ids.length} 条可回查</dd></div></dl><div className={styles.detailActions}>{selected.status === "open" ? <><form action={alertStatusAction}><input type="hidden" name="alert_id" value={selected.id}/><input type="hidden" name="status" value="confirmed"/><button>确认告警</button></form><form action={alertStatusAction}><input type="hidden" name="alert_id" value={selected.id}/><input type="hidden" name="status" value="ignored"/><button className={styles.secondary}>忽略</button></form></> : <span className={styles.doneState}>{selected.status === "confirmed" ? "已确认" : "已忽略"}</span>}<form action={convertAlertAction}><input type="hidden" name="alert_id" value={selected.id}/><button className={styles.secondary}>{selected.converted_action_id ? "查看优化行动" : "转为优化行动"}</button></form></div></> : <div className={styles.empty}><b>暂无变化告警</b><span>观测计划完成两轮同范围采样后，才会判断变化。</span></div>}</aside>
		</section>
		<section className={styles.schedules}><header><div><h2>观测计划</h2><p>问题、模型和重复次数会冻结为范围快照。</p></div><span>{center.schedules.length} 个计划</span></header><div className={styles.scheduleRail}>{center.schedules.length ? center.schedules.map((schedule) => <article key={schedule.id}><header><b>{schedule.name}</b><span className={schedule.status === "active" ? styles.on : styles.off}>{schedule.status === "active" ? "运行中" : "已暂停"}</span></header><div className={styles.scheduleMeta}><span>{schedule.cadence === "daily" ? "每天" : schedule.cadence === "weekly" ? "每周" : "自定义"}</span><span>UTC+08:00</span><span>范围 v{schedule.scope_version}</span></div><p>{schedule.question_plan_ids.length} 个问题 · {schedule.provider_ids.length} 个模型 · 重复 {schedule.repeat_count} 次</p><small>下次运行 {formatTime(schedule.next_run_at)}</small><form action={scheduleAction}><input type="hidden" name="schedule_id" value={schedule.id}/><button name="intent" value="run">立即观测</button><button className={styles.textButton} name="intent" value={schedule.status === "active" ? "paused" : "active"}>{schedule.status === "active" ? "暂停" : "启用"}</button></form></article>) : <div className={styles.empty}><b>还没有观测计划</b><span>新建后会按固定范围生成真实观测批次。</span></div>}</div></section>
		<section className={styles.runs}><header><h2>最近运行</h2><span>每次运行都保留独立回执</span></header><div className={styles.tableWrap}><table><thead><tr><th>计划</th><th>执行窗口</th><th>批次</th><th>状态</th><th>基准批次</th><th>说明</th></tr></thead><tbody>{center.runs.length ? center.runs.map((run) => { const schedule=center.schedules.find((item)=>item.id===run.schedule_id); return <tr key={run.id}><td>{schedule?.name ?? `计划 #${run.schedule_id}`}</td><td>{formatTime(run.scheduled_for)}</td><td>{run.batch_id ? <Link href={`/geo/${workspaceId}/batches/${run.batch_id}` as Route}>#{run.batch_id}</Link> : "—"}</td><td><span className={styles.runStatus}>{run.status === "evaluated" ? "已完成" : run.status === "running" ? "观测中" : run.status === "dispatching" ? "正在分发" : run.status === "failed" ? "失败" : "排队中"}</span></td><td>{run.baseline_batch_id ? `#${run.baseline_batch_id}` : "首次观测"}</td><td>{run.failure_reason ?? "范围和证据已归档"}</td></tr>; }) : <tr><td colSpan={6}>暂无运行记录</td></tr>}</tbody></table></div></section>
	</main>;
}
