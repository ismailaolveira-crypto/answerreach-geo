import Link from "next/link";
import type { Route } from "next";
import { getQuestionLibrary } from "@/lib/cleanroom-v1-api";

const STAGE_LABELS: Record<string, string> = {
	awareness: "认知",
	consideration: "评估",
	decision: "决策",
};

const ROLE_LABELS: Record<string, string> = {
	ciso: "CISO / 安全",
	technical_lead: "技术负责人",
	procurement: "采购 / 商务",
};

const STATUS_LABELS: Record<string, string> = {
	draft: "草稿",
	pending_review: "待审核",
	approved: "已批准",
	active: "已运行",
	deprecated: "已停用",
	rejected: "已拒绝",
};

export default async function QuestionAnalysisSelectorPage({
	params,
	searchParams,
}: {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<{ stage?: string; role?: string }>;
}) {
	const { workspaceId } = await params;
	const query = await searchParams;
	const library = await getQuestionLibrary(workspaceId, {
		stage: query.stage,
		role: query.role,
	});
	const activeCount = library.questions.filter((question) => ["approved", "active"].includes(question.status)).length;
	const filterLabel = [query.stage ? STAGE_LABELS[query.stage] : null, query.role ? ROLE_LABELS[query.role] : null].filter(Boolean).join(" · ");

	return <div className="sy-page sy-question-analysis-selector">
		<main className="sy-analysis-selector-main">
			<header className="sy-analysis-selector-hero">
				<div>
					<p>问题库 / 问题分析</p>
					<h1>选择一个问题</h1>
					<span>{filterLabel ? `正在查看 ${filterLabel} 下的问题。` : "从已治理的问题中进入分析；仅展示归档回答计算出的结果。"}</span>
				</div>
				<div className="sy-analysis-selector-summary"><small>当前列表</small><b>{library.questions.length}</b><span>{activeCount} 个可采样</span></div>
			</header>

			<section className="sy-analysis-selector-panel">
				<header>
					<div><p>待选问题</p><h2>{filterLabel || "全部问题"}</h2></div>
					<Link href={`/geo/${workspaceId}/questions` as Route}>返回问题库</Link>
				</header>
				{library.questions.length ? <div className="sy-analysis-selector-list">
					{library.questions.map((question) => <Link key={question.id} href={`/geo/${workspaceId}/questions/${question.id}` as Route} className="sy-analysis-selector-item">
						<span className="sy-analysis-selector-number">Q-{question.id}</span>
						<div><strong>{question.question_text}</strong><small>{STAGE_LABELS[question.journey_stage] ?? question.journey_stage} · {ROLE_LABELS[question.role] ?? question.role} · {question.topic_tags.join(" · ") || "未分类"}</small></div>
						<span className={`sy-question-status is-${question.status}`}>{STATUS_LABELS[question.status] ?? question.status}</span>
						<b>进入分析 →</b>
					</Link>)}
				</div> : <div className="sy-analysis-selector-empty"><b>这个分类下还没有问题</b><span>返回问题库，新建或审核问题后再查看分析。</span><Link href={`/geo/${workspaceId}/questions` as Route}>返回问题库</Link></div>}
			</section>
		</main>
	</div>;
}
