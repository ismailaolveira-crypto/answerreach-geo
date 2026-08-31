import { randomUUID } from "node:crypto";
import Link from "next/link";
import type { Route } from "next";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import {
	confirmGeoBusinessMetricImport,
	createGeoBusinessMetric,
	getGeoBusinessMetricImport,
	getGeoBusinessMetricImports,
	getGeoResultsOverview,
	preflightGeoBusinessMetricCsv,
	reverseGeoBusinessMetric,
	reverseGeoBusinessMetricImport,
	type GeoResultsOverview,
} from "@/lib/cleanroom-v1-api";
import { BrandLogo } from "@/components/brand-logo";
import styles from "./results.module.css";
import { RoiPanel } from "./roi-panel";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";

type PageProps = {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const moneyMetrics = new Set(["content_cost", "labor_cost", "distribution_cost", "tool_cost", "pipeline_value", "won_revenue"]);

function first(value: string | string[] | undefined) {
	return Array.isArray(value) ? value[0] : value;
}

function statusTone(status: string) {
	if (status === "stable_improvement" || status === "history_up") return styles.positive;
	if (status === "observed_improvement") return styles.signal;
	if (status === "regressed" || status === "history_down") return styles.negative;
	return styles.neutral;
}

type EffectAction = GeoResultsOverview["effect"]["actions"][number];

function modelBrand(modelKey: string) {
	const value = modelKey.toLowerCase();
	if (value.includes("qianwen") || value.includes("qwen") || value.includes("千问")) return "qwen";
	if (value.includes("glm") || value.includes("智谱")) return "glm";
	if (value.includes("deepseek")) return "deepseek";
	if (value.includes("doubao") || value.includes("豆包")) return "doubao";
	if (value.includes("kimi")) return "kimi";
	if (value.includes("yuanbao") || value.includes("hunyuan") || value.includes("元宝")) return "yuanbao";
	return "";
}

function modelLabel(modelKey: string) {
	return ({ qwen: "通义千问", qianwen: "通义千问", glm: "智谱 GLM", deepseek: "DeepSeek", doubao: "豆包", kimi: "Kimi", yuanbao: "腾讯元宝", hunyuan: "腾讯元宝" } as Record<string, string>)[modelBrand(modelKey)] ?? "AI 模型";
}

function ActionInsight({ action, workspaceId }: { action: EffectAction; workspaceId: string }) {
	const signal = action.historical_signal;
	const beforeRate = signal?.before_total ? Math.round((Number(signal.before_positive || 0) / signal.before_total) * 100) : null;
	const afterRate = signal?.after_total ? Math.round((Number(signal.after_positive || 0) / signal.after_total) * 100) : null;
	const delta = signal?.delta_percentage_points ?? null;
	const directionWord = delta == null ? "暂无可比变化" : delta > 0 ? `上升 ${Math.abs(delta).toFixed(0)} 个百分点` : delta < 0 ? `下降 ${Math.abs(delta).toFixed(0)} 个百分点` : "暂时没有变化";
	const summary = beforeRate == null || afterRate == null
		? "历史样本还不够，先创建一次同口径复测，才能判断这项优化有没有效果。"
		: `品牌在相关回答中的出现率，从历史参考的 ${beforeRate}% 变为最近的 ${afterRate}%，${directionWord}。这是一条历史信号，还不能归因给本次优化。`;
	return <div className={styles.actionDetail}>
		<div className={styles.glassGlow}/>
		<header className={styles.insightSummary}>
			<span className={delta != null && delta < 0 ? styles.summaryWarning : styles.summaryInfo}>{delta != null && delta < 0 ? "!" : "i"}</span>
			<div><small>一句话看懂</small><p>{summary}</p></div>
			<em>历史参考 ≠ 行动效果</em>
		</header>
		<div className={styles.comparisonFlow}>
			<article className={styles.metricGlass}>
				<small>历史参考</small><strong>{beforeRate == null ? "—" : `${beforeRate}%`}</strong><span>{signal?.before_total ? `${signal.before_positive}/${signal.before_total} 次回答出现品牌` : "暂无完整样本"}</span><i>批次 #{signal?.first_batch_id ?? "—"}</i>
			</article>
			<div className={styles.flowArrow}><b>{delta == null ? "→" : delta < 0 ? "↘" : delta > 0 ? "↗" : "→"}</b><span>{directionWord}</span></div>
			<article className={styles.metricGlass}>
				<small>最近观测</small><strong>{afterRate == null ? "—" : `${afterRate}%`}</strong><span>{signal?.after_total ? `${signal.after_positive}/${signal.after_total} 次回答出现品牌` : "暂无完整样本"}</span><i>批次 #{signal?.latest_batch_id ?? "—"}</i>
			</article>
		</div>
		<section className={styles.modelGlass}>
			<div><small>模型方向</small><p>图标下方只表示历史变化方向</p></div>
			<div className={styles.modelLogoRow}>{signal?.model_directions?.length ? signal.model_directions.map((model) => {
				const brand = modelBrand(model.model_key);
				const label = modelLabel(model.model_key);
				const directionLabel = model.direction === "up" ? "改善" : model.direction === "down" ? "回落" : "持平";
				return <div key={model.model_key} className={`${styles.modelDirection} ${statusTone(model.direction === "up" ? "history_up" : model.direction === "down" ? "history_down" : "history_flat")}`} title={`${label}：${directionLabel}`} aria-label={`${label}：${directionLabel}`}>
					{brand ? <BrandLogo brand={brand} label={label} className={styles.modelLogo}/> : <span className={styles.modelFallback}>AI</span>}
					<span>{model.direction === "up" ? "↗" : model.direction === "down" ? "↘" : "—"} {directionLabel}</span>
				</div>;
			}) : <span className={styles.noModels}>暂无可比模型</span>}</div>
		</section>
		<aside className={styles.nextStepGlass}>
			<div><small>下一步</small><strong>{action.outcome.comparable_rounds ? `已完成 ${action.outcome.comparable_rounds} 轮复测` : "创建同口径复测"}</strong><p>固定同一个问题、模型和提问次数，才能判断优化是否有效。</p></div>
			<div><Link className={styles.retestAction} href={`/geo/${workspaceId}/actions?action_id=${action.action_id}` as Route}>{action.outcome.comparable_rounds ? "继续复测" : "开始复测"} →</Link><Link className={styles.evidenceAction} href={`/geo/${workspaceId}/actions?action_id=${action.action_id}` as Route}>查看证据</Link></div>
		</aside>
	</div>;
}

function HistoricalChart({ historical }: { historical: GeoResultsOverview["effect"]["historical"] }) {
	const points = historical.series;
	if (points.length < 2) return <div className={styles.chartEmpty}><span>⌁</span><strong>当前筛选下历史观测不足</strong><p>换一个时间、模型或问题范围查看。</p></div>;
	const x = (index: number) => 58 + index * (884 / Math.max(points.length - 1, 1));
	const y = (value: number) => 194 - Math.max(0, Math.min(100, value)) * 1.48;
	const polyline = (key: "mention_rate" | "impact_score" | "high_value_rate") => points.map((point, index) => `${x(index)},${y(point[key])}`).join(" ");
	const markerIndexes = [...new Set([0, Math.floor((points.length - 1) / 3), Math.floor((points.length - 1) * 2 / 3), points.length - 1])];
	return <div className={styles.historyChart}>
		<div className={styles.chartLegend}><span><i className={styles.legendBlue}/>目标问题可见度</span><span><i className={styles.legendPurple}/>综合影响分</span><span><i className={styles.legendCyan}/>推荐 / 引用占比</span><em>均来自真实历史批次</em></div>
		<svg viewBox="0 0 1000 250" role="img" aria-label="目标问题历史观测趋势">
			{[0,25,50,75,100].map((tick) => <g key={tick}><line x1="58" x2="942" y1={y(tick)} y2={y(tick)} className={styles.gridLine}/><text x="44" y={y(tick)+4} textAnchor="end" className={styles.axisText}>{tick}%</text></g>)}
			<polyline points={polyline("mention_rate")} className={styles.historyBlue}/>
			<polyline points={polyline("impact_score")} className={styles.historyPurple}/>
			<polyline points={polyline("high_value_rate")} className={styles.historyCyan}/>
			{markerIndexes.map((index) => { const point = points[index]; return <g key={point.batch_id}><line x1={x(index)} x2={x(index)} y1="32" y2="204" className={styles.markerLine}/><rect x={x(index)-38} y="5" width="76" height="22" rx="5" className={styles.markerTag}/><text x={x(index)} y="20" textAnchor="middle" className={styles.markerText}>批次 #{point.batch_id}</text><circle cx={x(index)} cy={y(point.mention_rate)} r="4" className={styles.bluePoint}/><text x={x(index)} y="228" textAnchor="middle" className={styles.axisText}>{new Intl.DateTimeFormat("zh-CN",{month:"numeric",day:"numeric"}).format(new Date(point.captured_at))}</text></g>; })}
		</svg>
	</div>;
}

export default async function ResultsPage({ params, searchParams }: PageProps) {
	const [{ workspaceId }, query] = await Promise.all([params, searchParams]);
	const rangeDays = String(first(query.range) || "").replace("d", "");
	const periodDays = [7, 30, 90, 365].includes(Number(rangeDays)) ? Number(rangeDays) : [30, 90, 365].includes(Number(first(query.period))) ? Number(first(query.period)) : 30;
	const modelKeys = [...new Set((Array.isArray(query.model) ? query.model : query.model ? [query.model] : []).filter((value) => value && value !== "all"))];
	const rawQuestions = Array.isArray(query.question) ? query.question : String(first(query.question) || "").split(",");
	const questionPlanIds = [...new Set(rawQuestions.map((value) => Number(value)).filter((value) => Number.isInteger(value) && value > 0))];
	const batchIds = [...new Set((Array.isArray(query.batch) ? query.batch : query.batch ? [query.batch] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0))];
	const roiActionIds = [...new Set((Array.isArray(query.roi_action) ? query.roi_action : query.roi_action ? [query.roi_action] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0))];
	const roiRecordOpen = first(query.record) === "1";
	const tab = first(query.tab) === "roi" ? "roi" : "effect";
	const roiImportOpen = first(query.import) === "1";
	const importBatchId = Number(first(query.import_batch)) > 0 ? Number(first(query.import_batch)) : null;
	const data = await getGeoResultsOverview(workspaceId, { period_days: periodDays, model_keys: modelKeys, batch_ids: batchIds, question_plan_ids: questionPlanIds, roi_action_ids: roiActionIds });
	const [roiImportBatches, roiImportBatch] = tab === "roi"
		? await Promise.all([
			getGeoBusinessMetricImports(workspaceId),
			importBatchId ? getGeoBusinessMetricImport(workspaceId, importBatchId) : Promise.resolve(null),
		])
		: [[], null];
	const requestedAction = Number(first(query.action));
	const selected = data.effect.actions.find((item) => item.action_id === requestedAction) ?? data.effect.actions.find((item) => item.outcome.status !== "not_measured") ?? data.effect.actions[0];
	const message = first(query.message);
	const showAll = first(query.show) === "all";
	const visibleActions = showAll ? data.effect.actions : data.effect.actions.slice(0, 4);
	const history = data.effect.historical;
	const latestHistory = history.series.at(-1);
	const peakHistory = history.series.reduce((best, point) => !best || point.mention_rate > best.mention_rate ? point : best, undefined as typeof latestHistory);
	const fellFromPeak = Boolean(latestHistory && peakHistory && latestHistory.mention_rate < peakHistory.mention_rate - 5);
	const historyHeadline = fellFromPeak ? "历史可见度冲高后回落" : (history.change_percentage_points ?? 0) > 0 ? "历史可见度总体上升" : (history.change_percentage_points ?? 0) < 0 ? "历史可见度总体回落" : "历史可见度整体持平";
	const headlineDelta = fellFromPeak && latestHistory && peakHistory ? latestHistory.mention_rate - peakHistory.mention_rate : history.change_percentage_points;
	const headlineDeltaLabel = fellFromPeak ? "当前较所选历史峰值" : "当前较所选历史首批";
	const scopeParams = new URLSearchParams();
	for (const key of ["range", "from", "to", "batch", "model", "question"] as const) {
		const raw = query[key];
		for (const value of Array.isArray(raw) ? raw : raw ? [raw] : []) scopeParams.append(key, value);
	}
	const listParams = new URLSearchParams(scopeParams);
	if (selected?.action_id) listParams.set("action", String(selected.action_id));
	listParams.set("show", showAll ? "summary" : "all");
	const showAllHref = `/geo/${workspaceId}/results?${listParams.toString()}#action-results` as Route;
	const roiReturnParams = new URLSearchParams(scopeParams);
	roiReturnParams.set("tab", "roi");
	for (const actionId of roiActionIds) roiReturnParams.append("roi_action", String(actionId));
	const roiReturnHref = `/geo/${workspaceId}/results?${roiReturnParams.toString()}`;
	const effectParams = new URLSearchParams(scopeParams);
	const roiTabParams = new URLSearchParams(scopeParams);
	roiTabParams.set("tab", "roi");
	const effectHref = `/geo/${workspaceId}/results${effectParams.size ? `?${effectParams.toString()}` : ""}` as Route;
	const roiTabHref = `/geo/${workspaceId}/results?${roiTabParams.toString()}` as Route;

	async function recordMetric(formData: FormData) {
		"use server";
		const metricType = String(formData.get("metric_type") || "");
		const rawValue = String(formData.get("value") || "").trim();
		const isMoney = moneyMetrics.has(metricType);
		const isCost = metricType.endsWith("_cost");
		const attribution = isCost ? "not_applicable" : String(formData.get("attribution_type") || "unallocated");
		const date = String(formData.get("occurred_at") || "");
		try {
			await createGeoBusinessMetric(workspaceId, {
				action_id: Number(formData.get("action_id")) || null,
				metric_type: metricType as Parameters<typeof createGeoBusinessMetric>[1]["metric_type"],
				amount: isMoney ? rawValue : null,
				quantity: isMoney ? null : Number(rawValue),
				currency: isMoney ? String(formData.get("currency") || "CNY") : null,
				attribution_type: attribution as Parameters<typeof createGeoBusinessMetric>[1]["attribution_type"],
				source_type: String(formData.get("source_type") || "manual") as Parameters<typeof createGeoBusinessMetric>[1]["source_type"],
				source_label: String(formData.get("source_label") || "").trim(),
				source_reference: String(formData.get("source_reference") || "").trim() || null,
				evidence_note: String(formData.get("evidence_note") || "").trim(),
				occurred_at: new Date(`${date}T12:00:00+08:00`).toISOString(),
				idempotency_key: String(formData.get("idempotency_key") || randomUUID()),
			});
		} catch (error) {
			const text = error instanceof Error ? error.message : "记录失败";
			redirect(`${roiReturnHref}&message=${encodeURIComponent(text)}` as Route);
		}
		revalidatePath(`/geo/${workspaceId}/results`);
		redirect(`${roiReturnHref}&message=${encodeURIComponent("真实业务记录已写入")}` as Route);
	}

	async function reverseMetric(formData: FormData) {
		"use server";
		const entryId = Number(formData.get("entry_id"));
		try {
			await reverseGeoBusinessMetric(workspaceId, entryId, {
				reason: String(formData.get("reason") || "").trim(),
				idempotency_key: String(formData.get("idempotency_key") || randomUUID()),
			});
		} catch (error) {
			const text = error instanceof Error ? error.message : "冲销失败";
			redirect(`${roiReturnHref}&message=${encodeURIComponent(text)}` as Route);
		}
		revalidatePath(`/geo/${workspaceId}/results`);
		redirect(`${roiReturnHref}&message=${encodeURIComponent("原记录已保留，并新增冲销记录")}` as Route);
	}

	async function preflightImport(formData: FormData) {
		"use server";
		const file = formData.get("file");
		if (!(file instanceof File) || !file.name.toLowerCase().endsWith(".csv") || file.size === 0) {
			redirect(`${roiReturnHref}&import=1&message=${encodeURIComponent("请选择一个有内容的 CSV 文件")}` as Route);
		}
		let batchId: number;
		try {
			const batch = await preflightGeoBusinessMetricCsv(workspaceId, {
				file_name: file.name,
				csv_text: await file.text(),
			});
			batchId = batch.id;
		} catch (error) {
			const text = error instanceof Error ? error.message : "CSV 预检失败";
			redirect(`${roiReturnHref}&import=1&message=${encodeURIComponent(text)}` as Route);
		}
		redirect(`${roiReturnHref}&import_batch=${batchId}` as Route);
	}

	async function confirmImport(formData: FormData) {
		"use server";
		const batchId = Number(formData.get("batch_id"));
		try {
			await confirmGeoBusinessMetricImport(workspaceId, batchId);
		} catch (error) {
			const text = error instanceof Error ? error.message : "导入失败";
			redirect(`${roiReturnHref}&import_batch=${batchId}&message=${encodeURIComponent(text)}` as Route);
		}
		revalidatePath(`/geo/${workspaceId}/results`);
		redirect(`${roiReturnHref}&message=${encodeURIComponent("有效记录已导入 ROI 账本")}` as Route);
	}

	async function reverseImport(formData: FormData) {
		"use server";
		const batchId = Number(formData.get("batch_id"));
		try {
			await reverseGeoBusinessMetricImport(workspaceId, batchId, String(formData.get("reason") || "CSV 批次数据撤销").trim());
		} catch (error) {
			const text = error instanceof Error ? error.message : "撤销失败";
			redirect(`${roiReturnHref}&import_batch=${batchId}&message=${encodeURIComponent(text)}` as Route);
		}
		revalidatePath(`/geo/${workspaceId}/results`);
		redirect(`${roiReturnHref}&message=${encodeURIComponent("原数据已保留，该导入批次已生成冲销记录")}` as Route);
	}

	return <main className={styles.page}>
		<header className={styles.hero}>
			<div><h1>效果与 ROI</h1>{tab === "effect" ? <span>把每次优化行动与后续变化对应起来</span> : null}</div>
		</header>
		<GeoGlobalScopeBar workspaceId={workspaceId} />
		<div className={styles.toolbar}><nav className={styles.tabs} aria-label="效果与 ROI 视图"><Link href={effectHref} className={tab === "effect" ? styles.activeTab : ""}>优化效果</Link><Link href={roiTabHref} className={tab === "roi" ? styles.activeTab : ""}>业务 ROI</Link></nav></div>

		{message ? <div className={styles.message}>{message}</div> : null}
		{tab === "effect" ? <>
			<section className={styles.conclusion}><div><small>本期结论 · 历史观测参考</small><h2>{historyHeadline}</h2><p>{history.signal_counts.history_down ?? 0} 个行动对应问题历史回落 · {history.signal_counts.history_flat ?? 0} 个持平 · 行动复测仍待启动</p></div><div className={styles.conclusionMetric}><span className={headlineDelta && headlineDelta < 0 ? styles.negativeMetric : ""}>⌁ {headlineDelta == null ? "—" : `${headlineDelta > 0 ? "+" : ""}${headlineDelta.toFixed(1)}pp`}</span><small>{headlineDeltaLabel}</small></div></section>
			<section className={styles.focusGrid}><div className={styles.panel}><div className={styles.panelHead}><div><h2>目标问题可见度趋势</h2><p>真实历史观测；模型、问题或重复次数可能不同</p></div><span className={styles.historyBadge}>历史数据</span></div><HistoricalChart historical={history}/></div><aside className={styles.confidencePanel}><h2>数据可信度</h2><div className={styles.confidenceValue}>中</div><ul><li><i>✓</i><span>真实模型联网证据</span></li><li><i>✓</i><span>{history.complete_batch_count} / {history.batch_count} 个批次样本完整</span></li><li><i>✓</i><span>原始答案与来源可回读</span></li><li className={styles.caution}><i>!</i><span>批次口径并不完全一致</span></li></ul><p>{history.warning}</p></aside></section>
				{data.effect.actions.length ? <section id="action-results" className={styles.actionSection}>
					<div className={styles.sectionHead}><div><h2>行动效果</h2><small>{questionPlanIds.length ? `当前显示所选 ${questionPlanIds.length} 个问题对应的优化行动` : "可多选问题范围，只看这些问题对应的行动"}</small></div><span>{data.effect.actions.length} 个行动</span></div>
					<div className={styles.actionTable}>
						<div className={styles.tableHeader}><span>#</span><span>优化行动</span><span>效果评估</span><span>目标问题可见度（变化）</span><span>可信度 / 状态</span><span>复测计划</span></div>
						{visibleActions.map((action,index) => {
							const signal=action.historical_signal;
							const measured=action.outcome.status!=="not_measured";
							const displayStatus=measured?action.outcome.status:(signal?.status??"no_history");
							const displayLabel=measured?action.outcome.label:(signal?.label??"暂无历史观测");
							const directionIcon=displayStatus==="history_down"||displayStatus==="regressed"?"↘":displayStatus==="history_flat"||displayStatus==="no_clear_change"?"—":"↗";
							return <details key={action.action_id} name="effect-action" className={styles.actionGroup} open={selected?.action_id===action.action_id}>
								<summary><span>{index+1}</span><span><b>{action.title}</b><small>{action.question??"未绑定问题"}</small></span><span className={statusTone(displayStatus)}>{directionIcon} {displayLabel}</span><span>{signal?.before_total?`${signal.before_positive}/${signal.before_total} → ${signal.after_positive}/${signal.after_total}`:"—"}</span><span><em className={signal?.scope_quality==="same_scope"?styles.trustGood:styles.trustReference}>{measured?action.outcome.confidence_label:(signal?.scope_label??"待验证")}</em></span><span>{measured?`${action.outcome.comparable_rounds} 轮完成`:"待创建"}<b className={styles.rowChevron}>⌄</b></span></summary>
								<ActionInsight action={action} workspaceId={workspaceId}/>
							</details>;
						})}
					</div>
					{data.effect.actions.length>4?<Link className={styles.showAll} href={showAllHref}>{showAll?"收起行动":"查看全部行动"}</Link>:null}
				</section>:null}
		</> : <RoiPanel workspaceId={workspaceId} data={data.roi} periodDays={periodDays} selectedActionIds={roiActionIds} baseScopeQuery={scopeParams.toString()} recordOpen={roiRecordOpen} importOpen={roiImportOpen} importBatch={roiImportBatch} importBatches={roiImportBatches} recordMetric={recordMetric} reverseMetric={reverseMetric} preflightImport={preflightImport} confirmImport={confirmImport} reverseImport={reverseImport}/>}
	</main>;
}
