import Link from "next/link";
import type { Route } from "next";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
	createCleanroomQuestion,
	getQuestionLibrary,
	mergeCleanroomQuestion,
	questionPlanAction,
	updateCleanroomQuestion,
	type CleanroomQuestion,
} from "@/lib/cleanroom-v1-api";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";

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

function preserveQuery(formData: FormData) {
	const value = String(formData.get("return_query") ?? "");
	return value ? `?${value}` : "";
}

export default async function QuestionLibraryPage({
	params,
	searchParams,
}: {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<{
		search?: string;
		status?: string;
		stage?: string;
		role?: string;
		topic?: string;
		notice?: string;
		range?: string;
		from?: string;
		to?: string;
		batch?: string | string[];
		model?: string | string[];
		question?: string | string[];
	}>;
}) {
	const { workspaceId } = await params;
	const query = await searchParams;
	const selectedQuestionIds = (Array.isArray(query.question) ? query.question : query.question ? [query.question] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0);
	const library = await getQuestionLibrary(workspaceId, {
		search: query.search,
		status: query.status,
		stage: query.stage,
		role: query.role,
		topic: query.topic,
		question_plan_ids: selectedQuestionIds,
	});
	const returnParams = new URLSearchParams();
	for (const [key, raw] of Object.entries(query)) for (const value of Array.isArray(raw) ? raw : raw ? [raw] : []) returnParams.append(key, value);
	const returnQuery = returnParams.toString();

	async function addQuestion(formData: FormData) {
		"use server";
		const text = String(formData.get("question_text") ?? "").trim();
		if (text.length >= 4) {
			await createCleanroomQuestion(workspaceId, text, {
				journey_stage: String(formData.get("journey_stage") ?? "consideration"),
				role: String(formData.get("role") ?? "technical_lead"),
				topic_tags: String(formData.get("topic_tags") ?? "")
					.split(",")
					.map((item) => item.trim())
					.filter(Boolean),
				source_type: "manual",
			});
		}
		revalidatePath(`/geo/${workspaceId}/questions`);
		redirect(`/geo/${workspaceId}/questions` as Route);
	}

	async function reviewQuestion(formData: FormData) {
		"use server";
		const questionId = Number(formData.get("question_id"));
		const action = String(formData.get("action")) as
			| "approve"
			| "reject"
			| "deprecate";
		if (
			Number.isInteger(questionId) &&
			["approve", "reject", "deprecate"].includes(action)
		) {
			await questionPlanAction(
				workspaceId,
				questionId,
				action,
				String(formData.get("note") ?? "").trim() || undefined,
			);
		}
		revalidatePath(`/geo/${workspaceId}/questions`);
		redirect(
			`/geo/${workspaceId}/questions${preserveQuery(formData)}` as Route,
		);
	}

	async function mergeQuestion(formData: FormData) {
		"use server";
		const questionId = Number(formData.get("question_id"));
		const targetQuestionId = Number(formData.get("target_question_id"));
		if (Number.isInteger(questionId) && Number.isInteger(targetQuestionId)) {
			await mergeCleanroomQuestion(
				workspaceId,
				questionId,
				targetQuestionId,
				String(formData.get("note") ?? "").trim() || undefined,
			);
		}
		revalidatePath(`/geo/${workspaceId}/questions`);
		redirect(
			`/geo/${workspaceId}/questions${preserveQuery(formData)}` as Route,
		);
	}

	async function editQuestion(formData: FormData) {
		"use server";
		const questionId = Number(formData.get("question_id"));
		const text = String(formData.get("question_text") ?? "").trim();
		if (Number.isInteger(questionId) && text.length >= 4)
			await updateCleanroomQuestion(workspaceId, questionId, text);
		revalidatePath(`/geo/${workspaceId}/questions`);
		redirect(
			`/geo/${workspaceId}/questions${preserveQuery(formData)}` as Route,
		);
	}

	const matrix = library.stages.map((stage) => ({
		stage,
		cells: library.roles.map((role) => {
			const items = library.questions.filter(
				(question) =>
					question.journey_stage === stage && question.role === role,
			);
			return {
				role,
				items,
				approved: items.filter((item) =>
					["approved", "active"].includes(item.status),
				).length,
				pending: items.filter((item) =>
					["draft", "pending_review"].includes(item.status),
				).length,
				topics: [...new Set(items.flatMap((item) => item.topic_tags))].slice(
					0,
					3,
				),
			};
		}),
	}));
	const candidates = library.questions.filter((question) =>
		["draft", "pending_review"].includes(question.status),
	);
	const hasMatrixFilters = Boolean(
		query.search || query.status || query.stage || query.role || query.topic,
	);

	return (
		<div className="sy-page">
			<header className="sy-topbar">
				<Link className="sy-brand" href={`/geo/${workspaceId}`}>
					<img alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" />
					<b>入答 AnswerReach</b>
				</Link>
				<nav className="sy-toplinks">
					<Link href={`/geo/${workspaceId}/sources`}>信源地图</Link>
					<Link href={`/geo/${workspaceId}/competitors`}>竞品对比</Link>
					<Link
						aria-current="page"
						href={`/geo/${workspaceId}/questions` as Route}
					>
						问题库
					</Link>
					<Link href={`/geo/${workspaceId}/actions`}>优化行动</Link>
					<Link href={`/admin/providers?workspace=${workspaceId}` as Route}>模型与渠道</Link>
				</nav>
			</header>
			<main className="sy-question-library">
				<header className="sy-question-heading">
					<div>
						<p>采购问题治理</p>
						<h1>问题库</h1>
						<span>
							用采购阶段 ×
							提问角色管理真实采样问题。自动发现只进入候选收件箱，批准前不会进入正式采样。
						</span>
					</div>
					<details className="sy-question-add">
						<summary className="sy-primary">新增问题</summary>
						<form action={addQuestion}>
							<input
								name="question_text"
								required
								minLength={4}
								placeholder="例如：企业如何评估 Token 使用成本？"
							/>
							<div>
								<select name="journey_stage" defaultValue="consideration">
									<option value="awareness">认知</option>
									<option value="consideration">评估</option>
									<option value="decision">决策</option>
								</select>
								<select name="role" defaultValue="technical_lead">
									<option value="ciso">CISO / 安全</option>
									<option value="technical_lead">技术负责人</option>
									<option value="procurement">采购 / 商务</option>
								</select>
							</div>
							<input name="topic_tags" placeholder="主题标签，用逗号分隔" />
							<button className="sy-primary" type="submit">
								保存到问题库
							</button>
						</form>
					</details>
				</header>
				<GeoGlobalScopeBar workspaceId={workspaceId} />
				<section className="sy-question-kpis">
					<article>
						<small>问题总量</small>
						<b>{library.counts.total ?? 0}</b>
						<span>含历史问题与候选</span>
					</article>
					<article>
						<small>可采样问题</small>
						<b>{library.counts.sampling_eligible ?? 0}</b>
						<span>已批准且未停用</span>
					</article>
					<article className="is-warn">
						<small>待审核</small>
						<b>
							{(library.counts.pending_review ?? 0) +
								(library.counts.draft ?? 0)}
						</b>
						<span>需要人工判断来源与相似度</span>
					</article>
					<article>
						<small>最大缺口</small>
						<b>
							{
								matrix
									.flatMap((item) => item.cells)
									.filter((cell) => !cell.approved).length
							}
						</b>
						<span>阶段 × 角色覆盖格</span>
					</article>
				</section>
				<form className="sy-question-filters" method="get">
					<input
						name="search"
						defaultValue={query.search}
						placeholder="搜索问题文本"
					/>
					<select name="status" defaultValue={query.status ?? ""}>
						<option value="">全部状态</option>
						{Object.entries(STATUS_LABELS).map(([key, label]) => (
							<option key={key} value={key}>
								{label}
							</option>
						))}
					</select>
					<select name="stage" defaultValue={query.stage ?? ""}>
						<option value="">全部阶段</option>
						{library.stages.map((stage) => (
							<option key={stage} value={stage}>
								{STAGE_LABELS[stage]}
							</option>
						))}
					</select>
					<select name="role" defaultValue={query.role ?? ""}>
						<option value="">全部角色</option>
						{library.roles.map((role) => (
							<option key={role} value={role}>
								{ROLE_LABELS[role]}
							</option>
						))}
					</select>
					<select name="topic" defaultValue={query.topic ?? ""}>
						<option value="">全部主题</option>
						{library.topics.map((topic) => (
							<option key={topic} value={topic}>
								{topic}
							</option>
						))}
					</select>
					<button type="submit">筛选</button>
					<Link href={`/geo/${workspaceId}/questions` as Route}>清除</Link>
				</form>
				<section className="sy-question-matrix">
					<header>
						<div>
							<p>{hasMatrixFilters ? "当前筛选" : "默认视图"}</p>
							<h2>{hasMatrixFilters ? "当前筛选的阶段 × 角色" : "采购阶段 × 提问角色"}</h2>
						</div>
						<small>{hasMatrixFilters ? "每格仅统计当前筛选结果" : "每格显示已批准与待审核问题"}</small>
					</header>
					<div className="sy-question-grid">
						{matrix.map(({ stage, cells }) => (
							<section key={stage}>
								<h3>{STAGE_LABELS[stage]}</h3>
								{cells.map((cell) => {
									const destination = cell.items.length === 1
										? `/geo/${workspaceId}/questions/${cell.items[0].id}`
										: `/geo/${workspaceId}/questions/analysis?stage=${stage}&role=${cell.role}`;
									const detail = cell.topics.length
										? cell.topics.join(" · ")
										: cell.items.length
											? `${cell.items.length} 个问题`
											: "暂无主题";
									const content = <>
										<div>
											<b>{ROLE_LABELS[cell.role]}</b>
											<span>{cell.approved} 已批准 · {cell.pending} 待审</span>
										</div>
										<small>{detail}</small>
									</>;
									return cell.items.length ? (
										<Link key={cell.role} className="sy-question-matrix-link" href={destination as Route} aria-label={`查看${STAGE_LABELS[stage]}阶段${ROLE_LABELS[cell.role]}的问题分析`}>
											{content}
										</Link>
									) : (
										<article key={cell.role} className="is-gap" aria-label={`${STAGE_LABELS[stage]}阶段${ROLE_LABELS[cell.role]}暂无问题`}>
											{content}
										</article>
									);
								})}
							</section>
						))}
					</div>
				</section>
				<section className="sy-question-candidates">
					<header>
						<div>
							<p>候选收件箱</p>
							<h2>
								需要人工审核的问题 <span>{candidates.length}</span>
							</h2>
						</div>
						<small>核对来源、理由与相似问题后再批准</small>
					</header>
					{candidates.length ? (
						<div className="sy-candidate-list">
							{candidates.map((question) => (
								<Candidate
									key={question.id}
									question={question}
									allQuestions={library.questions}
									action={reviewQuestion}
									mergeAction={mergeQuestion}
									editAction={editQuestion}
									returnQuery={returnQuery}
								/>
							))}
						</div>
					) : (
						<div className="sy-question-empty">
							<b>收件箱为空</b>
							<span>
								没有待审核候选。手动新增问题会直接进入问题库；自动发现必须带有可读来源与理由。
							</span>
						</div>
					)}
				</section>
				<section className="sy-question-all">
					<header>
						<h2>
							全部问题 <span>{library.questions.length}</span>
						</h2>
						<small>当前筛选结果 · 历史问题不会被删除，停用只影响未来采样</small>
					</header>
					<div className="sy-question-table-wrap">
						<table className="sy-question-table">
							<thead>
								<tr>
									<th>问题</th>
									<th>阶段 / 角色</th>
									<th>主题</th>
									<th>来源</th>
									<th>状态</th>
									<th>版本</th>
								</tr>
							</thead>
							<tbody>
								{library.questions.map((question) => (
									<tr key={question.id}>
										<th><Link className="sy-question-detail-link" href={`/geo/${workspaceId}/questions/${question.id}`}>{question.question_text}</Link><small>查看该问题的模型表现、竞品与信源分析 →</small></th>
										<td>
											{STAGE_LABELS[question.journey_stage] ??
												question.journey_stage}
											<br />
											<small>
												{ROLE_LABELS[question.role] ?? question.role}
											</small>
										</td>
										<td>{question.topic_tags.join(" · ") || "—"}</td>
										<td>
											{question.source_type}
											<br />
											<small>{question.source_reason || "人工维护"}</small>
										</td>
										<td>
											<span
												className={`sy-question-status is-${question.status}`}
											>
												{STATUS_LABELS[question.status] ?? question.status}
											</span>
										</td>
										<td>v{question.version}</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				</section>
			</main>
		</div>
	);
}

function Candidate({
	question,
	allQuestions,
	action,
	mergeAction,
	editAction,
	returnQuery,
}: {
	question: CleanroomQuestion;
	allQuestions: CleanroomQuestion[];
	action: (formData: FormData) => Promise<void>;
	mergeAction: (formData: FormData) => Promise<void>;
	editAction: (formData: FormData) => Promise<void>;
	returnQuery: string;
}) {
	const mergeTargets = allQuestions.filter(
		(item) =>
			item.id !== question.id && ["approved", "active"].includes(item.status),
	);
	return (
		<details className="sy-candidate">
			<summary>
				<div>
					<span className={`sy-question-status is-${question.status}`}>
						{STATUS_LABELS[question.status]}
					</span>
					<strong>{question.question_text}</strong>
					<small>
						{STAGE_LABELS[question.journey_stage]} ·{" "}
						{ROLE_LABELS[question.role]} ·{" "}
						{question.topic_tags.join(" · ") || "未分类"}
					</small>
				</div>
				<b>查看详情 →</b>
			</summary>
			<div className="sy-candidate-detail">
				<div className="sy-candidate-evidence">
					<p>为什么建议加入</p>
					<strong>
						{question.source_reason || "该问题由人工添加，等待归类与批准。"}
					</strong>
					<dl>
						<div>
							<dt>来源类型</dt>
							<dd>{question.source_type}</dd>
						</div>
						<div>
							<dt>证据引用</dt>
							<dd>
								{Object.keys(question.source_evidence).length
									? JSON.stringify(question.source_evidence)
									: "暂无附加证据"}
							</dd>
						</div>
						<div>
							<dt>固定门禁</dt>
							<dd>批准前不会进入正式采样</dd>
						</div>
					</dl>
				</div>
				<form action={editAction} className="sy-candidate-edit">
					<input type="hidden" name="question_id" value={question.id} />
					<input type="hidden" name="return_query" value={returnQuery} />
					<label>
						编辑问题
						<textarea
							name="question_text"
							defaultValue={question.question_text}
							minLength={4}
							required
						/>
					</label>
					<label>
						备注
						<input name="note" placeholder="审核记录（可选）" />
					</label>
					<footer>
						<button
							name="action"
							value="reject"
							formAction={action}
							type="submit"
						>
							拒绝
						</button>
						<button
							className="sy-primary"
							name="action"
							value="approve"
							formAction={action}
							type="submit"
						>
							批准并加入问题库
						</button>
						<button type="submit">保存编辑</button>
					</footer>
				</form>
				{mergeTargets.length ? (
					<form action={mergeAction} className="sy-candidate-merge">
						<input type="hidden" name="question_id" value={question.id} />
						<input type="hidden" name="return_query" value={returnQuery} />
						<label>
							合并为角色变体
							<select
								name="target_question_id"
								defaultValue={mergeTargets[0].id}
							>
								{mergeTargets.map((target) => (
									<option key={target.id} value={target.id}>
										{target.question_text}
									</option>
								))}
							</select>
						</label>
						<button type="submit">合并重复</button>
					</form>
				) : null}
			</div>
		</details>
	);
}
