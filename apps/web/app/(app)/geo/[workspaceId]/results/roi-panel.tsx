import { randomUUID } from "node:crypto";
import Link from "next/link";
import type { Route } from "next";

import type { GeoBusinessMetricImportBatch, GeoResultsOverview } from "@/lib/cleanroom-v1-api";
import styles from "./results.module.css";

type RoiData = GeoResultsOverview["roi"];
type FormAction = (formData: FormData) => Promise<void>;

type RoiPanelProps = {
	workspaceId: string;
	data: RoiData;
	periodDays: number;
	selectedActionIds: number[];
	baseScopeQuery: string;
	recordOpen: boolean;
	importOpen: boolean;
	importBatch: GeoBusinessMetricImportBatch | null;
	importBatches: GeoBusinessMetricImportBatch[];
	recordMetric: FormAction;
	reverseMetric: FormAction;
	preflightImport: FormAction;
	confirmImport: FormAction;
	reverseImport: FormAction;
};

function money(minor: number | null | undefined, currency = "CNY") {
	if (minor == null) return "—";
	return new Intl.NumberFormat("zh-CN", { style: "currency", currency, maximumFractionDigits: 0 }).format(minor / 100);
}

function signed(value: number | null | undefined, suffix = "%") {
	if (value == null) return "暂无可比数据";
	return `${value > 0 ? "+" : ""}${value.toFixed(1)}${suffix}`;
}

function formatShortDate(value: string) {
	return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(value)).replace("/", "-");
}

function Sparkline({ values, tone = "blue" }: { values: number[]; tone?: "blue" | "navy" | "purple" }) {
	const safe = values.length > 1 ? values : [0, ...(values.length ? values : [0])];
	const min = Math.min(...safe);
	const max = Math.max(...safe);
	const points = safe.map((value, index) => {
		const x = index * (92 / Math.max(safe.length - 1, 1));
		const y = 25 - ((value - min) / Math.max(max - min, 1)) * 20;
		return `${x},${y}`;
	}).join(" ");
	return <svg className={`${styles.roiSparkline} ${styles[`spark${tone[0].toUpperCase()}${tone.slice(1)}`]}`} viewBox="0 0 92 30" aria-hidden="true"><polyline points={points}/></svg>;
}

function RoiTrendChart({ data }: { data: RoiData }) {
	const points = data.trend;
	const hasValues = points.some((point) => point.cost_minor || point.revenue_minor || point.roi_percent != null);
	if (!hasValues) return <div className={styles.roiChartEmpty}><span>⌒</span><b>录入投入与归因收入后，这里会生成 ROI 趋势</b><small>图表只使用当前筛选范围内的已确认记录</small></div>;
	const width = 1040;
	const height = 230;
	const left = 58;
	const right = 54;
	const top = 42;
	const bottom = 30;
	const chartWidth = width - left - right;
	const chartHeight = height - top - bottom;
	const maxMoney = Math.max(1, ...points.flatMap((point) => [point.cost_minor, point.revenue_minor]));
	const roiValues = points.map((point) => point.roi_percent).filter((value): value is number => value != null);
	const minRoi = Math.min(0, ...roiValues);
	const maxRoi = Math.max(20, ...roiValues);
	const x = (index: number) => left + index * (chartWidth / Math.max(points.length - 1, 1));
	const moneyY = (value: number) => top + chartHeight - (value / maxMoney) * chartHeight;
	const roiY = (value: number | null | undefined) => value == null ? top + chartHeight : top + chartHeight - ((value - minRoi) / Math.max(maxRoi - minRoi, 1)) * chartHeight;
	const line = (key: "cost_minor" | "revenue_minor") => points.map((point, index) => `${x(index)},${moneyY(point[key])}`).join(" ");
	const roiLine = points.map((point, index) => `${x(index)},${roiY(point.roi_percent)}`).join(" ");
	const firstTime = new Date(points[0].date).getTime();
	const lastTime = new Date(points.at(-1)?.date ?? points[0].date).getTime();
	const markerX = (date: string) => left + ((new Date(date).getTime() - firstTime) / Math.max(lastTime - firstTime, 1)) * chartWidth;
	const dateIndexes = [...new Set([0, Math.floor((points.length - 1) / 4), Math.floor((points.length - 1) / 2), Math.floor((points.length - 1) * .75), points.length - 1])];
	return <div className={styles.roiChartWrap}>
		<div className={styles.roiLegend}><span><i className={styles.roiLegendRevenue}/>归因收入（¥）</span><span><i className={styles.roiLegendCost}/>总投入（¥）</span><span><i className={styles.roiLegendPercent}/>ROI（%）</span><em>累计趋势</em></div>
		<svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="投入、归因收入与 ROI 趋势">
			{[0, .25, .5, .75, 1].map((ratio) => <g key={ratio}><line x1={left} x2={width-right} y1={top + chartHeight * (1-ratio)} y2={top + chartHeight * (1-ratio)} className={styles.roiGridLine}/><text x={left-10} y={top + chartHeight * (1-ratio)+4} textAnchor="end" className={styles.roiAxisText}>{money(Math.round(maxMoney*ratio), data.currency ?? "CNY")}</text><text x={width-right+10} y={top + chartHeight * (1-ratio)+4} className={styles.roiAxisText}>{Math.round(minRoi + (maxRoi-minRoi)*ratio)}%</text></g>)}
			{data.action_markers.slice(0, 4).map((marker) => { const px = Math.max(left, Math.min(width-right, markerX(marker.date))); return <g key={marker.action_id}><line x1={px} x2={px} y1={top-8} y2={top+chartHeight} className={styles.roiMarkerLine}/><text x={px+6} y={top-20} className={styles.roiMarkerDate}>{formatShortDate(marker.date)}</text><rect x={px+4} y={top-15} width={Math.min(150, 36 + marker.title.length*9)} height="22" rx="5" className={styles.roiMarkerTag}/><text x={px+10} y={top} className={styles.roiMarkerText}>{marker.title.slice(0, 12)}</text></g>; })}
			<polyline points={line("revenue_minor")} className={styles.roiRevenueLine}/>
			<polyline points={line("cost_minor")} className={styles.roiCostLine}/>
			<polyline points={roiLine} className={styles.roiPercentLine}/>
			{dateIndexes.map((index) => <text key={index} x={x(index)} y={height-6} textAnchor="middle" className={styles.roiAxisText}>{formatShortDate(points[index].date)}</text>)}
		</svg>
	</div>;
}

export function RoiPanel({ workspaceId, data, periodDays, selectedActionIds, baseScopeQuery, recordOpen, importOpen, importBatch, importBatches, recordMetric, reverseMetric, preflightImport, confirmImport, reverseImport }: RoiPanelProps) {
	const scopeHref = (period: number, actionIds: number[] = selectedActionIds) => {
		const params = new URLSearchParams(baseScopeQuery);
		params.set("tab", "roi");
		params.set("range", `${period}d`);
		params.delete("period");
		params.delete("roi_action");
		for (const actionId of actionIds) params.append("roi_action", String(actionId));
		return `/geo/${workspaceId}/results?${params.toString()}` as Route;
	};
	const currency = data.currency ?? "CNY";
	const roiDisplay = data.roi_percent == null ? "—" : `${data.roi_percent > 0 ? "+" : ""}${data.roi_percent.toFixed(1)}%`;
	const formActionOptions = data.action_options;
	const recordParams = new URLSearchParams(baseScopeQuery);
	recordParams.set("tab", "roi");
	recordParams.set("record", "1");
	recordParams.delete("roi_action");
	for (const actionId of selectedActionIds) recordParams.append("roi_action", String(actionId));
	const recordHref = `/geo/${workspaceId}/results?${recordParams.toString()}` as Route;
	const importParams = new URLSearchParams(recordParams);
	importParams.delete("record");
	importParams.set("import", "1");
	const importHref = `/geo/${workspaceId}/results?${importParams.toString()}` as Route;
	const closeHref = scopeHref(periodDays);
	const selectedActionId = selectedActionIds.length === 1 ? selectedActionIds[0] : null;
	const scopeHiddenFields = [...new URLSearchParams(baseScopeQuery).entries()].filter(([key]) => !["tab", "range", "period", "roi_action", "record", "import", "import_batch", "message"].includes(key));
	const costSeries = data.trend.map((point) => point.cost_minor);
	const revenueSeries = data.trend.map((point) => point.revenue_minor);
	const netSeries = data.trend.map((point) => point.net_value_minor ?? 0);
	const roiSeries = data.trend.map((point) => point.roi_percent ?? 0);
	const maxActionRoi = Math.max(1, ...data.action_portfolio.map((action) => Math.max(0, action.roi_percent ?? 0)));
	return <>
		<section className={styles.roiToolbar} aria-label="ROI 筛选">
			<div className={styles.roiToolbarFilters}>
				<details className={styles.roiSelect}><summary>最近 {periodDays === 365 ? "1 年" : `${periodDays} 天`}<span>⌄</span></summary><div>{[30,90,365].map((days) => <Link key={days} href={scopeHref(days)} className={days === periodDays ? styles.filterActive : ""}>{days === 365 ? "最近 1 年" : `最近 ${days} 天`}<i>{days === periodDays ? "✓" : ""}</i></Link>)}</div></details>
				<details className={`${styles.roiSelect} ${styles.roiActionSelect}`}><summary>{selectedActionIds.length ? `已选 ${selectedActionIds.length} 个行动` : "全部行动"}<span>⌄</span></summary><form method="get" action={`/geo/${workspaceId}/results`} className={styles.roiActionMulti}>{scopeHiddenFields.map(([key, value], index) => <input key={`${key}-${value}-${index}`} type="hidden" name={key} value={value}/>)}<input type="hidden" name="tab" value="roi"/><input type="hidden" name="range" value={`${periodDays}d`}/><div>{data.action_options.map((action) => <label key={action.id}><input type="checkbox" name="roi_action" value={action.id} defaultChecked={selectedActionIds.includes(action.id)}/><span>{action.label}</span><i>✓</i></label>)}</div><footer><Link href={scopeHref(periodDays, [])}>清空</Link><button type="submit">应用筛选</button></footer></form></details>
				<div className={styles.roiCompareSelect}>对比上一周期<span>⌄</span></div>
			</div>
			<div className={styles.roiToolbarActions}><Link className={styles.roiSingleButton} href={recordHref}>单笔录入</Link><Link className={styles.roiRecordButton} href={importHref}>导入 CSV</Link></div>
		</section>

		<section className={styles.roiHeroCard}>
			<div><small>本期 ROI</small><strong>{roiDisplay}</strong></div>
			<div className={styles.roiHeroNet}><small>净回报</small><b>{money(data.net_value_minor, currency)}</b><span>较上一周期 <em>{signed(data.comparison.roi_change_percentage_points, " 个百分点")}</em></span></div>
		</section>

		<section className={styles.roiKpiGrid}>
			<article><div><small>总投入</small><strong>{money(data.total_cost_minor, currency)}</strong><span>较上一周期 <em>{signed(data.comparison.cost_change_percent)}</em></span></div><Sparkline values={costSeries} tone="navy"/></article>
			<article><div><small>归因收入</small><strong>{money(data.direct_revenue_minor, currency)}</strong><span>较上一周期 <em>{signed(data.comparison.revenue_change_percent)}</em></span></div><Sparkline values={revenueSeries}/></article>
			<article><div><small>净回报</small><strong>{money(data.net_value_minor, currency)}</strong><span>较上一周期 <em>{signed(data.comparison.net_change_percent)}</em></span></div><Sparkline values={netSeries}/></article>
			<article><div><small>ROI</small><strong className={styles.roiBlueValue}>{roiDisplay}</strong><span>较上一周期 <em>{signed(data.comparison.roi_change_percentage_points, " 个百分点")}</em></span></div><Sparkline values={roiSeries} tone="purple"/></article>
		</section>

		<section className={styles.roiTrendPanel}><h2>投入与回报趋势</h2><RoiTrendChart data={data}/></section>

		<section className={styles.roiActionPanel}>
			<h2>行动 ROI 对比</h2>
			<div className={styles.roiActionTable}>
				<div className={styles.roiActionHead}><span>行动</span><span>投入</span><span>归因收入</span><span>净回报</span><span>ROI</span><span/></div>
				{data.action_portfolio.slice(0, 8).map((action, index) => <div className={styles.roiActionLine} key={action.action_id}><span><i>{index+1}</i><b>{action.title}</b></span><span><i style={{ width: `${Math.min(100, action.cost_minor / Math.max(1, ...data.action_portfolio.map((item) => item.cost_minor)) * 100)}%` }}/><b>{money(action.cost_minor || null, currency)}</b></span><span>{money(action.direct_revenue_minor || null, currency)}</span><span className={(action.net_value_minor ?? 0) < 0 ? styles.roiLoss : ""}>{money(action.net_value_minor, currency)}</span><span className={(action.roi_percent ?? 0) < 0 ? styles.roiLoss : ""}>{action.roi_percent == null ? "—" : signed(action.roi_percent)}</span><span><i style={{ width: `${Math.max(4, Math.max(0, action.roi_percent ?? 0) / maxActionRoi * 100)}%` }}/></span></div>)}
				{!data.action_portfolio.length ? <div className={styles.roiTableEmpty}>当前范围内还没有可对比的优化行动</div> : null}
			</div>
		</section>
		<p className={styles.roiFootnote}>仅统计已确认成本与关联行动、带 CRM/财务凭证的直接成交 · 数据更新于 {data.updated_at ? new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(data.updated_at)) : "暂无记录"}</p>
		{importBatches.length ? <details className={styles.roiImportHistory}><summary><span>最近导入</span><b>{importBatches.length} 个批次 ⌄</b></summary><div>{importBatches.slice(0, 8).map((batch) => <Link key={batch.id} href={`${scopeHref(periodDays)}&import_batch=${batch.id}` as Route}><span><b>{batch.file_name}</b><small>{new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(batch.created_at))}</small></span><em className={styles[`importStatus${batch.status[0].toUpperCase()}${batch.status.slice(1)}`]}>{batch.status === "confirmed" ? `已导入 ${batch.imported_rows} 条` : batch.status === "reversed" ? "已撤销" : "待确认"}</em></Link>)}</div></details> : null}

		{recordOpen ? <div className={styles.roiModalBackdrop}>
			<section className={styles.roiModal} role="dialog" aria-modal="true" aria-labelledby="roi-record-title">
				<header><div><small>ROI 数据</small><h2 id="roi-record-title">录入一笔业务数据</h2></div><Link href={closeHref} aria-label="关闭">×</Link></header>
				<form action={recordMetric} className={styles.roiMetricForm}>
					<input type="hidden" name="idempotency_key" value={randomUUID()}/>
					<label><span>数据类型</span><select name="metric_type" required defaultValue="content_cost"><optgroup label="投入成本"><option value="content_cost">内容制作成本</option><option value="labor_cost">内部人力成本</option><option value="distribution_cost">分发与媒体成本</option><option value="tool_cost">模型与工具成本</option></optgroup><optgroup label="业务结果"><option value="ai_referral_visit">AI 引荐访问</option><option value="qualified_lead">有效线索</option><option value="sales_opportunity">销售商机</option><option value="pipeline_value">商机管道金额</option><option value="won_revenue">已成交收入</option></optgroup></select></label>
					<label><span>金额或数量</span><input name="value" type="number" min="0" step="0.01" required placeholder="输入已核对数值"/></label>
					<label><span>币种</span><select name="currency" defaultValue="CNY"><option value="CNY">人民币 CNY</option><option value="USD">美元 USD</option><option value="EUR">欧元 EUR</option></select></label>
					<label><span>归因关系</span><select name="attribution_type" defaultValue="direct"><option value="direct">直接归因</option><option value="assisted">辅助归因</option><option value="unallocated">暂未分配</option></select></label>
					<label><span>关联优化行动</span><select name="action_id" defaultValue={selectedActionId ? String(selectedActionId) : ""}><option value="">暂不关联</option>{formActionOptions.map((action) => <option key={action.id} value={String(action.id)}>{action.label}</option>)}</select></label>
					<label><span>发生日期</span><input name="occurred_at" type="date" required defaultValue={new Date().toISOString().slice(0,10)}/></label>
					<label><span>数据来源</span><select name="source_type" defaultValue="manual"><option value="manual">人工核对</option><option value="analytics">分析平台</option><option value="crm">CRM</option><option value="finance">财务记录</option></select></label>
					<label><span>来源名称</span><input name="source_label" required minLength={2} placeholder="例：CRM 8 月成交表"/></label>
					<label className={styles.wide}><span>来源链接或凭证编号</span><input name="source_reference" placeholder="例：CRM-DEAL-20260824"/></label>
					<label className={styles.wide}><span>核对说明</span><textarea name="evidence_note" required minLength={4} placeholder="简单说明数据口径与关联关系"/></label>
					<button type="submit">保存数据</button>
				</form>
				{data.entries.length ? <details className={styles.roiAuditCompact}><summary>查看 {data.entries.length} 条原始记录</summary><div>{data.entries.map((entry) => <article key={entry.id}><span><b>{entry.metric_label}</b><small>{entry.source_label}</small></span><strong>{entry.amount_minor != null ? money(entry.amount_minor, entry.currency ?? currency) : entry.quantity}</strong>{!entry.is_reversal && !data.entries.some((item) => item.reverses_entry_id === entry.id) ? <form action={reverseMetric}><input type="hidden" name="entry_id" value={entry.id}/><input type="hidden" name="idempotency_key" value={randomUUID()}/><input name="reason" required minLength={4} placeholder="冲销原因"/><button type="submit">冲销</button></form> : null}</article>)}</div></details> : null}
			</section>
		</div> : null}

		{importOpen || importBatch ? <div className={styles.roiModalBackdrop}>
			<section className={`${styles.roiModal} ${styles.roiImportModal}`} role="dialog" aria-modal="true" aria-labelledby="roi-import-title">
				<header><div><small>ROI 批量导入</small><h2 id="roi-import-title">{importBatch ? "导入前核对" : "上传业务数据"}</h2></div><Link href={closeHref} aria-label="关闭">×</Link></header>
				<nav className={styles.roiImportSteps} aria-label="导入步骤"><span className={!importBatch ? styles.stepActive : styles.stepDone}><i>{importBatch ? "✓" : "1"}</i>上传文件</span><b/><span className={importBatch?.status === "preflight" ? styles.stepActive : importBatch ? styles.stepDone : ""}><i>{importBatch?.status !== "preflight" && importBatch ? "✓" : "2"}</i>数据预检</span><b/><span className={importBatch?.status === "confirmed" ? styles.stepDone : ""}><i>{importBatch?.status === "confirmed" ? "✓" : "3"}</i>确认导入</span></nav>
				{!importBatch ? <form action={preflightImport} className={styles.roiUploadForm}>
					<label><input type="file" name="file" accept=".csv,text/csv" required/><span><b>选择 CSV 文件</b><small>最多 5000 行，文件不超过 2MB</small></span></label>
					<div><a href={`/api/geo/${workspaceId}/roi-import-template`} download>↓ 下载标准模板</a><p>系统会先检查字段、币种、行动归属、凭证和重复记录，不会直接写入账本。</p></div>
					<button type="submit">上传并预检</button>
				</form> : <div className={styles.roiPreflight}>
					<div className={styles.roiImportFile}><span><i>CSV</i><b>{importBatch.file_name}</b><small>共 {importBatch.total_rows} 条记录</small></span><a href={importHref}>重新选择</a></div>
					<div className={styles.roiImportCounts}><article><i>✓</i><span><small>可导入</small><strong>{importBatch.valid_rows}</strong></span></article><article><i>!</i><span><small>需修正</small><strong>{importBatch.error_rows}</strong></span></article><article><i>⊘</i><span><small>已去重</small><strong>{importBatch.duplicate_rows}</strong></span></article><article><i>↓</i><span><small>已写入</small><strong>{importBatch.imported_rows}</strong></span></article></div>
					<div className={styles.roiImportTable}><header><span>行</span><span>记录编号</span><span>类型</span><span>金额 / 数量</span><span>状态</span><span>说明</span></header>{importBatch.rows.slice(0, 10).map((row) => { const firstError = row.errors[0]?.message; const value = row.normalized.amount ?? row.normalized.quantity ?? "—"; return <div key={row.id}><span>{row.row_number}</span><span>{row.record_id || "—"}</span><span>{String(row.normalized.metric_type || "—")}</span><span>{String(value)} {String(row.normalized.currency || "")}</span><span className={styles[`rowStatus${row.status[0].toUpperCase()}${row.status.slice(1)}`]}>{row.status === "valid" ? "可导入" : row.status === "imported" ? "已导入" : row.status === "duplicate" ? "已去重" : "需修正"}</span><span>{firstError || "检查通过"}</span></div>; })}</div>
					{importBatch.rows.length > 10 ? <p className={styles.roiImportMore}>仅预览前 10 条，其余 {importBatch.rows.length - 10} 条已完成相同检查。</p> : null}
					<details className={styles.roiImportMapping}><summary>字段对应关系 <span>⌄</span></summary><div>{Object.entries(importBatch.mapping.mapping ?? {}).map(([field, source]) => <span key={field}><b>{source}</b><i>→</i><em>{field}</em></span>)}</div></details>
					<footer className={styles.roiImportFooter}><div>{importBatch.error_rows || importBatch.duplicate_rows ? <a href={`/api/geo/${workspaceId}/roi-import-errors/${importBatch.id}`} download>下载错误清单</a> : <span>全部记录检查通过</span>}<small>只会写入“可导入”记录</small></div>{importBatch.status === "preflight" ? <form action={confirmImport}><input type="hidden" name="batch_id" value={importBatch.id}/><button type="submit" disabled={!importBatch.valid_rows}>确认导入 {importBatch.valid_rows} 条</button></form> : importBatch.status === "confirmed" ? <form action={reverseImport} className={styles.roiReverseBatch}><input type="hidden" name="batch_id" value={importBatch.id}/><input name="reason" required minLength={4} defaultValue="CSV 批次数据撤销"/><button type="submit">撤销该批次</button></form> : <strong>该批次已撤销</strong>}</footer>
				</div>}
			</section>
		</div> : null}
	</>;
}
