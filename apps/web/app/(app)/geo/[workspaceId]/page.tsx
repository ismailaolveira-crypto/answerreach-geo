import Link from "next/link";
import type { Route } from "next";
import { revalidatePath } from "next/cache";
import { notFound } from "next/navigation";
import { redirect } from "next/navigation";
import {
	getLLMProviderReadiness,
	getLLMProviders,
} from "@/lib/geo-provider-api";
import {
	getCleanroomActions,
	getCleanroomDecisionMap,
	getCleanroomEvidence,
	createCleanroomQuestion,
	updateCleanroomQuestion,
	createOfficialProviderObservationBatch,
	getOfficialProviderObservationBatch,
	getLatestOfficialProviderObservationBatch,
	getQueueWorkerStatus,
	type CleanroomEvidence,
	type QueueWorkerStatus,
} from "@/lib/cleanroom-v1-api";
import SamplingBatchPanel, {
	type ObservationProvider,
} from "./sampling-batch-panel";
import ObservationBatchProgress from "./observation-batch-progress";

export const maxDuration = 300;

type Props = {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<{
		model?: string;
		scope?: string;
		period?: string;
		notice?: string;
		error?: string;
		batch?: string;
	}>;
};

const STATUS: Record<string, { label: string; tone: string; icon: string }> = {
	absent: { label: "未出现", tone: "quiet", icon: "×" },
	mentioned: { label: "提及", tone: "blue", icon: "◌" },
	shortlisted: { label: "候选", tone: "green", icon: "○" },
	recommended: { label: "推荐", tone: "orange", icon: "♧" },
	cited: { label: "引用", tone: "violet", icon: "✦" },
	negative: { label: "负面", tone: "red", icon: "!" },
};

function Status({ value }: { value: CleanroomEvidence["brand_status"] }) {
	const status = STATUS[value] ?? STATUS.absent;
	return (
		<span className={`sy-status sy-status-${status.tone}`}>
			<i>{status.icon}</i>
			{status.label}
		</span>
	);
}

type KpiExplanation = {
	formula: string;
	numerator: string;
	denominator: string;
	scope: string;
	rules: string[];
};

function Kpi({
	label,
	value,
	detail,
	note,
	state,
	explanation,
}: {
	label: string;
	value: string;
	detail: string;
	note: string;
	state: "measured" | "zero" | "pending" | "verification";
	explanation: KpiExplanation;
}) {
	return (
		<article className="sy-kpi" data-state={state}>
			<header>
				<span>{label}</span>
				<details className="sy-kpi-explain">
					<summary
						className="sy-kpi-help"
						title={`查看${label}来源`}
						aria-label={`查看${label}计算来源`}
					>
						i
					</summary>
					<div role="note" aria-label={`${label}计算说明`}>
						<span>计算来源</span>
						<b>{explanation.formula}</b>
						<dl>
							<div>
								<dt>分子</dt>
								<dd>{explanation.numerator}</dd>
							</div>
							<div>
								<dt>分母</dt>
								<dd>{explanation.denominator}</dd>
							</div>
							<div>
								<dt>当前范围</dt>
								<dd>{explanation.scope}</dd>
							</div>
						</dl>
						<ul>
							{explanation.rules.map((rule) => (
								<li key={rule}>{rule}</li>
							))}
						</ul>
						<small>每次真实观测入库后由后端重新聚合，不使用前端缓存值。</small>
					</div>
				</details>
			</header>
			<strong>{value}</strong>
			<em>
				<i aria-hidden="true" />
				{note}
			</em>
			<small>{detail}</small>
		</article>
	);
}

export default async function SpringYuanDecisionMap({
	params,
	searchParams,
}: Props) {
	const { workspaceId } = await params;
	const query = await searchParams;
	const activeBatchId = Number(query.batch);
	const periodMode = ["7", "30", "90"].includes(String(query.period))
		? String(query.period)
		: "current";
	const periodDays = periodMode === "7" ? 7 : periodMode === "90" ? 90 : 30;
	const isCurrentMeasurement = periodMode === "current";
	const requestedScope = query.scope === "all" ? "all" : "high";
	const requestedModel =
		query.model &&
		[
			"deepseek",
			"doubao",
			"qianwen",
			"qwen",
			"glm",
			"kimi",
			"hunyuan",
		].includes(query.model)
			? query.model
			: "all";
	// The dashboard describes one measurement, not a lifetime aggregate. Keep
	// the last submitted batch selected until the user explicitly starts the
	// next one, then calculate both the matrix and KPI cards from that receipt.
	const activeBatch =
		Number.isInteger(activeBatchId) && activeBatchId > 0
			? await getOfficialProviderObservationBatch(
					workspaceId,
					activeBatchId,
				).catch(() => null)
			: await getLatestOfficialProviderObservationBatch(workspaceId).catch(
					() => null,
				);
	let decisionMap;
	let actions;
	let providers;
	let evidenceRows;
	let readinessRows;
	let workerStatus: QueueWorkerStatus | null;
	try {
		[decisionMap, actions, providers, evidenceRows, readinessRows, workerStatus] =
			await Promise.all([
				getCleanroomDecisionMap(workspaceId, {
					periodDays,
					modelKey: requestedModel,
					scope: requestedScope,
					batchId: isCurrentMeasurement ? activeBatch?.batch_id : undefined,
				}),
				getCleanroomActions(workspaceId),
				getLLMProviders(),
				getCleanroomEvidence(workspaceId),
				getLLMProviderReadiness().catch(() => []),
				getQueueWorkerStatus(workspaceId).catch(() => null),
			]);
	} catch (error) {
		if (error instanceof Error && error.message.includes("404")) notFound();
		throw error;
	}

	const selectedModel = decisionMap.models.some(
		(item) => item.key === requestedModel,
	)
		? requestedModel
		: "all";
	const selectedScope = requestedScope;
	const visibleModels =
		selectedModel === "all"
			? decisionMap.models
			: decisionMap.models.filter((item) => item.key === selectedModel);
	const visibleQuestions =
		selectedScope === "all"
			? decisionMap.questions
			: decisionMap.questions.filter((item) => item.importance >= 4);
	const cellByKey = new Map(
		decisionMap.cells.map((cell) => [
			`${cell.question_plan_id}:${cell.model_key}`,
			cell,
		]),
	);
	const metrics = decisionMap.metrics ?? {};
	const hasEvidence =
		(!isCurrentMeasurement || Boolean(activeBatch)) &&
		Number(metrics.eligible_samples ?? 0) > 0;
	const sampleNote = hasEvidence
		? `基于 ${metrics.eligible_samples ?? 0} 个样本`
		: "等待首轮观测";
	const metricValue = (value: unknown) =>
		typeof value === "number" ? value : 0;
	const eligibleSamples = metricValue(metrics.eligible_samples);
	const metricScopeLabel =
		isCurrentMeasurement && activeBatch
			? `本次测验 #${activeBatch.batch_id} · ${activeBatch.provider_count} 个模型 · ${activeBatch.question_count} 个问题 · 每题 ${activeBatch.repeat_count} 次`
			: isCurrentMeasurement
				? "尚未发起真实测验"
				: `近 ${periodDays} 天 · ${selectedModel === "all" ? "全部模型" : (visibleModels[0]?.label ?? selectedModel)} · ${selectedScope === "all" ? "全部问题" : "高价值问题"}`;
	const measurementLabel = isCurrentMeasurement
		? "本次测验"
		: `近 ${periodDays} 天`;
	const denominatorLabel = `${eligibleSamples} 条${measurementLabel}中已完成、真实且可审计的回答`;
	const ratioFormula = (numerator: number, rate: number) =>
		hasEvidence
			? `${numerator} ÷ ${eligibleSamples} × 100 = ${rate}%`
			: "暂无符合条件的真实样本";
	const outstandingActions = actions.filter(
		(item) => item.status !== "closed",
	).length;
	const platformDefinitions = [
		{ key: "deepseek", label: "DeepSeek" },
		{ key: "doubao", label: "豆包" },
		{ key: "qwen", label: "通义千问" },
		{ key: "glm", label: "智谱 GLM" },
		{ key: "kimi", label: "Kimi" },
		{ key: "hunyuan", label: "腾讯混元" },
	];
	// The decision map is the product's primary observation entry. It must only
	// surface the official channel for each model; custom/aggregated channels are
	// managed separately and must never replace an official card just because
	// they happen to share the same platform_key.
	const providerForPlatform = (key: string) =>
		providers.find((item) => {
			if (item.status !== "active") return false;
			const platformKey = String(
				item.cost_rule?.platform_key ?? "",
			).toLowerCase();
			const providerText = `${item.name} ${item.model_name}`.toLowerCase();
			if (key === "deepseek")
				return item.provider_type === "deepseek_web_search";
			if (key === "doubao")
				return (
					item.provider_type === "volcengine_ark" &&
					(platformKey === "doubao" ||
						providerText.includes("doubao") ||
						providerText.includes("豆包"))
				);
			if (key === "glm")
				return (
					item.provider_type === "volcengine_ark" &&
					(platformKey === "glm" || providerText.includes("glm"))
				);
			if (key === "qwen")
				return item.provider_type === "bailian_qwen_responses";
			if (key === "kimi") return item.provider_type === "kimi_web_search";
			return key === "hunyuan" && item.provider_type === "hunyuan_web_search";
		});
	const readinessByProvider = new Map(
		readinessRows.map((item) => [item.provider_id, item]),
	);
	const observationProviders: ObservationProvider[] = platformDefinitions.map(
		(definition) => {
			const provider = providerForPlatform(definition.key);
			const readiness = provider ? readinessByProvider.get(provider.id) : null;
			const latestTest = readiness?.latest_test ?? null;
			const ready = readiness?.collection_ready === true;
			return {
				...definition,
				providerId: provider?.id,
				status: ready ? "ready" : provider ? "needs_key" : "needs_key",
				statusLabel: ready
					? "联网可用"
					: readiness?.collection_blocker ||
						(latestTest?.ok === false
							? "联网测试未通过"
							: provider
								? "待主动测试"
								: "待配置"),
			};
		},
	);
	const officialEvidence = decisionMap.cells
		.map((cell) => cell.evidence)
		.filter((item): item is CleanroomEvidence =>
			Boolean(item?.collection_method === "official_api_web_search"),
		)
		.sort((a, b) => b.captured_at.localeCompare(a.captured_at))[0];
	const runnableQuestions = decisionMap.questions.filter(
		(item) => item.active && !item.is_brand_query,
	);
	const groupCountById = new Map<string, number>();
	evidenceRows.forEach((item) => {
		const groupId =
			typeof item.sampling_environment.observation_group_id === "string"
				? item.sampling_environment.observation_group_id
				: `single_${item.id}`;
		groupCountById.set(groupId, (groupCountById.get(groupId) ?? 0) + 1);
	});
	// A result table is evidence-driven, never a permanent six-model template.
	// When a batch is in the URL, mirror that batch's exact model/question
	// selection. Otherwise show only historical rows and columns that contain
	// at least one real result in the current filter scope.
	const batchModelKeys = new Set(
		activeBatch?.provider_groups.map((item) => item.key) ?? [],
	);
	const batchQuestionIds = new Set(
		activeBatch?.question_groups.map((item) => item.id) ?? [],
	);
	const candidateResultModels = activeBatch
		? visibleModels.filter((model) => batchModelKeys.has(model.key))
		: visibleModels;
	const candidateResultQuestions = activeBatch
		? visibleQuestions.filter((question) => batchQuestionIds.has(question.id))
		: visibleQuestions;
	const resultQuestions = candidateResultQuestions.filter((question) =>
		candidateResultModels.some((model) =>
			Boolean(cellByKey.get(`${question.id}:${model.key}`)?.evidence),
		),
	);
	const resultModels = candidateResultModels.filter((model) =>
		resultQuestions.some((question) =>
			Boolean(cellByKey.get(`${question.id}:${model.key}`)?.evidence),
		),
	);
	const hasResultMatrix = resultQuestions.length > 0 && resultModels.length > 0;

	async function runProviderObservation(formData: FormData) {
		"use server";
		const selectedProviderIds = JSON.parse(
			String(formData.get("provider_ids") || "[]"),
		) as unknown[];
		const selectedQuestionItems = JSON.parse(
			String(formData.get("selected_questions") || "[]"),
		) as Array<{ value?: string; text?: string }>;
		const customQuestion = String(formData.get("custom_question") ?? "").trim();
		const repeatCount = Math.min(
			5,
			Math.max(1, Number(formData.get("repeat_count")) || 5),
		);
		try {
			const providerIds = [
				...new Set(
					selectedProviderIds
						.map(Number)
						.filter((value) => Number.isInteger(value) && value > 0),
				),
			].slice(0, 5);
			if (!providerIds.length)
				throw new Error("请至少选择一个已经通过联网测试的模型");
			const questionIds: number[] = [];
			for (const item of selectedQuestionItems.slice(0, 5)) {
				const id = Number(item.value);
				if (
					Number.isInteger(id) &&
					runnableQuestions.some((question) => question.id === id)
				) {
					questionIds.push(id);
				} else if (String(item.text || "").trim().length >= 4) {
					questionIds.push(
						(
							await createCleanroomQuestion(
								workspaceId,
								String(item.text).trim(),
							)
						).id,
					);
				}
			}
			if (customQuestion.length >= 4 && questionIds.length < 5)
				questionIds.push(
					(await createCleanroomQuestion(workspaceId, customQuestion)).id,
				);
			const uniqueQuestionIds = [...new Set(questionIds)].slice(0, 5);
			if (!uniqueQuestionIds.length)
				throw new Error("请至少选择或输入一个有效采购问题");
			const batch = await createOfficialProviderObservationBatch(workspaceId, {
				provider_ids: providerIds,
				question_plan_ids: uniqueQuestionIds,
				repeat_count: repeatCount,
			});
			const expectedTotal =
				providerIds.length * uniqueQuestionIds.length * repeatCount;
			if (
				batch.provider_count !== providerIds.length ||
				batch.question_count !== uniqueQuestionIds.length ||
				batch.repeat_count !== repeatCount ||
				batch.total !== expectedTotal
			) {
				throw new Error(
					`任务矩阵校验失败：期望 ${expectedTotal} 条，后台仅创建 ${batch.total} 条`,
				);
			}
			revalidatePath(`/geo/${workspaceId}`);
			redirect(`/geo/${workspaceId}?notice=queued&batch=${batch.batch_id}`);
		} catch (error) {
			if (error && typeof error === "object" && "digest" in error) throw error;
			const message =
				error instanceof Error ? error.message.slice(0, 240) : "模型观测失败";
			redirect(
				`/geo/${workspaceId}?notice=failed&error=${encodeURIComponent(message)}`,
			);
		}
	}

	async function updateQuestion(questionId: number, questionText: string) {
		"use server";
		try {
			await updateCleanroomQuestion(workspaceId, questionId, questionText);
			revalidatePath(`/geo/${workspaceId}`);
			return { ok: true };
		} catch (error) {
			return {
				ok: false,
				error:
					error instanceof Error
						? error.message.slice(0, 180)
						: "常用问题保存失败",
			};
		}
	}

	return (
		<div className="sy-page">
			<header className="sy-topbar">
				<Link className="sy-brand" href={`/geo/${workspaceId}`}>
					<span>◈</span>
					<b>春秋元泉 GEO</b>
				</Link>
				<div className="sy-toplinks">
					<Link href={`/geo/${workspaceId}/sources`}>信源地图</Link>
					<Link href={`/geo/${workspaceId}/competitors` as Route}>
						竞品对比
					</Link>
					<Link href={`/geo/${workspaceId}/questions` as Route}>问题库</Link>
					<Link href={`/geo/${workspaceId}/actions`}>
						优化行动{outstandingActions ? <b>{outstandingActions}</b> : null}
					</Link>
					<Link href={`/admin/providers?workspace=${workspaceId}` as Route}>模型与渠道</Link>
					<Link href={`/geo/${workspaceId}/operations`}>运营状态</Link>
				</div>
			</header>
			<main className="sy-main">
				<section className="sy-heading">
					<div>
						<h1>决策地图</h1>
						<p>看见春秋元泉如何进入企业 AI 的真实采购决策。</p>
					</div>
					<div className="sy-cta-row">
						<form className="sy-filters" method="get" aria-label="筛选决策地图">
							<select
								name="period"
								defaultValue={periodMode}
								aria-label="观测时间"
							>
								<option value="current">当前测试</option>
								<option value="7">近 7 天</option>
								<option value="30">近 30 天</option>
								<option value="90">近 90 天</option>
							</select>
							<select
								name="model"
								defaultValue={selectedModel}
								aria-label="模型"
							>
								<option value="all">全部模型</option>
								{decisionMap.models.map((item) => (
									<option key={item.key} value={item.key}>
										{item.label}
									</option>
								))}
							</select>
							<select
								name="scope"
								defaultValue={selectedScope}
								aria-label="问题范围"
							>
								<option value="high">高价值问题</option>
								<option value="all">全部问题</option>
							</select>
							<button type="submit">筛选</button>
						</form>
					</div>
				</section>

				{activeBatch ? (
					<ObservationBatchProgress
						key={`observation-progress-${activeBatch.batch_id}`}
						workspaceId={workspaceId}
						initialBatch={activeBatch}
					/>
				) : null}
				{query.notice === "failed" ? (
					<div className="sy-notice sy-notice-error" role="alert">
						<b>本次观测未完成</b>
						<span>{query.error || "请检查 API 配置后重试。"}</span>
					</div>
				) : null}

				<SamplingBatchPanel
					key={`observation-composer-${activeBatch?.batch_id ?? "new"}`}
						workspaceId={workspaceId}
						questions={runnableQuestions}
						providers={observationProviders}
						workerStatus={workerStatus}
					lastEvidence={officialEvidence}
					initialSelection={activeBatch ? {
						batchId: activeBatch.batch_id,
						providerIds: activeBatch.provider_groups.map((group) => group.id),
						questions: activeBatch.question_groups.map((group) => ({ id: group.id, text: group.label })),
						repeatCount: activeBatch.repeat_count,
					} : undefined}
					runAction={runProviderObservation}
					updateQuestionAction={updateQuestion}
				/>

				<section className="sy-kpis" aria-label="本轮指标">
					<Kpi
						label="自然提及率"
						value={hasEvidence ? `${metricValue(metrics.mention_rate)}%` : "—"}
						state={
							!hasEvidence
								? "pending"
								: metricValue(metrics.mention_rate) === 0
									? "zero"
									: "measured"
						}
						note={
							!hasEvidence
								? `等待${measurementLabel}结果`
								: metricValue(metrics.mention_rate) === 0
									? `${measurementLabel}未命中`
									: sampleNote
						}
						detail={`在${measurementLabel}的不带品牌词回答中被自然提及的比例`}
						explanation={{
							formula: ratioFormula(
								metricValue(metrics.mention_count),
								metricValue(metrics.mention_rate),
							),
							numerator: `${metricValue(metrics.mention_count)} 条回答出现春秋元泉（含负面提及 ${metricValue(metrics.negative_mention_count)} 条）`,
							denominator: denominatorLabel,
							scope: metricScopeLabel,
							rules: [
								isCurrentMeasurement
									? "只统计当前测验批次已成功归档的官方 API 联网回答。"
									: `统计近 ${periodDays} 天内已成功归档的官方 API 联网回答。`,
								"失败、未完成、带品牌词、Mock 或证据不完整的任务不进入分母。",
							],
						}}
					/>
					<Kpi
						label="候选进入率"
						value={
							hasEvidence ? `${metricValue(metrics.shortlist_rate)}%` : "—"
						}
						state={
							!hasEvidence
								? "pending"
								: metricValue(metrics.shortlist_rate) === 0
									? "zero"
									: "measured"
						}
						note={
							!hasEvidence
								? `等待${measurementLabel}结果`
								: metricValue(metrics.shortlist_rate) === 0
									? `${measurementLabel}未进入`
									: sampleNote
						}
						detail={`${measurementLabel}中进入候选清单或前三位置的比例`}
						explanation={{
							formula: ratioFormula(
								metricValue(metrics.shortlist_count),
								metricValue(metrics.shortlist_rate),
							),
							numerator: `${metricValue(metrics.shortlist_count)} 条回答进入候选、被推荐或位于前三`,
							denominator: denominatorLabel,
							scope: metricScopeLabel,
							rules: [
								"明确进入候选/推荐，或品牌排序为第 1–3 位时计入。",
								"普通提及和负面提及不计入候选。",
							],
						}}
					/>
					<Kpi
						label="引用率"
						value={hasEvidence ? `${metricValue(metrics.citation_rate)}%` : "—"}
						state={
							!hasEvidence
								? "pending"
								: metricValue(metrics.citation_rate) === 0
									? "zero"
									: "measured"
						}
						note={
							!hasEvidence
								? `等待${measurementLabel}结果`
								: metricValue(metrics.citation_rate) === 0
									? `${measurementLabel}未引用`
									: sampleNote
						}
						detail={`${measurementLabel}回答中引用春秋元泉或其来源的比例`}
						explanation={{
							formula: ratioFormula(
								metricValue(metrics.citation_count),
								metricValue(metrics.citation_rate),
							),
							numerator: `${metricValue(metrics.citation_count)} 条回答引用春秋元泉品牌来源`,
							denominator: denominatorLabel,
							scope: metricScopeLabel,
							rules: [
								"引用标题或 URL 必须命中品牌名称，或域名属于已配置的品牌官网。",
								"一般网页来源只保留为证据，不会误算为品牌引用。",
							],
						}}
					/>
					<Kpi
						label="事实准确率"
						value={hasEvidence ? "待核验" : "—"}
						state={hasEvidence ? "verification" : "pending"}
						note={hasEvidence ? "需人工逐条核验" : "等待首轮观测"}
						detail="需要由品牌事实逐条核验，不以猜测代替结论"
						explanation={{
							formula: "当前不自动生成百分比",
							numerator: "经人工确认准确的品牌事实条数",
							denominator: "已完成人工核验的品牌事实条数",
							scope: metricScopeLabel,
							rules: [
								"模型回答不能自行证明事实准确。",
								"只有与品牌事实库逐条比对并完成人工确认后，才会显示比例。",
							],
						}}
					/>
				</section>

				{hasResultMatrix ? (
					<section className="sy-map-card">
						<header className="sy-map-head">
							<div>
								<h2>
									采购问题{" "}
									<span>{selectedScope === "all" ? "全部" : "高价值"}</span>
								</h2>
								<p>
									{hasEvidence
										? `近 ${periodDays} 天已验证 ${metrics.eligible_samples ?? 0} 个可审计样本；未回传的平台会保留为“未观测”。`
										: `近 ${periodDays} 天还没有真实采样结果。先开始一轮标准观测，结果会自动落在对应格子里。`}
								</p>
							</div>
							<small>点击任一结果查看完整证据</small>
						</header>
						<div className="sy-table-wrap">
							<table className="sy-matrix">
								<thead>
									<tr>
										<th>企业采购问题</th>
										{resultModels.map((model) => (
											<th key={model.key}>{model.label}</th>
										))}
									</tr>
								</thead>
								<tbody>
									{resultQuestions.map((question) => (
										<tr key={question.id}>
											<th>{question.question_text}</th>
											{resultModels.map((model) => {
												const evidence = cellByKey.get(
													`${question.id}:${model.key}`,
												)?.evidence;
												const groupId =
													evidence &&
													typeof evidence.sampling_environment
														.observation_group_id === "string"
														? evidence.sampling_environment.observation_group_id
														: evidence
															? `single_${evidence.id}`
															: null;
												const sampleCount = groupId
													? (groupCountById.get(groupId) ?? 1)
													: 0;
												return (
													<td key={model.key}>
														{evidence ? (
															<Link
																className="sy-cell"
																href={`/geo/${workspaceId}/evidence/${evidence.id}`}
															>
																<Status value={evidence.brand_status} />
																<small>
																	{evidence.is_real_provider_evidence
																		? `查看 ${sampleCount} 次回答`
																		: "不计入指标"}
																</small>
															</Link>
														) : (
															<span className="sy-no-result">— 本批无结果</span>
														)}
													</td>
												);
											})}
										</tr>
									))}
								</tbody>
							</table>
						</div>
						<footer className="sy-legend">
							<span>
								<i className="quiet">×</i>未出现
							</span>
							<span>
								<i className="blue">◌</i>提及
							</span>
							<span>
								<i className="green">○</i>候选
							</span>
							<span>
								<i className="orange">♧</i>推荐
							</span>
							<span>
								<i className="violet">✦</i>引用
							</span>
						</footer>
					</section>
				) : null}
				<p className="sy-proof-note">
					每一条 API 结果都会保存原始回答、搜索来源、原始响应和采样环境；API
					链路不伪造网页截图。缺少任一必要证据时不会进入指标。
				</p>
			</main>
		</div>
	);
}
