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

export type WorkspaceIntegrationSettings = {
	workspace_id: number;
	deepseek_api_key_configured: boolean;
	article_sync_mcp_server_path?: string | null;
	article_sync_mcp_token_configured: boolean;
	deepseek_updated_at?: string | null;
	article_sync_mcp_updated_at?: string | null;
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

export type ActionEvidenceSummary = Pick<
	CleanroomEvidence,
	| "id"
	| "question_plan_id"
	| "model_label"
	| "is_real_provider_evidence"
	| "brand_status"
	| "competitor_positions"
	| "source_items"
>;

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
	source_type: string;
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

export type AgentRuntime = {
	runtime_key: "local_codex";
	sdk_installed: boolean;
	sdk_version?: string | null;
	runtime_version?: string | null;
	ready: boolean;
	login_status: string;
	default_model?: string | null;
	available_models: string[];
	connection_status: "cold" | "warm";
	connected_since?: string | null;
	reuse_count: number;
	active_run_count: number;
	max_concurrent_runs: number;
	capacity_available: boolean;
	run_timeout_seconds: number;
	error?: string | null;
};

export type AgentRuntimeTest = {
	ok: boolean;
	runtime: AgentRuntime;
	latency_ms: number;
	thread_id?: string | null;
	error?: string | null;
};

export type CleanroomAgentRun = {
	id: number;
	workspace_id: number;
	action_id: number;
	job_id?: number | null;
	requested_by_user_id?: number | null;
	runtime_key: string;
	model?: string | null;
	codex_thread_id?: string | null;
	codex_turn_id?: string | null;
	status: string;
	stage: string;
	selected_platforms: string[];
	result_snapshot: Record<string, unknown>;
	error_code?: string | null;
	error_message?: string | null;
	cancel_requested_at?: string | null;
	started_at?: string | null;
	finished_at?: string | null;
	created_at: string;
	updated_at: string;
};

export type CleanroomAgentEvent = {
	id: number;
	workspace_id: number;
	agent_run_id: number;
	sequence: number;
	event_type: string;
	stage: string;
	message: string;
	detail: Record<string, unknown>;
	created_at: string;
};

export type CleanroomAgentProgressStage = {
	key: "preparing_context" | "researching_platform" | "researching_brand" | "adapting_platforms" | "awaiting_review";
	label: string;
	state: "waiting" | "running" | "done" | "waiting_human" | "failed";
	message?: string | null;
	event_sequence?: number | null;
	updated_at?: string | null;
};

export type CleanroomAgentProgressArtifact = {
	id: number;
	artifact_kind: string;
	sha256: string;
	size_bytes: number;
	created_at: string;
};

export type CleanroomAgentRunProgress = {
	run: CleanroomAgentRun;
	stages: CleanroomAgentProgressStage[];
	attempt_number: number;
	attempt_event_count: number;
	attempt_started_at?: string | null;
	progress_percent: number;
	elapsed_seconds: number;
	timeout_seconds: number;
	timeout_remaining_seconds?: number | null;
	event_count: number;
	events: CleanroomAgentEvent[];
	artifacts: CleanroomAgentProgressArtifact[];
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

export type CleanroomActionOpportunityScope = {
	latest_batch_id?: number | null;
	batches: Array<{
		id: number;
		status: string;
		created_at: string;
		completed_at?: string | null;
		eligible_evidence_count: number;
		model_keys: string[];
		question_plan_ids: number[];
	}>;
	models: Array<{ key: string; label: string }>;
	questions: Array<{ id: number; label: string }>;
	evidence_gate: string;
};

export type CleanroomOpportunityAnalysisRun = {
	job_id: number;
	workspace_id: number;
	batch_id: number;
	model_keys: string[];
	question_plan_ids: number[];
	status: "queued" | "running" | "succeeded" | "failed";
	stage: "queued" | "preparing" | "analyzing" | "complete" | "failed";
	evidence_count: number;
	result_count: number;
	no_action_count: number;
	input_fingerprint: string;
	codex_thread_id?: string | null;
	codex_turn_id?: string | null;
	analysis_summary?: string | null;
	error_message?: string | null;
	created_at: string;
	started_at?: string | null;
	finished_at?: string | null;
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
	created_at: string;
	updated_at: string;
};

export type CleanroomContentClaim = {
	id: number;
	content_asset_id: number;
	claim_key: string;
	claim_text: string;
	support_type: string;
	support_id?: number | null;
	source_url?: string | null;
	verification_status: string;
	introduced_by_model: boolean;
	review_note?: string | null;
};

export type CleanroomPlatformVariant = {
	id: number;
	workspace_id: number;
	content_asset_id: number;
	platform_key: string;
	version: number;
	policy_version: string;
	title: string;
	summary: string;
	body_markdown: string;
	tags: string[];
	category?: string | null;
	image_manifest: Array<Record<string, unknown>>;
	adaptation_contract: Record<string, unknown>;
	content_fingerprint: string;
	prompt_template_id?: number | null;
	prompt_hash?: string | null;
	status: string;
};

export type CleanroomContentReview = {
	id: number;
	workspace_id: number;
	subject_type: string;
	subject_id: number;
	review_type: string;
	verdict: string;
	checks: Record<string, unknown>;
	issues: Array<Record<string, unknown>>;
	reviewer_id?: number | null;
	created_at: string;
};

export type CleanroomContentReviewPackage = {
	asset: CleanroomContentAsset;
	claims: CleanroomContentClaim[];
	variants: CleanroomPlatformVariant[];
	reviews: CleanroomContentReview[];
	pending_claim_count: number;
	approved_platform_keys: string[];
	requires_sourced_brand_facts: boolean;
	available_sourced_brand_fact_count: number;
	sourced_brand_fact_count: number;
	sourced_brand_fact_ids: number[];
	unverified_brand_fact_count: number;
	used_unverified_brand_fact_count: number;
};

export type CleanroomContentLibraryItem = {
	asset: CleanroomContentAsset;
	action_id: number;
	action_title: string;
	action_stage: string;
	question_plan_id?: number | null;
	variants: CleanroomPlatformVariant[];
	pending_claim_count: number;
	available_sourced_brand_fact_count: number;
	sourced_brand_fact_count: number;
	unverified_brand_fact_count: number;
	used_unverified_brand_fact_count: number;
	brand_fact_verification_required: boolean;
	brand_fact_snapshot_stale: boolean;
	approved_platform_keys: string[];
	latest_review_verdict?: string | null;
	latest_review_note?: string | null;
	agent_run_id?: number | null;
	agent_run_status?: string | null;
	distribution_run_id?: number | null;
	distribution_status?: string | null;
	saved_draft_count: number;
	total_draft_targets: number;
	draft_targets: CleanroomDistributionTarget[];
	is_latest_version: boolean;
	latest_version_id: number;
	latest_version_number: number;
};

export type CleanroomDistributionTarget = {
	id: number;
	distribution_run_id: number;
	platform_variant_id?: number | null;
	platform_key: string;
	adapter_version: string;
	request_status: string;
	draft_readback_status: string;
	candidate_draft_url?: string | null;
	draft_url?: string | null;
	external_draft_id?: string | null;
	response_artifact_uri?: string | null;
	readback_artifact_uri?: string | null;
	waiting_human_reason?: string | null;
	blocked_reason?: string | null;
	last_error_code?: string | null;
	final_action_clicked: boolean;
	human_publish_status: string;
	public_url?: string | null;
	publication_verification_status: string;
	published_at?: string | null;
	published_by_user_id?: number | null;
};

export type CleanroomDistributionRun = {
	id: number;
	workspace_id: number;
	action_id?: number | null;
	content_asset_id?: number | null;
	requested_platforms: string[];
	stage: string;
	idempotency_key: string;
	status: string;
	targets: CleanroomDistributionTarget[];
};

export type CleanroomActionRetest = {
	id: number;
	action_id: number;
	workspace_id: number;
	status: string;
	baseline_batch_id?: number | null;
	retest_batch_id?: number | null;
	retest_queue_job_id?: number | null;
	scope_snapshot: Record<string, unknown>;
	baseline_metrics: Record<string, unknown>;
	retest_metrics: Record<string, unknown>;
	conclusion: string;
	measured_delta: Record<string, unknown>;
	batch?: OfficialApiObservationBatchSummary | null;
	started_at?: string | null;
	completed_at?: string | null;
};

export type CleanroomActionWorkbenchState = {
	agent_runs: CleanroomAgentRun[];
	review_packages: CleanroomContentReviewPackage[];
	distribution_runs: CleanroomDistributionRun[];
	retests: CleanroomActionRetest[];
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
	source_verification?: {
		status: "source_and_statement_verified";
		verification_mode?: "server_rendered_html" | "same_origin_public_javascript";
		verified_url: string;
		evidence_url?: string;
		status_code: number;
		content_type: string;
		source_sha256: string;
		source_page_sha256?: string;
		statement_sha256: string;
		size_bytes: number;
		truncated: boolean;
		redirect_count: number;
		verified_at: string;
	} | null;
	source_verification_failure?: {
		status: "failed";
		http_status: number;
		detail: string;
		attempted_at: string;
	} | null;
};

export type CleanroomBrandFactSourceCandidate = {
	statement: string;
	source_url: string;
	evidence_url: string;
	verification_mode: "server_rendered_html" | "same_origin_public_javascript";
	source_field: string;
	source_sha256: string;
	source_page_sha256: string;
	score: number;
};

export type CleanroomBrandFactSourceCandidates = {
	fact_id: number;
	source_url: string;
	checked_at: string;
	candidate_count: number;
	candidates: CleanroomBrandFactSourceCandidate[];
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

export type WebsiteAuditCheck = {
	label: string;
	status: "passed" | "failed";
	passed: boolean;
	detail: string;
	weight: number;
};

export type WebsiteAuditFinding = {
	code: string;
	severity: "high" | "medium" | "low";
	title: string;
	detail: string;
	recommendation: string;
};

export type WebsiteAudit = {
	id: number;
	workspace_id: number;
	requested_url: string;
	final_url?: string | null;
	status: "ready" | "needs_work" | "blocked";
	status_code?: number | null;
	content_type?: string | null;
	title?: string | null;
	meta_description?: string | null;
	canonical_url?: string | null;
	score: number;
	audit_version: string;
	checks: Record<string, WebsiteAuditCheck>;
	findings: WebsiteAuditFinding[];
	response_headers: Record<string, string>;
	raw_html_sha256?: string | null;
	raw_html_size: number;
	artifact_manifest: Array<{
		kind: "homepage" | "robots" | "sitemap";
		url: string;
		status_code?: number | null;
		content_type?: string | null;
		sha256?: string | null;
		size_bytes: number;
		truncated: boolean;
	}>;
	response_ms?: number | null;
	checked_at: string;
	created_at: string;
};

export type WebsiteAuditOverview = {
	website_url?: string | null;
	latest?: WebsiteAudit | null;
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

export function getWorkspaceIntegrations(workspaceId: string | number) {
	return apiRequest<WorkspaceIntegrationSettings>(`/workspaces/${workspaceId}/integrations`);
}

export function updateWorkspaceIntegrations(
	workspaceId: string | number,
	payload: {
		deepseek_api_key?: string;
		article_sync_mcp_server_path?: string;
		article_sync_mcp_token?: string;
	},
) {
	return apiRequest<WorkspaceIntegrationSettings>(`/workspaces/${workspaceId}/integrations`, {
		method: "PATCH",
		body: JSON.stringify(payload),
	});
}

export function testWorkspaceIntegration(
	workspaceId: string | number,
	integration: "deepseek" | "article_sync_mcp",
) {
	return apiRequest<{ integration: string; ok: boolean; message: string; latency_ms?: number; platforms?: ArticleSyncPlatform[] }>(
		`/workspaces/${workspaceId}/integrations/test`,
		{ method: "POST", body: JSON.stringify({ integration }) },
	);
}

export type ArticleSyncPlatform = { id: string; name: string; isAuthenticated: boolean; username?: string };

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

export function getActionEvidenceSummary(workspaceId: string | number) {
	return apiRequest<ActionEvidenceSummary[]>(
		`/workspaces/${workspaceId}/evidence/action-summary`,
	);
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

export function getCleanroomActionWorkbenchState(workspaceId: string | number) {
	return apiRequest<CleanroomActionWorkbenchState>(`/workspaces/${workspaceId}/action-workbench-state`);
}

export function getAgentRuntime(workspaceId: string | number) {
	return apiRequest<AgentRuntime>(`/workspaces/${workspaceId}/agent-runtime`);
}

export function testAgentRuntime(workspaceId: string | number) {
	return apiRequest<AgentRuntimeTest>(`/workspaces/${workspaceId}/agent-runtime/test`, {
		method: "POST",
	});
}

export function createCleanroomAgentRun(
	workspaceId: string | number,
	actionId: number,
	payload: { selected_platforms?: string[]; model?: string | null } = {},
) {
	return apiRequest<CleanroomAgentRun>(`/workspaces/${workspaceId}/actions/${actionId}/agent-runs`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function getActionAgentRuns(workspaceId: string | number, actionId: number) {
	return apiRequest<CleanroomAgentRun[]>(`/workspaces/${workspaceId}/actions/${actionId}/agent-runs`);
}

export function getAgentRunEvents(workspaceId: string | number, runId: number, after = 0) {
	return apiRequest<CleanroomAgentEvent[]>(`/workspaces/${workspaceId}/agent-runs/${runId}/events?after=${after}`);
}

export function getAgentRunProgress(workspaceId: string | number, runId: number) {
	return apiRequest<CleanroomAgentRunProgress>(`/workspaces/${workspaceId}/agent-runs/${runId}/progress`);
}

export function captureAgentRunVisuals(workspaceId: string | number, runId: number) {
	return apiRequest<CleanroomAgentRunProgress>(`/workspaces/${workspaceId}/agent-runs/${runId}/visual-captures`, {
		method: "POST",
	});
}

export function interruptCleanroomAgentRun(workspaceId: string | number, runId: number) {
	return apiRequest<CleanroomAgentRun>(`/workspaces/${workspaceId}/agent-runs/${runId}/interrupt`, {
		method: "POST",
	});
}

export function resumeCleanroomAgentRun(workspaceId: string | number, runId: number) {
	return apiRequest<CleanroomAgentRun>(`/workspaces/${workspaceId}/agent-runs/${runId}/resume`, {
		method: "POST",
	});
}

export function reviseCleanroomAgentRun(workspaceId: string | number, runId: number, contentAssetId: number) {
	return apiRequest<CleanroomAgentRun>(`/workspaces/${workspaceId}/agent-runs/${runId}/revise`, {
		method: "POST",
		body: JSON.stringify({ content_asset_id: contentAssetId }),
	});
}

export function getCleanroomActionOpportunityScope(workspaceId: string | number) {
	return apiRequest<CleanroomActionOpportunityScope>(`/workspaces/${workspaceId}/action-opportunities/scope`);
}

export function getCleanroomActionOpportunities(
	workspaceId: string | number,
	options: { batch_id?: number | null; model_key?: string | null; question_plan_id?: number | null; include_legacy?: boolean } = {},
) {
	const params = new URLSearchParams();
	if (options.batch_id) params.set("batch_id", String(options.batch_id));
	if (options.model_key) params.set("model_key", options.model_key);
	if (options.question_plan_id) params.set("question_plan_id", String(options.question_plan_id));
	params.set("include_legacy", String(options.include_legacy ?? false));
	const suffix = params.size ? `?${params.toString()}` : "";
	return apiRequest<CleanroomActionOpportunity[]>(`/workspaces/${workspaceId}/action-opportunities${suffix}`);
}

export function discoverCleanroomActionOpportunities(
	workspaceId: string | number,
	payload: { batch_id?: number | null; question_plan_ids?: number[]; model_keys?: string[]; max_items?: number } = {},
) {
	return apiRequest<CleanroomOpportunityAnalysisRun>(`/workspaces/${workspaceId}/action-opportunities/discover`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function getLatestCleanroomOpportunityAnalysis(
	workspaceId: string | number,
	options: { batch_id: number; model_key?: string | null; question_plan_id?: number | null },
) {
	const params = new URLSearchParams({ batch_id: String(options.batch_id) });
	if (options.model_key) params.set("model_key", options.model_key);
	if (options.question_plan_id) params.set("question_plan_id", String(options.question_plan_id));
	return apiRequest<CleanroomOpportunityAnalysisRun | null>(`/workspaces/${workspaceId}/action-opportunities/analysis-runs/latest?${params.toString()}`);
}

export function getCleanroomOpportunityAnalysis(workspaceId: string | number, jobId: number) {
	return apiRequest<CleanroomOpportunityAnalysisRun>(`/workspaces/${workspaceId}/action-opportunities/analysis-runs/${jobId}`);
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

export function getCleanroomContentReviewPackage(workspaceId: string | number, assetId: number) {
	return apiRequest<CleanroomContentReviewPackage>(`/workspaces/${workspaceId}/content-assets/${assetId}/review-package`);
}

export function updateCleanroomPlatformVariant(
	workspaceId: string | number,
	variantId: number,
	payload: { title: string; summary: string; body_markdown: string; tags?: string[]; category?: string | null },
) {
	return apiRequest<CleanroomPlatformVariant>(`/workspaces/${workspaceId}/platform-variants/${variantId}`, {
		method: "PATCH",
		body: JSON.stringify(payload),
	});
}

export function getCleanroomContentLibrary(workspaceId: string | number) {
	return apiRequest<CleanroomContentLibraryItem[]>(`/workspaces/${workspaceId}/content-library`);
}

export function decideCleanroomContentReview(
	workspaceId: string | number,
	assetId: number,
	payload: {
		verdict: "approved" | "changes_requested";
		confirmed_claim_ids?: number[];
		unverified_claim_ids?: number[];
		platform_keys?: string[];
		reviewed_platform_keys?: string[];
		note?: string | null;
	},
) {
	return apiRequest<CleanroomContentReviewPackage>(`/workspaces/${workspaceId}/content-assets/${assetId}/reviews`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function getCleanroomDistributionRuns(workspaceId: string | number, actionId?: number) {
	const suffix = actionId ? `?action_id=${actionId}` : "";
	return apiRequest<CleanroomDistributionRun[]>(`/workspaces/${workspaceId}/distribution-runs${suffix}`);
}

export function createCleanroomDistributionRun(
	workspaceId: string | number,
	payload: { content_asset_id: number; platform_keys: string[]; idempotency_key: string },
) {
	return apiRequest<CleanroomDistributionRun>(`/workspaces/${workspaceId}/distribution-runs`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function recordCleanroomDistributionClientResults(
	workspaceId: string | number,
	runId: number,
	targets: Array<{
		platform_key: string;
		request_status: "draft_link_returned" | "draft_saved" | "failed" | "cancelled";
		draft_url?: string | null;
		external_draft_id?: string | null;
		message?: string | null;
	}>,
) {
	return apiRequest<CleanroomDistributionRun>(`/workspaces/${workspaceId}/distribution-runs/${runId}/client-results`, {
		method: "POST",
		body: JSON.stringify({ targets }),
	});
}

export function confirmCleanroomHumanDraftReadback(
	workspaceId: string | number,
	runId: number,
	targetId: number,
) {
	return apiRequest<CleanroomDistributionRun>(
		`/workspaces/${workspaceId}/distribution-runs/${runId}/targets/${targetId}/human-draft-readback`,
		{
			method: "POST",
			body: JSON.stringify({ confirmed_visible: true }),
		},
	);
}

export function recordCleanroomHumanPublication(
	workspaceId: string | number,
	runId: number,
	targetId: number,
	publicUrl: string,
) {
	return apiRequest<CleanroomDistributionRun>(
		`/workspaces/${workspaceId}/distribution-runs/${runId}/targets/${targetId}/human-publication`,
		{
			method: "POST",
			body: JSON.stringify({ public_url: publicUrl }),
		},
	);
}

export function getCleanroomActionRetest(workspaceId: string | number, actionId: number) {
	return apiRequest<CleanroomActionRetest>(`/workspaces/${workspaceId}/actions/${actionId}/retest`);
}

export function createCleanroomActionRetest(workspaceId: string | number, actionId: number) {
	return apiRequest<CleanroomActionRetest>(`/workspaces/${workspaceId}/actions/${actionId}/retest`, {
		method: "POST",
	});
}

export function queueCleanroomContentGeneration(
	workspaceId: string | number,
	actionId: number,
	briefId: number,
	payload: { provider_id: number; platform_key: "official_site" | "zhihu" | "juejin" | "csdn" | "51cto" | "wechat" | "xiaohongshu" },
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

export function discoverCleanroomBrandFactSourceCandidates(
	workspaceId: string | number,
	factId: number,
) {
	return apiRequest<CleanroomBrandFactSourceCandidates>(
		`/workspaces/${workspaceId}/brand-facts/${factId}/source-candidates`,
		{ method: "POST" },
	);
}

export function getCleanroomContentAudits(workspaceId: string | number) {
	return apiRequest<CleanroomContentAudit[]>(
		`/workspaces/${workspaceId}/content-audits`,
	);
}

export function getLatestWebsiteAudit(workspaceId: string | number) {
	return apiRequest<WebsiteAuditOverview>(
		`/workspaces/${workspaceId}/website-audits/latest`,
	);
}

export function createWebsiteAudit(workspaceId: string | number) {
	return apiRequest<WebsiteAudit>(`/workspaces/${workspaceId}/website-audits`, {
		method: "POST",
	});
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

export function updateCleanroomBrandFact(
	workspaceId: string | number,
	factId: number,
	payload: Partial<Pick<CleanroomBrandFact, "title" | "statement" | "source_url" | "status">>,
) {
	return apiRequest<CleanroomBrandFact>(
		`/workspaces/${workspaceId}/brand-facts/${factId}`,
		{
			method: "PATCH",
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
