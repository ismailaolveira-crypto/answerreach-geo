import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import type { Route } from "next";
import { BrandLogo } from "@/components/brand-logo";
import {
	getQuestionAnalysis,
	type QuestionAnalysis,
} from "@/lib/cleanroom-v1-api";

const STATUS_LABELS: Record<string, string> = {
	absent: "未出现",
	mentioned: "提及",
	shortlisted: "候选",
	recommended: "推荐",
	cited: "引用",
	negative: "负面",
};

const JOURNEY_LABELS: Record<string, string> = {
	awareness: "认知",
	consideration: "评估",
	decision: "决策",
};

const ROLE_LABELS: Record<string, string> = {
	ciso: "CISO / 安全",
	technical_lead: "技术负责人",
	procurement: "采购 / 商务",
};

function percent(value: number) {
	return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%`;
}

function signed(value: number | null | undefined, suffix = "") {
	if (value == null) return "—";
	return `${value > 0 ? "+" : ""}${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}${suffix}`;
}

function positionDelta(value: number | null | undefined) {
	if (value == null) return "暂无对比";
	if (value === 0) return "持平";
	return value < 0 ? `提升 ${Math.abs(value)} 位` : `下降 ${value} 位`;
}

function date(value?: string | null) {
	if (!value) return "—";
	return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function scopeHref(workspaceId: string, questionId: string, scope: string) {
	return `/geo/${workspaceId}/questions/${questionId}?scope=${scope}`;
}

function modelBrand(key: string, label: string) {
	const value = `${key} ${label}`.toLowerCase();
	if (value.includes("deepseek")) return "deepseek";
	if (value.includes("doubao") || value.includes("豆包")) return "doubao";
	if (value.includes("qwen") || value.includes("千问")) return "qwen";
	if (value.includes("glm") || value.includes("智谱")) return "glm";
	if (value.includes("kimi") || value.includes("moonshot")) return "kimi";
	if (value.includes("hunyuan") || value.includes("混元")) return "hunyuan";
	return null;
}

function labelOf(labels: Record<string, string>, value: string | null | undefined) {
	if (!value) return "未分类";
	return labels[value] ?? value.replaceAll("_", " ");
}

function TrendCard({ label, current, previous, tone, format = percent, deltaSuffix = "pt", hasPrevious = true }: { label: string; current: number; previous: number; tone: "blue" | "green" | "orange" | "violet"; format?: (value: number) => string; deltaSuffix?: string; hasPrevious?: boolean }) {
	if (!hasPrevious) return <article className={`sy-analysis-trend-card tone-${tone} is-unavailable`}><div><small>{label}</small><b>{format(current)}</b><em>—</em></div><div className="sy-analysis-trend-unavailable">尚无可比较的上一周期真实回答</div><span>当前 {format(current)} · 生成下一周期后可对比</span></article>;
	const max = Math.max(current, previous, 1);
	const currentY = 42 - (current / max) * 27;
	const previousY = 42 - (previous / max) * 27;
	return <article className={`sy-analysis-trend-card tone-${tone}`}><div><small>{label}</small><b>{format(current)}</b><em>{signed(current - previous, deltaSuffix)}</em></div><svg viewBox="0 0 160 52" role="img" aria-label={`${label}从上一周期到当前周期的真实变化`}><line x1="8" y1="44" x2="152" y2="44" /><line className="sy-trend-previous" x1="16" y1={previousY} x2="144" y2={previousY} /><line className="sy-trend-current" x1="16" y1={previousY} x2="144" y2={currentY} /><circle className="sy-trend-previous-point" cx="16" cy={previousY} r="3" /><circle cx="144" cy={currentY} r="3" /></svg><span>当前 {format(current)} · 上一周期 {format(previous)}</span></article>;
}

function MetricIcon({ tone }: { tone: "green" | "blue" | "orange" | "violet" }) {
	if (tone === "green") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 4.8c-5.9.1-10.2 1.7-12.1 5.1-1.1 2-.8 4.1.5 5.6-1.2 1.4-2 2.7-2.4 3.7" /><path d="M6.7 15.5c2.6-2.5 5.1-4.1 7.8-5.1" /><path d="M10.4 19.1c.3-2.2.1-4.2-.5-6.1" /></svg>;
	if (tone === "blue") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h11" /><path d="m11 7 5 5-5 5" /><path d="M19 5v14" /></svg>;
	if (tone === "orange") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.2 8.1c0-1.8 1.1-3 2.9-3v3.2c-1.1.2-1.7.8-1.7 1.8h1.7v3.2H8.2v-2.4c0-1.1.1-1.9.5-2.8Z" /><path d="M14.8 8.1c0-1.8 1.1-3 2.9-3v3.2c-1.1.2-1.7.8-1.7 1.8h1.7v3.2h-2.9v-2.4c0-1.1.1-1.9.5-2.8Z" /></svg>;
	return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 7 3v5.3c0 4.1-2.8 7.7-7 9.7-4.2-2-7-5.6-7-9.7V6l7-3Z" /><path d="m8.8 12 2.1 2.1 4.5-4.7" /></svg>;
}

function MetricCard({ label, value, hint, delta, tone }: { label: string; value: string; hint: string; delta?: string; tone: "green" | "blue" | "orange" | "violet" }) {
	return <article className={`sy-analysis-metric tone-${tone}`}><div className="sy-analysis-metric-title"><span className="sy-analysis-metric-icon"><MetricIcon tone={tone} /></span><small>{label}</small></div><b>{value}</b><em className="sy-analysis-metric-delta">较上期&nbsp; {delta ?? "暂无对比"}</em><span>{hint}</span></article>;
}

function Empty({ children }: { children: ReactNode }) {
	return <div className="sy-analysis-empty">{children}</div>;
}

export default async function QuestionAnalysisPage({
	params,
	searchParams,
}: {
	params: Promise<{ workspaceId: string; questionId: string }>;
	searchParams: Promise<{ scope?: string }>;
}) {
	const { workspaceId, questionId } = await params;
	const query = await searchParams;
	const scope = (["current", "7", "30", "90"].includes(query.scope ?? "") ? query.scope : "current") as "current" | "7" | "30" | "90";
	let analysis: QuestionAnalysis;
	try {
		analysis = await getQuestionAnalysis(workspaceId, questionId, scope);
	} catch {
		notFound();
	}
	if (!analysis!) notFound();
	const current = analysis.comparison.current;
	const previous = analysis.comparison.previous;
	const delta = analysis.comparison.delta;
	const hasEvidence = current.answer_count > 0;

	return <div className="sy-page sy-page-analysis">
		<header className="sy-topbar">
			<Link className="sy-brand" href={`/geo/${workspaceId}`}><img alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" /><b>入答 AnswerReach</b></Link>
			<nav className="sy-toplinks">
				<Link href={`/geo/${workspaceId}`}>概览</Link>
				<Link className="is-current" href={`/geo/${workspaceId}/questions`}>问题分析</Link>
				<Link href={`/geo/${workspaceId}/competitors`}>对比分析</Link>
				<Link href={`/geo/${workspaceId}/operations`}>监控中心</Link>
				<Link href={`/geo/${workspaceId}/operations`}>数据管理</Link>
				<Link href={`/admin/providers?workspace=${workspaceId}` as Route}>设置</Link>
			</nav>
			<div className="sy-top-actions" aria-label="账户工具"><span aria-hidden="true">?</span><span aria-hidden="true">♧</span><b>张</b><i aria-hidden="true">⌄</i></div>
		</header>
		<main className="sy-question-analysis">
			<div className="sy-analysis-breadcrumb"><Link href={`/geo/${workspaceId}/questions`}>← 返回问题库</Link><span>问题分析</span></div>
			<h1 className="sy-analysis-page-title">问题分析</h1>
			<header className="sy-analysis-heading">
				<div className="sy-analysis-question-copy"><div className="sy-analysis-question-mark" aria-hidden="true">问</div><div><p>选中的问题</p><h1>{analysis.question.question_text}</h1><div className="sy-analysis-question-meta"><span>问题 ID · Q-{analysis.question.id}</span><span>问题阶段 · {labelOf(JOURNEY_LABELS, analysis.question.journey_stage)}</span><span>提问角色 · {labelOf(ROLE_LABELS, analysis.question.role)}</span><span>当前范围 · {analysis.scope.label}</span></div></div></div>
				<div className="sy-analysis-scope"><small>数据范围</small><div>{([["current", "当前测试"], ["7", "近 7 天"], ["30", "近 30 天"], ["90", "近 90 天"]] as const).map(([key, label]) => <Link key={key} className={scope === key ? "is-active" : ""} href={scopeHref(workspaceId, questionId, key) as Route}>{label}</Link>)}</div><small>{current.answer_count ? `只统计 ${current.answer_count} 条真实提供方回答` : "当前范围尚无真实提供方回答"}</small></div>
			</header>
			{hasEvidence ? <>
				<section className="sy-analysis-kpis">
					<MetricCard tone="green" label="自然提及率" value={percent(current.mention_rate)} hint={`${current.mention_count} / ${current.answer_count} 条回答`} delta={signed(delta.mention_rate, "pt")} />
					<MetricCard tone="blue" label="候选进入率" value={percent(current.answer_count ? (current.candidate_count / current.answer_count) * 100 : 0)} hint={`${current.candidate_count} 条进入候选`} delta={signed(delta.candidate_count, " 条")} />
					<MetricCard tone="orange" label="引用率" value={percent(current.source_rate)} hint={`${current.answers_with_sources} 条回答包含来源`} delta={signed(delta.source_rate, "pt")} />
					<MetricCard tone="violet" label="平均排名" value={current.average_position == null ? "待观察" : `第 ${current.average_position} 位`} hint={`${current.position_observation_count} 条回答有明确排名`} delta={positionDelta(delta.average_position)} />
				</section>
				<section className="sy-analysis-panel">
					<header><div><p>模型表现对比</p><h2>每个模型如何看见这个品牌</h2></div><small>{analysis.models.length} 个模型 · 只展示真实回答</small></header>
					{analysis.models.length ? <div className="sy-analysis-table-wrap"><table className="sy-analysis-table"><thead><tr><th>排名</th><th>模型</th><th>自然提及率</th><th>候选进入率</th><th>引用率</th><th>平均位置</th><th>状态</th></tr></thead><tbody>{analysis.models.map((model, index) => { const brand = modelBrand(model.key, model.label); const candidateRate = model.answer_count ? (model.candidate_count / model.answer_count) * 100 : 0; return <tr key={model.key}><td><span className={`sy-analysis-rank rank-${index + 1}`}>{index + 1}</span></td><th><div className="sy-analysis-model-name">{brand ? <BrandLogo brand={brand} label={model.label} className="sy-analysis-model-logo" /> : <span className="sy-analysis-model-fallback">AI</span>}<span><b>{model.label}</b><small>{model.key}</small></span></div></th><td>{percent(model.mention_rate)}</td><td>{percent(candidateRate)}</td><td>{percent(model.source_rate)}</td><td>{model.average_position == null ? "—" : `第 ${model.average_position} 位`}</td><td><span className={`sy-analysis-model-status ${model.mention_count ? "is-seen" : "is-muted"}`}>{model.mention_count ? "已提及" : "未提及"}</span></td></tr>; })}</tbody></table></div> : <Empty>当前范围没有按模型拆分的真实回答。</Empty>}
				</section>
				<section className="sy-analysis-two-col">
					<section className="sy-analysis-panel"><header><div><p>竞品对比</p><h2>这个问题上，我们输给了谁？</h2></div><small>只显示原文中可解释的竞品命中</small></header>{analysis.competitors.length ? <div className="sy-competitor-list">{analysis.competitors.map((competitor) => <article key={competitor.key}><div className="sy-competitor-rank"><b>{competitor.wins_over_brand}</b><small>胜过我们</small></div><div className="sy-competitor-copy"><strong>{competitor.name}</strong><span>出现 {competitor.appearances} 次 · 推荐 {competitor.recommendation_count} 次 · {competitor.average_position == null ? "无明确排名" : `平均第 ${competitor.average_position} 位`}</span></div><span className={competitor.wins_over_brand ? "sy-analysis-badge is-warn" : "sy-analysis-badge"}>{competitor.wins_over_brand ? "需要关注" : "暂无胜出"}</span></article>)}</div> : <Empty>当前问题尚未解析出竞品胜出关系。原文不确定时保持空白，不把猜测当结论。</Empty>}</section>
					<section className="sy-analysis-panel"><header><div><p>信源偏好</p><h2>模型更常引用哪些来源？</h2></div><small>按 URL 去重，按模型计数</small></header>{analysis.sources.length ? <div className="sy-source-list">{analysis.sources.slice(0, 6).map((source) => <a key={source.key} href={source.url} target="_blank" rel="noreferrer"><div><strong>{source.title}</strong><span>{source.domain} · {source.appearance_count} 次引用</span></div><small>{source.favored_models.map((model) => `${model.label} ${model.count}`).join(" · ")}</small><b>↗</b></a>)}</div> : <Empty>当前回答没有可解析的引用 URL。</Empty>}</section>
				</section>
				<section className="sy-analysis-panel"><header><div><p>当前与上一周期对比趋势</p><h2>这道题有没有变好？</h2></div><small>{previous.answer_count ? "同等长度周期对比" : "暂无可比较的上一周期"}</small></header><div className="sy-analysis-trend-grid"><TrendCard label="自然提及率" current={current.mention_rate} previous={previous.mention_rate} tone="green" hasPrevious={Boolean(previous.answer_count)} /><TrendCard label="候选进入率" current={current.answer_count ? (current.candidate_count / current.answer_count) * 100 : 0} previous={previous.answer_count ? (previous.candidate_count / previous.answer_count) * 100 : 0} tone="blue" hasPrevious={Boolean(previous.answer_count)} /><TrendCard label="引用率" current={current.source_rate} previous={previous.source_rate} tone="orange" hasPrevious={Boolean(previous.answer_count)} /><TrendCard label="平均排名" current={current.average_position == null ? 0 : current.average_position} previous={previous.average_position == null ? 0 : previous.average_position} tone="violet" format={(value) => value ? `第 ${value} 位` : "待观察"} deltaSuffix=" 位" hasPrevious={Boolean(previous.average_position)} /></div><div className="sy-analysis-period-summary"><span>当前 · {analysis.scope.label}：{current.answer_count} 条回答</span><span>上一周期：{previous.answer_count} 条回答</span><b>提及率变化 {signed(delta.mention_rate, "pt")} · 平均排名 {positionDelta(delta.average_position)}</b></div></section>
				<section className="sy-analysis-panel"><header><div><p>真实回答</p><h2>这组结论由哪些回答组成？</h2></div><small>{current.answer_count} 条 · 点击进入完整证据</small></header><div className="sy-analysis-evidence-list">{analysis.evidence.map((item) => <Link key={item.id} href={`/geo/${workspaceId}/evidence/${item.id}`}><span className="sy-evidence-number">{item.id}</span><div><strong>{item.model_label} · {STATUS_LABELS[item.brand_status] ?? item.brand_status}</strong><p>{item.answer_preview || "暂无摘要"}</p><small>{date(item.captured_at)} · {item.source_count} 个来源</small></div><b>查看证据 →</b></Link>)}</div></section>
			</> : <section className="sy-analysis-empty-state"><span>○</span><h2>这个问题还没有真实观测</h2><p>先在决策地图中选择模型和问题，完成一次真实联网观测；分析会自动回到这里。</p><Link className="sy-primary" href={`/geo/${workspaceId}`}>去发起观测</Link></section>}
		</main>
	</div>;
}
