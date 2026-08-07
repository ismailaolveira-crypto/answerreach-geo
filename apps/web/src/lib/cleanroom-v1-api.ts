import { cookies } from "next/headers";

const API_BASE_URL =
	process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export type CleanroomWorkspace = {
	id: number;
	company_id: number;
	slug: string;
	brand_name: string;
	brand_aliases: string[];
	website_url?: string | null;
	status: string;
};

export type CleanroomQuestion = {
	id: number;
	workspace_id: number;
	question_text: string;
	journey_stage: string;
	role: string;
	topic_tags: string[];
	importance: number;
	is_brand_query: boolean;
	active: boolean;
	status:
		| "draft"
		| "pending_review"
		| "approved"
		| "active"
		| "deprecated"
		| "rejected";
	source_type: string;
	source_evidence: Record<string, unknown>;
	source_reason?: string | null;
	template_variables: string[];
	cluster_id?: string | null;
	similar_question_id?: number | null;
	similarity?: number | null;
	version: number;
	approved_by?: number | null;
	approved_at?: string | null;
	rejected_reason?: string | null;
	prompt_version: string;
};

export type QuestionLibrary = {
	workspace: CleanroomWorkspace;
	questions: CleanroomQuestion[];
	counts: Record<string, number>;
	filters: {
		search?: string | null;
		status?: string | null;
		stage?: string | null;
		role?: string | null;
		topic?: string | null;
	};
	stages: string[];
	roles: string[];
	topics: string[];
};

export type CleanroomEvidence = {
	id: number;
	workspace_id: number;
	run_id: number;
	question_plan_id: number;
	model_key: string;
	model_label: string;
	prompt_version: string;
	sample_mode: string;
	evidence_level: string;
	collection_method: string;
	is_real_provider_evidence: boolean;
	brand_status:
		| "absent"
		| "mentioned"
		| "shortlisted"
		| "recommended"
		| "cited"
		| "negative";
	brand_position?: number | null;
	competitor_positions: Array<Record<string, unknown>>;
	answer_text: string;
	source_items: Array<Record<string, unknown>>;
	sampling_environment: Record<string, unknown>;
	raw_artifact_uri?: string | null;
	screenshot_uri?: string | null;
	captured_at: string;
};

export type QuestionAnalysisMetric = {
	answer_count: number;
	mention_count: number;
	mention_rate: number;
	candidate_count: number;
	recommendation_count: number;
	recommendation_rate: number;
	cited_count: number;
	brand_citation_rate: number;
	answers_with_sources: number;
	source_rate: number;
	average_position?: number | null;
	position_observation_count: number;
};

export type QuestionAnalysis = {
	question: CleanroomQuestion;
	scope: {
		kind: "current" | "7" | "30" | "90";
		label: string;
		period_days?: number | null;
		real_provider_evidence_only: boolean;
		current_run_ids: number[];
		previous_run_ids: number[];
	};
	summary: QuestionAnalysisMetric;
	comparison: {
		current: QuestionAnalysisMetric;
		previous: QuestionAnalysisMetric;
		delta: Record<string, number | null>;
	};
	models: Array<QuestionAnalysisMetric & {
		key: string;
		label: string;
		latest_captured_at?: string | null;
		evidence_ids: number[];
	}>;
	competitors: Array<{
		key: string;
		name: string;
		aliases: string[];
		appearances: number;
		appearance_rate: number;
		candidate_count: number;
		recommendation_count: number;
		average_position?: number | null;
		top3_count: number;
		top3_rate: number;
		wins_over_brand: number;
		comparable_answers: number;
		evidence_ids: number[];
		is_baseline: boolean;
	}>;
	sources: Array<{
		key: string;
		domain: string;
		url: string;
		title: string;
		appearance_count: number;
		model_count: number;
		favored_models: Array<{ key: string; label: string; count: number }>;
		evidence_ids: number[];
	}>;
	trend: Array<QuestionAnalysisMetric & { label: string }>;
	evidence: Array<{
		id: number;
		run_id: number;
		model_key: string;
		model_label: string;
		brand_status: string;
		brand_position?: number | null;
		answer_preview: string;
		source_count: number;
		captured_at: string;
	}>;
	methodology: Record<string, string>;
};

export type CleanroomScorecard = {
	id: number;
	workspace_id: number;
	run_id: number;
	scoring_version: string;
	input_fingerprint: string;
	metrics: Record<string, number | null>;
	explanation: Record<string, string>;
};

export type CleanroomDecisionMap = {
	workspace: CleanroomWorkspace;
	questions: CleanroomQuestion[];
	scorecard?: CleanroomScorecard | null;
	models: Array<{ key: string; label: string }>;
	cells: Array<{
		question_plan_id: number;
		model_key: string;
		model_label: string;
		evidence?: CleanroomEvidence | null;
	}>;
	metrics: Record<string, number | null>;
	metric_scope: Record<string, string | number | null>;
	sample_count: number;
};

export type SourceMapBreakdown = {
	key?: string | null;
	id?: number | null;
	label?: string | null;
	text?: string | null;
	citation_count: number;
	answer_count: number;
};

export type SourceMapItem = {
	key: string;
	label: string;
	canonical_url?: string | null;
	title?: string | null;
	citation_count: number;
	answer_count: number;
	model_count: number;
	brand_absent_answer_count: number;
	brand_absent_answer_ratio: number;
	evidence_ids: number[];
	evidence_references: Array<{
		evidence_id: number;
		source_url: string;
		source_title?: string | null;
	}>;
	evidence_total: number;
	evidence_truncated: boolean;
	models: SourceMapBreakdown[];
	questions: SourceMapBreakdown[];
	reason?: string | null;
};

export type CleanroomSourceMap = {
	workspace: CleanroomWorkspace;
	scope: {
		date_from?: string | null;
		date_to?: string | null;
		period_days?: number | null;
		model_key?: string | null;
		question_plan_id?: number | null;
		real_provider_evidence_only: boolean;
	};
	summary: {
		answer_count: number;
		answers_with_sources: number;
		citation_count: number;
		unique_domain_count: number;
		unique_page_count: number;
		brand_absent_answer_count: number;
		brand_absent_answer_ratio: number;
		ignored_source_count: number;
		duplicate_source_count: number;
		excluded_non_real_answer_count: number;
	};
	available_models: Array<{ key: string; label: string }>;
	available_questions: CleanroomQuestion[];
	domains: SourceMapItem[];
	pages: SourceMapItem[];
	opportunities: SourceMapItem[];
	interpretation_notice: string;
};

export type CompetitorEvidenceSnippet = {
	evidence_id: number;
	question_plan_id: number;
	question: string;
	model_key: string;
	model_label: string;
	brand_key: string;
	brand_name: string;
	matched_brand_keys: string[];
	matched_aliases: string[];
	match_count: number;
	status: "mentioned" | "shortlisted" | "recommended" | "negative";
	appearance_order: number;
	explicit_list_position?: number | null;
	explicit_rank?: number | null;
	baseline_explicit_rank?: number | null;
	comparison_result: "win" | "comparable" | "not_comparable";
	win_reason_type?: "explicit_rank_ahead" | "selected_baseline_absent" | null;
	context_snippet: string;
	captured_at: string;
};

export type CompetitorBrandStat = {
	key: string;
	canonical_name: string;
	aliases: string[];
	is_baseline: boolean;
	hit_answer_count: number;
	sample_answer_count: number;
	mention_rate: number;
	question_count: number;
	model_count: number;
	candidate_count: number;
	recommendation_count: number;
	negative_count: number;
	average_first_appearance_order?: number | null;
	order_observation_count: number;
	wins_over_baseline: number;
	comparable_answers: number;
	top3_count: number;
	top3_rate: number;
	explicit_average_position?: number | null;
	explicit_rank_observation_count: number;
	win_reason_counts: Record<string, number>;
	win_evidence: CompetitorEvidenceSnippet[];
	evidence_total: number;
	evidence: CompetitorEvidenceSnippet[];
};

export type CompetitorBreakdown = {
	key?: string | null;
	id?: number | null;
	label: string;
	answer_count: number;
	brands: CompetitorBrandStat[];
};

export type CleanroomCompetitorComparison = {
	workspace: CleanroomWorkspace;
	scope: {
		date_from?: string | null;
		date_to?: string | null;
		period_days?: number | null;
		model_key?: string | null;
		question_plan_id?: number | null;
		real_provider_evidence_only: boolean;
	};
	summary: {
		answer_count: number;
		tracked_brand_count: number;
		answers_with_tracked_brand: number;
		excluded_non_real_answer_count: number;
		comparable_answer_count: number;
		answers_where_competitor_wins: number;
	};
	brands: CompetitorBrandStat[];
	by_model: CompetitorBreakdown[];
	by_question: CompetitorBreakdown[];
	action_diagnostics: Array<{
		competitor_key: string;
		competitor_name: string;
		model_key: string;
		model_label: string;
		question_plan_id: number;
		question: string;
		competitor_hit_count: number;
		baseline_hit_count: number;
		mention_gap: number;
		wins_over_baseline: number;
		comparable_answers: number;
		reason_type: "explicit_rank_ahead" | "selected_baseline_absent";
		reason_label: string;
		evidence_count: number;
		evidence_ids: number[];
		evidence: CompetitorEvidenceSnippet[];
		suggestion: string;
		suggestion_type:
			| "fill_citable_content_then_retest"
			| "strengthen_comparison_evidence_then_retest";
	}>;
	available_models: Array<{ key: string; label: string }>;
	available_questions: CleanroomQuestion[];
	matching_rule_version: string;
	methodology: Record<string, string>;
};

export type StandardObservationRun = {
	id: number;
	workspace_id: number;
	adapter_key: string;
	status: string;
	request_context: Record<string, unknown>;
	started_at?: string | null;
	completed_at?: string | null;
	failure_reason?: string | null;
};

export type StandardObservationResponse = {
	run: StandardObservationRun;
	message: string;
	providers: Array<{ key: string; label: string }>;
	question_count: number;
};

export type OfficialApiObservationResponse = {
	run: StandardObservationRun;
	evidence: CleanroomEvidence;
	scorecard: CleanroomScorecard;
	message: string;
};

export type QueuedOfficialApiObservationResponse = {
	job_id: number;
	status: "pending" | "running";
	message: string;
};

export type OfficialApiObservationJobStatus = {
	job_id: number;
	status: "pending" | "running" | "success" | "failed";
	run_id?: number | null;
	evidence_id?: number | null;
	error_message?: string | null;
};

export type BrowserAccount = {
	id: number;
	workspace_id: number;
	provider_key: "deepseek";
	alias: string;
	ego_task_space_id?: number | null;
	browser_profile_alias?: string | null;
	cohort: "clean_baseline" | "real_user";
	status:
		| "onboarding"
		| "ready"
		| "busy"
		| "cooldown"
		| "reauth_required"
		| "disabled";
	isolation_verified: boolean;
	isolation_verified_at?: string | null;
	health_note?: string | null;
	last_checked_at?: string | null;
	last_used_at?: string | null;
	cooldown_until?: string | null;
	consecutive_failures: number;
	lease_worker_id?: string | null;
	lease_run_id?: number | null;
	lease_expires_at?: string | null;
};

export type SamplingSample = {
	id: number;
	batch_id: number;
	browser_account_id: number;
	question_plan_id: number;
	repeat_index: number;
	status: "queued" | "running" | "completed" | "failed";
	attempt_count: number;
	evidence_id?: number | null;
	error_code?: string | null;
	error_detail?: string | null;
	started_at?: string | null;
	completed_at?: string | null;
	conversation_deleted_at?: string | null;
};

export type SamplingBatch = {
	id: number;
	workspace_id: number;
	run_id: number;
	provider_key: "deepseek";
	status: "queued" | "running" | "completed" | "partial" | "failed";
	account_count: number;
	question_count: number;
	repeat_count: number;
	total_samples: number;
	completed_samples: number;
	failed_samples: number;
	configuration: Record<string, unknown>;
	current_message?: string | null;
	failure_reason?: string | null;
	started_at?: string | null;
	completed_at?: string | null;
	samples: SamplingSample[];
};

export type OfficialApiObservationBatchGroup = {
	id: number;
	key: string;
	label: string;
	total: number;
	pending: number;
	running: number;
	succeeded: number;
	failed: number;
};

export type Pagination = {
	page: number;
	page_size: number;
	total: number;
	total_pages: number;
};

export type OfficialApiObservationBatchSummary = {
	batch_id: number;
	status: "pending" | "running" | "success" | "partial" | "failed";
	provider_count: number;
	question_count: number;
	repeat_count: number;
	total: number;
	pending: number;
	running: number;
	succeeded: number;
	failed: number;
	progress_percent: number;
	status_percentages: Record<
		"pending" | "running" | "succeeded" | "failed",
		number
	>;
	created_at: string;
	started_at?: string | null;
	finished_at?: string | null;
};

export type OfficialApiObservationTask = {
	job_id: number;
	provider_id: number;
	provider_key: string;
	provider_label: string;
	question_plan_id: number;
	question_label: string;
	repeat_index: number;
	status: "pending" | "running" | "success" | "failed";
	evidence_id?: number | null;
	error_message?: string | null;
	started_at?: string | null;
	finished_at?: string | null;
	duration_seconds?: number | null;
};

export type OfficialApiObservationBatch = OfficialApiObservationBatchSummary & {
	provider_groups: OfficialApiObservationBatchGroup[];
	question_groups: OfficialApiObservationBatchGroup[];
	evidence_ids: number[];
	errors: string[];
	tasks: OfficialApiObservationTask[];
	task_pagination: Pagination;
};

export type OfficialApiObservationBatchList = {
	items: OfficialApiObservationBatchSummary[];
	pagination: Pagination;
};

export type CleanroomAction = {
	id: number;
	workspace_id: number;
	title: string;
	rationale: string;
	hypothesis?: string | null;
	priority: "high" | "medium" | "low";
	question_plan_id?: number | null;
	source_evidence_id?: number | null;
	status: string;
	opportunity_id?: number | null;
	stage?: string;
	baseline_snapshot?: Record<string, unknown>;
	selected_scope?: Record<string, unknown>;
	blocked_reason?: string | null;
	selected_at?: string | null;
	completed_at?: string | null;
};

export type CleanroomActionOpportunityEvidence = {
	id: number;
	opportunity_id: number;
	evidence_id: number;
	question_plan_id: number;
	batch_id?: number | null;
	observation_task_id?: number | null;
	model_key: string;
	signal_type: string;
	signal_value: Record<string, unknown>;
	evidence_hash: string;
	source_url?: string | null;
};

export type CleanroomActionOpportunity = {
	id: number;
	workspace_id: number;
	fingerprint: string;
	opportunity_type: string;
	title: string;
	summary: string;
	priority_score: number;
	priority_label: "high" | "medium" | "low";
	evidence_strength: number;
	source_gap_type?: string | null;
	recommended_asset_type: string;
	recommended_platforms: string[];
	scope_snapshot: Record<string, unknown>;
	rule_version: string;
	status: string;
	first_seen_batch_id?: number | null;
	latest_seen_batch_id?: number | null;
	evidence: CleanroomActionOpportunityEvidence[];
};

export type CleanroomContentBrief = {
	id: number;
	workspace_id: number;
	action_id: number;
	question_plan_id?: number | null;
	audience: string;
	intent: string;
	asset_type: string;
	required_sections: string[];
	brand_fact_ids: number[];
	evidence_ids: number[];
	source_urls: string[];
	required_claims: string[];
	forbidden_claims: string[];
	open_questions: string[];
	prompt_template_id?: number | null;
	input_fingerprint: string;
	status: string;
};

export type CleanroomContentAsset = {
	id: number;
	workspace_id: number;
	brief_id: number;
	version: number;
	title: string;
	summary: string;
	body_markdown: string;
	content_fingerprint: string;
	model_provider_id?: number | null;
	model_name?: string | null;
	prompt_template_id?: number | null;
	prompt_hash?: string | null;
	raw_artifact_uri?: string | null;
	generation_usage: Record<string, unknown>;
	status: string;
};

export type CleanroomContentGenerationJob = {
	id: number;
	job_type: string;
	status: string;
	payload_json: Record<string, unknown>;
	error_message?: string | null;
};

export type CleanroomBrandFact = {
	id: number;
	workspace_id: number;
	title: string;
	statement: string;
	source_url?: string | null;
	status: string;
};

export type CleanroomContentAudit = {
	id: number;
	workspace_id: number;
	target_url?: string | null;
	content_fingerprint: string;
	audit_version: string;
	score: number;
	checks: Record<string, boolean | number>;
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	const response = await fetch(`${API_BASE_URL}/api/v1${path}`, {
		...init,
		cache: "no-store",
		headers: {
			"Content-Type": "application/json",
			...(token ? { Authorization: `Bearer ${token}` } : {}),
			...(init?.headers ?? {}),
		},
	});
	if (!response.ok) {
		const errorBody = (await response.json().catch(() => null)) as {
			detail?: string;
		} | null;
		throw new Error(
			errorBody?.detail || `Clean-room GEO API ${response.status}`,
		);
	}
	return response.json() as Promise<T>;
}

export function getCleanroomWorkspaces() {
	return apiRequest<CleanroomWorkspace[]>("/workspaces");
}

export function updateCleanroomWorkspace(
	workspaceId: string | number,
	payload: Pick<CleanroomWorkspace, "brand_name" | "brand_aliases" | "website_url">,
) {
	return apiRequest<CleanroomWorkspace>(`/workspaces/${workspaceId}`, {
		method: "PATCH",
		body: JSON.stringify(payload),
	});
}

export function getCleanroomDecisionMap(
	workspaceId: string | number,
	filters?: {
		periodDays?: number;
		modelKey?: string;
		scope?: "all" | "high";
		batchId?: number;
	},
) {
	const params = new URLSearchParams();
	if (filters?.periodDays)
		params.set("period_days", String(filters.periodDays));
	if (filters?.modelKey && filters.modelKey !== "all")
		params.set("model_key", filters.modelKey);
	if (filters?.scope) params.set("scope", filters.scope);
	if (filters?.batchId) params.set("batch_id", String(filters.batchId));
	const suffix = params.toString() ? `?${params.toString()}` : "";
	return apiRequest<CleanroomDecisionMap>(
		`/workspaces/${workspaceId}/decision-map${suffix}`,
	);
}

export function getCleanroomSourceMap(
	workspaceId: string | number,
	filters?: {
		periodDays?: number;
		modelKey?: string;
		questionPlanId?: number;
		limit?: number;
	},
) {
	const params = new URLSearchParams();
	if (filters?.periodDays)
		params.set("period_days", String(filters.periodDays));
	if (filters?.modelKey && filters.modelKey !== "all")
		params.set("model_key", filters.modelKey);
	if (filters?.questionPlanId)
		params.set("question_plan_id", String(filters.questionPlanId));
	if (filters?.limit) params.set("limit", String(filters.limit));
	const suffix = params.toString() ? `?${params.toString()}` : "";
	return apiRequest<CleanroomSourceMap>(
		`/workspaces/${workspaceId}/source-map${suffix}`,
	);
}

export function getCleanroomCompetitorComparison(
	workspaceId: string | number,
	filters?: {
		periodDays?: number;
		modelKey?: string;
		questionPlanId?: number;
		evidenceLimit?: number;
	},
) {
	const params = new URLSearchParams();
	if (filters?.periodDays)
		params.set("period_days", String(filters.periodDays));
	if (filters?.modelKey && filters.modelKey !== "all")
		params.set("model_key", filters.modelKey);
	if (filters?.questionPlanId)
		params.set("question_plan_id", String(filters.questionPlanId));
	if (filters?.evidenceLimit)
		params.set("evidence_limit", String(filters.evidenceLimit));
	const suffix = params.toString() ? `?${params.toString()}` : "";
	return apiRequest<CleanroomCompetitorComparison>(
		`/workspaces/${workspaceId}/competitor-comparison${suffix}`,
	);
}

export function startCleanroomStandardObservation(
	workspaceId: string | number,
	repeatCount = 3,
) {
	return apiRequest<StandardObservationResponse>(
		`/workspaces/${workspaceId}/observations/standard`,
		{
			method: "POST",
			body: JSON.stringify({ repeat_count: repeatCount }),
		},
	);
}

export function getQuestionLibrary(
	workspaceId: string | number,
	filters?: {
		search?: string;
		status?: string;
		stage?: string;
		role?: string;
		topic?: string;
	},
) {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(filters ?? {}))
		if (value) params.set(key, value);
	const suffix = params.size ? `?${params.toString()}` : "";
	return apiRequest<QuestionLibrary>(
		`/workspaces/${workspaceId}/question-library${suffix}`,
	);
}

export function getQuestionAnalysis(
	workspaceId: string | number,
	questionId: string | number,
	scope: "current" | "7" | "30" | "90" = "current",
) {
	return apiRequest<QuestionAnalysis>(
		`/workspaces/${workspaceId}/question-plans/${questionId}/analysis?scope=${scope}`,
	);
}

export function createCleanroomQuestion(
	workspaceId: string | number,
	questionText: string,
	options?: {
		journey_stage?: string;
		role?: string;
		topic_tags?: string[];
		source_type?: string;
		source_reason?: string;
		template_variables?: string[];
	},
) {
	return apiRequest<CleanroomQuestion>(
		`/workspaces/${workspaceId}/question-plans`,
		{
			method: "POST",
			body: JSON.stringify({
				question_text: questionText,
				journey_stage: options?.journey_stage ?? "consideration",
				role: options?.role ?? "technical_lead",
				topic_tags: options?.topic_tags ?? [],
				importance: 4,
				is_brand_query: false,
				source_type: options?.source_type ?? "manual",
				source_reason: options?.source_reason,
				template_variables: options?.template_variables ?? [],
			}),
		},
	);
}

export function questionPlanAction(
	workspaceId: string | number,
	questionId: string | number,
	action: "approve" | "reject" | "deprecate",
	note?: string,
) {
	return apiRequest<CleanroomQuestion>(
		`/workspaces/${workspaceId}/question-plans/${questionId}/${action}`,
		{
			method: "POST",
			body: JSON.stringify({ note }),
		},
	);
}

export function mergeCleanroomQuestion(
	workspaceId: string | number,
	questionId: string | number,
	targetQuestionId: number,
	note?: string,
) {
	return apiRequest<CleanroomQuestion>(
		`/workspaces/${workspaceId}/question-plans/${questionId}/merge`,
		{
			method: "POST",
			body: JSON.stringify({ target_question_id: targetQuestionId, note }),
		},
	);
}

export function updateCleanroomQuestion(
	workspaceId: string | number,
	questionId: string | number,
	questionText: string,
) {
	return apiRequest<CleanroomQuestion>(
		`/workspaces/${workspaceId}/question-plans/${questionId}`,
		{
			method: "PATCH",
			body: JSON.stringify({ question_text: questionText }),
		},
	);
}

export function observeOfficialProvider(
	workspaceId: string | number,
	payload: {
		question_plan_id: number;
		provider_id?: number | null;
		repeat_index?: number;
		repeat_count?: number;
		observation_group_id?: string;
	},
) {
	return apiRequest<OfficialApiObservationResponse>(
		`/workspaces/${workspaceId}/observations/provider-web-search`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}

export function queueOfficialProviderObservation(
	workspaceId: string | number,
	payload: {
		question_plan_id: number;
		provider_id: number;
		repeat_index?: number;
		repeat_count?: number;
		observation_group_id?: string;
	},
) {
	return apiRequest<QueuedOfficialApiObservationResponse>(
		`/workspaces/${workspaceId}/observations/provider-web-search/queue`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}

export function getOfficialProviderObservationJob(
	workspaceId: string | number,
	jobId: number,
) {
	return apiRequest<OfficialApiObservationJobStatus>(
		`/workspaces/${workspaceId}/observation-jobs/${jobId}`,
	);
}

export function createOfficialProviderObservationBatch(
	workspaceId: string | number,
	payload: {
		provider_ids: number[];
		question_plan_ids: number[];
		repeat_count: number;
	},
) {
	return apiRequest<OfficialApiObservationBatch>(
		`/workspaces/${workspaceId}/observation-batches`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}

export function getOfficialProviderObservationBatch(
	workspaceId: string | number,
	batchId: number,
	options?: { taskPage?: number; taskPageSize?: number },
) {
	const params = new URLSearchParams();
	if (options?.taskPage) params.set("task_page", String(options.taskPage));
	if (options?.taskPageSize)
		params.set("task_page_size", String(options.taskPageSize));
	const suffix = params.size ? `?${params.toString()}` : "";
	return apiRequest<OfficialApiObservationBatch>(
		`/workspaces/${workspaceId}/observation-batches/${batchId}${suffix}`,
	);
}

export function getLatestOfficialProviderObservationBatch(
	workspaceId: string | number,
) {
	return apiRequest<OfficialApiObservationBatch>(
		`/workspaces/${workspaceId}/observation-batches/latest`,
	);
}

export function getOfficialProviderObservationBatches(
	workspaceId: string | number,
	options?: { page?: number; pageSize?: number },
) {
	const params = new URLSearchParams({
		page: String(options?.page ?? 1),
		page_size: String(options?.pageSize ?? 20),
	});
	return apiRequest<OfficialApiObservationBatchList>(
		`/workspaces/${workspaceId}/observation-batches?${params.toString()}`,
	);
}

export function getCleanroomEvidence(workspaceId: string | number) {
	return apiRequest<CleanroomEvidence[]>(`/workspaces/${workspaceId}/evidence`);
}

export function getBrowserAccounts(workspaceId: string | number) {
	return apiRequest<BrowserAccount[]>(
		`/workspaces/${workspaceId}/browser-accounts`,
	);
}

export function createBrowserAccount(
	workspaceId: string | number,
	payload: {
		alias: string;
		ego_task_space_id?: number | null;
		browser_profile_alias?: string | null;
		cohort?: "clean_baseline" | "real_user";
	},
) {
	return apiRequest<BrowserAccount>(
		`/workspaces/${workspaceId}/browser-accounts`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}

export function updateBrowserAccount(
	workspaceId: string | number,
	accountId: string | number,
	payload: {
		status: "onboarding" | "ready" | "reauth_required" | "disabled";
		health_note?: string | null;
		cohort?: "clean_baseline" | "real_user";
		browser_profile_alias?: string | null;
		session_fingerprint?: string | null;
	},
) {
	return apiRequest<BrowserAccount>(
		`/workspaces/${workspaceId}/browser-accounts/${accountId}`,
		{
			method: "PATCH",
			body: JSON.stringify(payload),
		},
	);
}

export function getLatestSamplingBatch(workspaceId: string | number) {
	return apiRequest<SamplingBatch | null>(
		`/workspaces/${workspaceId}/sampling-batches/latest`,
	);
}

export function createSamplingBatch(workspaceId: string | number) {
	return apiRequest<SamplingBatch>(
		`/workspaces/${workspaceId}/sampling-batches`,
		{
			method: "POST",
			body: JSON.stringify({
				account_count: 2,
				question_count: 3,
				repeat_count: 3,
			}),
		},
	);
}

export function getCleanroomActions(workspaceId: string | number) {
	return apiRequest<CleanroomAction[]>(`/workspaces/${workspaceId}/actions`);
}

export function getCleanroomActionOpportunities(workspaceId: string | number) {
	return apiRequest<CleanroomActionOpportunity[]>(`/workspaces/${workspaceId}/action-opportunities`);
}

export function discoverCleanroomActionOpportunities(
	workspaceId: string | number,
	payload: { batch_id?: number | null; question_plan_ids?: number[]; max_items?: number } = {},
) {
	return apiRequest<CleanroomActionOpportunity[]>(`/workspaces/${workspaceId}/action-opportunities/discover`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function selectCleanroomActionOpportunity(workspaceId: string | number, opportunityId: number) {
	return apiRequest<CleanroomAction>(`/workspaces/${workspaceId}/action-opportunities/${opportunityId}/select`, {
		method: "POST",
	});
}

export function createCleanroomContentBrief(
	workspaceId: string | number,
	actionId: number,
	payload: { audience?: string; intent?: string; asset_type?: string } = {},
) {
	return apiRequest<CleanroomContentBrief>(`/workspaces/${workspaceId}/actions/${actionId}/briefs`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function getCleanroomContentAssets(workspaceId: string | number, actionId: number, briefId: number) {
	return apiRequest<CleanroomContentAsset[]>(`/workspaces/${workspaceId}/actions/${actionId}/briefs/${briefId}/assets`);
}

export function queueCleanroomContentGeneration(
	workspaceId: string | number,
	actionId: number,
	briefId: number,
	payload: { provider_id: number; platform_key: "official_site" | "zhihu" | "wechat" | "xiaohongshu" },
) {
	return apiRequest<CleanroomContentGenerationJob>(`/workspaces/${workspaceId}/actions/${actionId}/briefs/${briefId}/generate`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function getCleanroomBrandFacts(workspaceId: string | number) {
	return apiRequest<CleanroomBrandFact[]>(
		`/workspaces/${workspaceId}/brand-facts`,
	);
}

export function getCleanroomContentAudits(workspaceId: string | number) {
	return apiRequest<CleanroomContentAudit[]>(
		`/workspaces/${workspaceId}/content-audits`,
	);
}

export function createCleanroomAction(
	workspaceId: string | number,
	payload: Omit<CleanroomAction, "id" | "workspace_id" | "status">,
) {
	return apiRequest<CleanroomAction>(`/workspaces/${workspaceId}/actions`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function updateCleanroomAction(
	workspaceId: string | number,
	actionId: string | number,
	payload: { status: "proposed" | "in_progress" | "verified" | "closed" },
) {
	return apiRequest<CleanroomAction>(
		`/workspaces/${workspaceId}/actions/${actionId}`,
		{
			method: "PATCH",
			body: JSON.stringify(payload),
		},
	);
}

export function createCleanroomBrandFact(
	workspaceId: string | number,
	payload: Omit<CleanroomBrandFact, "id" | "workspace_id" | "status">,
) {
	return apiRequest<CleanroomBrandFact>(
		`/workspaces/${workspaceId}/brand-facts`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}

export function createCleanroomContentAudit(
	workspaceId: string | number,
	payload: {
		title: string;
		body: string;
		source_urls: string[];
		target_url?: string | null;
	},
) {
	return apiRequest<CleanroomContentAudit>(
		`/workspaces/${workspaceId}/content-audits`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}

export function importYaoDeepSeekStage1(
	workspaceId: string | number,
	payload: {
		dataset: Record<string, unknown>;
		artifact_base_uri?: string | null;
		prompt_version?: string;
		target_run_id?: number;
	},
) {
	return apiRequest<CleanroomScorecard>(
		`/workspaces/${workspaceId}/imports/yao/deepseek-stage1`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}

export function importYaoDoubaoStage1(
	workspaceId: string | number,
	payload: {
		dataset: Record<string, unknown>;
		artifact_base_uri?: string | null;
		prompt_version?: string;
		target_run_id?: number;
	},
) {
	return apiRequest<CleanroomScorecard>(
		`/workspaces/${workspaceId}/imports/yao/doubao-stage1`,
		{
			method: "POST",
			body: JSON.stringify(payload),
		},
	);
}
