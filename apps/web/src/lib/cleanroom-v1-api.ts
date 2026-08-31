import { internalApiJson } from "@/lib/server-api";

export type CleanroomWorkspace = {
	id: number;
	company_id: number;
	slug: string;
	brand_name: string;
	brand_aliases: string[];
	website_url?: string | null;
	status: string;
};

export type GeoCollaborationMember = {
	id: number;
	name: string;
	email: string;
	role: WorkspaceMembership["role"];
	initial: string;
	bindings: Array<{
		provider: GeoCollaborationProvider;
		status: "verified" | "error";
		external_id_type: "user_id" | "open_id" | "union_id";
		external_display_name?: string | null;
		verified_at?: string | null;
	}>;
	notification_preferences: {
		provider_settings: Partial<Record<GeoCollaborationProvider, boolean>>;
		event_types: GeoCollaborationEventType[];
	};
	recent_deliveries: GeoCollaborationDelivery[];
};

export type GeoCollaborationProvider = "wecom" | "feishu" | "dingtalk";
export type GeoCollaborationEventType = "assigned" | "due_soon" | "approval" | "blocked" | "progress" | "manual_summary";
export type GeoCollaborationDelivery = {
	id: number;
	provider: GeoCollaborationProvider;
	connection_mode: "webhook" | "app";
	context_type: GeoCollaborationItem["context_type"];
	context_id: number;
	event_type: GeoCollaborationEventType;
	status: "sending" | "provider_accepted" | "failed";
	provider_message_ref?: string | null;
	error_code?: string | null;
	attempted_at: string;
	accepted_at?: string | null;
};

export type GeoCollaborationItem = {
	key: string;
	context_type: "action" | "alert" | "question" | "evidence";
	context_id: number;
	thread_id?: number | null;
	title: string;
	category: string;
	status: string;
	priority: string;
	assignee_user_id?: number | null;
	assignee_name?: string | null;
	start_at?: string | null;
	due_at?: string | null;
	participant_user_ids: number[];
	progress: number;
	target_progress: { completed: number; total: number };
	pending_approvals: number;
	evidence_count: number;
	question_ids: number[];
	model_keys: string[];
	blocked_note?: string | null;
	message_count: number;
	has_conversation: boolean;
	last_message_preview?: string | null;
	last_message_author_name?: string | null;
	mentioned_current_user: boolean;
	requires_attention: boolean;
	attention_reason?: string | null;
	unread_count: number;
	last_activity_at: string;
};

export type GeoCollaborationMessage = {
	id: number;
	kind: "comment" | "system";
	body: string;
	author?: GeoCollaborationMember | null;
	mention_user_ids: number[];
	attachment_refs: GeoCollaborationAttachmentRef[];
	created_at: string;
	delivery_state?: "sending" | "failed";
};

export type GeoCollaborationAttachmentRef = {
	label: string;
	url?: string | null;
	kind: "link" | "evidence" | "image" | "video" | "file" | "geo_object";
	attachment_id?: number;
	mime_type?: string;
	byte_size?: number;
	object_type?: "module" | "action" | "alert" | "question" | "content_asset" | "evidence";
	object_id?: number;
	object_key?: string;
	module_label?: string;
	title?: string;
	subtitle?: string;
	href?: string;
};

export type GeoCollaborationShareDraft = {
	kind: "module" | "action" | "alert" | "question" | "content_asset" | "evidence";
	object_id?: number;
	module_key?: string;
};

export type GeoCollaborationActivity = {
	id: string;
	kind: "system";
	event_type: string;
	from_stage?: string | null;
	to_stage?: string | null;
	detail: Record<string, unknown>;
	author?: GeoCollaborationMember | null;
	created_at: string;
};

export type GeoCollaborationChannel = {
	provider: GeoCollaborationProvider;
	label: string;
	status: "disconnected" | "configured" | "connected" | "error";
	display_name?: string | null;
	connection_mode?: "webhook" | "app" | null;
	configured_fields: string[];
	capabilities: Partial<Record<"group_broadcast" | "member_binding" | "direct_message" | "provider_acceptance" | "read_receipt", boolean>>;
	deep_link_base_url?: string | null;
	configured_at?: string | null;
	last_tested_at?: string | null;
	last_error_code?: string | null;
};

export type GeoCollaborationNotificationPreview = {
	recipient_user_id: number;
	event_type: GeoCollaborationEventType;
	snapshot: {
		title: string;
		category: string;
		status: string;
		progress: number;
		summary?: string;
		detail?: string;
		relative_url: string;
		note?: string;
	};
	providers: Array<{
		provider: GeoCollaborationProvider;
		label: string;
		ready: boolean;
		reason?: string | null;
		connection_mode?: "webhook" | "app" | null;
		identity_verified?: boolean | null;
		status_fact: string;
	}>;
	message_preview: string;
	external_write_performed: false;
};

export type GeoCollaborationCenter = {
	workspace_id: number;
	current_user_id: number;
	members: GeoCollaborationMember[];
	summary: { unread: number; mentions: number; pending_approvals: number; blocked: number };
	items: GeoCollaborationItem[];
	selected?: GeoCollaborationItem | null;
	selected_detail?: {
		rationale?: string | null;
		summary?: string | null;
		questions: Array<{ id: number; text: string }>;
		messages: GeoCollaborationMessage[];
		activity: GeoCollaborationActivity[];
	} | null;
	channels: GeoCollaborationChannel[];
};

export type WorkspaceMembership = {
	id: number;
	workspace_id: number;
	user_id: number;
	role: "owner" | "admin" | "operator" | "reviewer" | "viewer";
	status: string;
	joined_at: string;
	user: {
		id: number;
		company_id?: number | null;
		name: string;
		email: string;
		role: string;
		status: string;
	};
};

export type WorkspaceInvitation = {
	id: number;
	workspace_id: number;
	email: string;
	role: WorkspaceMembership["role"];
	status: string;
	invited_by_user_id: number;
	expires_at: string;
	accepted_at?: string | null;
	created_at: string;
};

export type WorkspaceInvitationCreated = WorkspaceInvitation & {
	invite_token: string;
	invite_path: string;
};

export type LocalAgentNode = {
	id: number;
	workspace_id: number;
	owner_user_id: number;
	name: string;
	hostname: string;
	platform: string;
	agent_version: string;
	status: string;
	execution_mode: "status_only";
	capabilities: Record<string, unknown>;
	health: Record<string, unknown>;
	last_seen_at: string;
	online: boolean;
	disabled_at?: string | null;
};

export type LocalAgentEnrollment = {
	workspace_id: number;
	enrollment_token: string;
	expires_at: string;
	command_hint: string;
};

export type QueueWorkerStatus = {
	workspace_id: number;
	online: boolean;
	status: "online" | "offline";
	worker_count: number;
	concurrency: number;
	pending_jobs: number;
	historical_jobs: number;
	running_jobs: number;
	stale_running_jobs: number;
	last_seen_at?: string | null;
	heartbeat_interval_seconds: number;
	offline_after_seconds: number;
	message: string;
	managed_service?: ManagedWorkerService | null;
	last_repair?: QueueWorkerRepairSummary | null;
};

export type ManagedWorkerService = {
	supported: boolean;
	installed: boolean;
	running: boolean;
	repository_match: boolean;
	state: string;
	pid?: number | null;
	label: string;
	message: string;
};

export type QueueWorkerRepairSummary = {
	status: string;
	action: string;
	recovered_jobs: number;
	exhausted_jobs: number;
	schedules_dispatched: number;
	schedules_failed: number;
	schedule_retries: number;
	schedule_retry_failures: number;
	repaired_at: string;
	message: string;
};

export type QueueWorkerRepair = {
	status: "online" | "recovering" | "needs_attention" | "unsupported";
	service_action: string;
	managed_service: ManagedWorkerService;
	recovered_jobs: number;
	exhausted_jobs: number;
	schedules_dispatched: number;
	schedules_failed: number;
	schedule_retries: number;
	schedule_retry_failures: number;
	worker: QueueWorkerStatus;
	message: string;
};

export type GeoObservationSchedule = {
	id: number;
	name: string;
	status: "active" | "paused";
	cadence: "daily" | "weekly" | "custom";
	weekdays: number[];
	local_time: string;
	timezone_name: string;
	provider_ids: number[];
	question_plan_ids: number[];
	repeat_count: number;
	scope_snapshot: Record<string, unknown>;
	scope_fingerprint: string;
	scope_version: number;
	next_run_at: string;
	last_run_at?: string | null;
};

export type GeoObservationScheduleRun = {
	id: number;
	schedule_id: number;
	window_key: string;
	status: string;
	batch_id?: number | null;
	baseline_batch_id?: number | null;
	scope_snapshot: Record<string, unknown>;
	scope_fingerprint: string;
	scheduled_for: string;
	started_at?: string | null;
	completed_at?: string | null;
	failure_reason?: string | null;
};

export type GeoChangeAlert = {
	id: number;
	alert_type: string;
	severity: "critical" | "warning" | "info";
	status: "open" | "confirmed" | "ignored";
	title: string;
	summary: string;
	baseline_batch_id?: number | null;
	current_batch_id?: number | null;
	scope_snapshot: Record<string, unknown>;
	completeness: Record<string, boolean | number>;
	metric_snapshot: Record<string, unknown>;
	evidence_ids: number[];
	suggested_action: Record<string, string>;
	converted_action_id?: number | null;
	created_at: string;
	resolved_at?: string | null;
};

export type GeoObservationAlertCenter = {
	summary: {
		active_schedules: number;
		today_runs: number;
		open_alerts: number;
		data_completeness?: number | null;
	};
	schedules: GeoObservationSchedule[];
	alerts: GeoChangeAlert[];
	runs: GeoObservationScheduleRun[];
};

export type WorkspaceIntegrationSettings = {
	workspace_id: number;
	deepseek_api_key_configured: boolean;
	article_sync_mcp_server_configured: boolean;
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
	influence_score: number;
	tier: "core" | "high" | "growth" | "unverified";
	tier_label: string;
	question_count: number;
	score_factors: {
		citation_frequency: number;
		answer_reach: number;
		model_breadth: number;
		question_breadth: number;
	};
	classification_reason: string;
	related_sources: Array<{
		key: string;
		label: string;
		shared_answer_count: number;
		shared_model_count: number;
		shared_question_count: number;
		strength_score: number;
		strength: "strong" | "medium" | "weak";
	}>;
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
	dispatch_enabled: boolean;
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

export type ActionExecutionTarget = {
	id: number;
	workspace_id: number;
	action_id: number;
	target_key: string;
	target_type: "platform" | "official_page" | "schema" | "external_source" | string;
	platform_key?: string | null;
	display_name: string;
	target_ref: string;
	delivery_status: string;
	recorded_delivery_status?: string | null;
	status_source: string;
	status_note?: string | null;
	distribution_target_id?: number | null;
	ordinal: number;
	metadata_json: Record<string, unknown>;
	completed_at?: string | null;
	completed_by_user_id?: number | null;
	verified_at?: string | null;
	created_at: string;
	updated_at: string;
};

export type ActionExecutionEvidence = {
	id: number;
	workspace_id: number;
	action_id: number;
	target_id: number;
	evidence_type: string;
	source_url?: string | null;
	artifact_uri?: string | null;
	sha256: string;
	verification_status: string;
	detail: Record<string, unknown>;
	submitted_by_user_id: number;
	verified_by_user_id?: number | null;
	submitted_at: string;
	verified_at?: string | null;
	supersedes_evidence_id?: number | null;
	created_at: string;
};

export type ActionExecutionApproval = {
	id: number;
	workspace_id: number;
	action_id: number;
	target_id?: number | null;
	approval_type: string;
	status: string;
	version: number;
	requested_by_user_id: number;
	reviewer_user_id: number;
	due_at: string;
	requested_at: string;
	decided_at?: string | null;
	note?: string | null;
	subject_fingerprint: string;
	created_at: string;
};

export type ActionExecutionDetail = CleanroomAction & {
	action_type: "article" | "official_site" | "structured_data" | "third_party_source" | "analysis" | "legacy_unclassified";
	deliverable_type: string;
	workflow_version: string;
	assignee_user_id?: number | null;
	due_at?: string | null;
	approval_due_at?: string | null;
	approval_requested_at?: string | null;
	blocked_reason_code?: string | null;
	blocked_note?: string | null;
	affected_question_ids: number[];
	affected_model_keys: string[];
	scope_fingerprint?: string | null;
	measurement_status: string;
	completed_target_count: number;
	retest_eligible_target_count: number;
	eligible_target_ids: number[];
	is_overdue: boolean;
	next_action: string;
	targets: ActionExecutionTarget[];
	approvals: ActionExecutionApproval[];
	evidence: ActionExecutionEvidence[];
};

export type ActionExecutionView = "all" | "mine" | "approvals" | "overdue_blocked";

export type CodexReasoningEffort = "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" | "ultra";

export type AgentRuntimeKey = "local_codex" | "claude_agent" | "hermes" | "openclaw";

export type AgentExecutionSelection = {
	runtime_key: AgentRuntimeKey;
	model: string | null;
	reasoning_effort: CodexReasoningEffort | null;
};

export type CodexExecutionSelection = AgentExecutionSelection;

export type AgentRuntimeModel = {
	id: string;
	display_name: string;
	description: string;
	default_reasoning_effort?: CodexReasoningEffort | null;
	supported_reasoning_efforts: CodexReasoningEffort[];
};

export type AgentRuntime = {
	runtime_key: AgentRuntimeKey;
	display_name: string;
	description: string;
	logo_path: string;
	transport: string;
	configuration_hint: string;
	sdk_installed: boolean;
	sdk_version?: string | null;
	runtime_version?: string | null;
	ready: boolean;
	login_status: string;
	default_model?: string | null;
	default_reasoning_effort?: CodexReasoningEffort | null;
	available_models: string[];
	model_options: AgentRuntimeModel[];
	connection_status: "cold" | "warm" | "configured";
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

export type AgentWorkspaceContext = {
	batch_id?: number | null;
	question_plan_id?: number | null;
	action_id?: number | null;
	model_keys: string[];
};

export type AgentWorkspaceEvent = {
	id: number;
	sequence: number;
	event_type: string;
	stage: string;
	message: string;
	detail: Record<string, unknown>;
	created_at: string;
};

export type AgentWorkspaceMessage = {
	id: number;
	sequence: number;
	role: "user" | "assistant";
	content: string;
	status: "queued" | "running" | "completed" | "failed";
	structured_payload: {
		answer?: string;
		rationale_summary?: string[];
		evidence_summary?: Array<{ label: string; detail: string }>;
		execution_plan?: Array<{ label: string; status: "ready" | "needs_user" | "blocked" }>;
		suggested_action?: { title: string; summary: string; action_type: string } | null;
		source_context?: {
			scope?: AgentWorkspaceContext;
			evidence_ids?: number[];
			evidence_count?: number;
		};
		linked_action_id?: number;
		needs_user?: boolean;
	};
	runtime_key?: AgentRuntimeKey | null;
	model?: string | null;
	job_id?: number | null;
	error_message?: string | null;
	events: AgentWorkspaceEvent[];
	created_at: string;
	updated_at: string;
};

export type AgentWorkspaceConversation = {
	id: number;
	workspace_id: number;
	title: string;
	status: "active" | "archived";
	runtime_key: AgentRuntimeKey;
	model?: string | null;
	reasoning_effort?: CodexReasoningEffort | null;
	context: AgentWorkspaceContext;
	last_message_status?: AgentWorkspaceMessage["status"] | null;
	needs_user: boolean;
	last_message_at?: string | null;
	created_at: string;
	updated_at: string;
	messages: AgentWorkspaceMessage[];
};

export type AgentWorkspaceContextOptions = {
	batches: Array<{ id: number; label: string; status: string; model_keys: string[] }>;
	questions: Array<{ id: number; label: string }>;
	actions: Array<{ id: number; label: string; status: string }>;
};

export type CleanroomAgentRun = {
	id: number;
	workspace_id: number;
	action_id: number;
	job_id?: number | null;
	requested_by_user_id?: number | null;
	runtime_key: string;
	model?: string | null;
	reasoning_effort?: CodexReasoningEffort | null;
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
	runtime_key: AgentRuntimeKey;
	model?: string | null;
	reasoning_effort?: CodexReasoningEffort | null;
	codex_thread_id?: string | null;
	codex_turn_id?: string | null;
	analysis_summary?: string | null;
	error_message?: string | null;
	created_at: string;
	started_at?: string | null;
	finished_at?: string | null;
};

export type WebsiteGapAnalysisRun = {
	job_id: number;
	workspace_id: number;
	batch_id: number;
	model_keys: string[];
	question_plan_ids: number[];
	status: "queued" | "running" | "succeeded" | "failed";
	stage: "queued" | "analyzing" | "complete" | "failed";
	evidence_count: number;
	result_count: number;
	recommendation_count: number;
	recommendations: Array<{
		priority: "high" | "medium" | "low";
		title: string;
		target_page: string;
		required_content: string[];
		reason: string;
		evidence_ids: number[];
		affected_models: string[];
		affected_question_plan_ids: number[];
		source_urls: string[];
	}>;
	input_fingerprint: string;
	runtime_key: AgentRuntimeKey;
	model?: string | null;
	reasoning_effort?: CodexReasoningEffort | null;
	skill_name: string;
	skill_sha256: string;
	official_metrics: Record<string, unknown>;
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
	image_manifest: Array<Record<string, unknown> & { content_path?: string }>;
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
	reviewer_name?: string | null;
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

export type GeoArticleAssistantTaskTarget = {
	target_id: number;
	platform_key:
		| "wechat" | "zhihu" | "juejin" | "51cto" | "csdn" | "bilibili"
		| "baijiahao" | "weibo" | "yuque" | "douban" | "sohu" | "xueqiu"
		| "cnblogs" | "oschina" | "segmentfault" | "imooc" | "woshipm" | "eastmoney";
	platform_variant_id: number;
	title: string;
	summary: string;
	body_markdown: string;
	body_html?: string;
	tags: string[];
	category?: string | null;
	image_manifest: Array<Record<string, unknown>>;
	content_fingerprint: string;
};

export type GeoArticleAssistantTask = {
	protocol_version: "geo-article-assistant.v1";
	task_token: string;
	run_id: number;
	workspace_id: number;
	action_id?: number | null;
	content_asset_id: number;
	issued_at: string;
	expires_at: string;
	content_fingerprint: string;
	targets: GeoArticleAssistantTaskTarget[];
};

export type CleanroomActionRetest = {
	id: number;
	action_id: number;
	workspace_id: number;
	round_index: number;
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

export type GeoResultsOverview = {
	workspace: { id: number; brand_name: string };
	generated_at: string;
	effect: {
		headline: string;
		description: string;
		total_actions: number;
		measured_actions: number;
		counts: Record<string, number>;
		historical: {
			mode: "historical_preview";
			label: string;
			warning: string;
			change_percentage_points?: number | null;
			complete_batch_count: number;
			batch_count: number;
			signal_counts: Record<string, number>;
			filters: { period_days: number; model_key?: string | null; question_plan_id?: number | null; question_plan_ids: number[] };
			model_options: Array<{ key: string; label: string }>;
			question_options: Array<{ id: number; label: string }>;
			series: Array<{
				batch_id: number;
				captured_at: string;
				mention_rate: number;
				impact_score: number;
				shortlist_rate: number;
				high_value_rate: number;
				eligible_samples: number;
				expected_samples: number;
				complete: boolean;
			}>;
		};
		actions: Array<{
			action_id: number;
			title: string;
			status: string;
			stage: string;
			question?: string | null;
			opportunity_type?: string | null;
			measurement_plan: {
				primary_metric: string;
				primary_metric_label: string;
				direction: "higher" | "lower";
				principle: string;
			};
			outcome: {
				status: "not_measured" | "insufficient_evidence" | "observed_improvement" | "stable_improvement" | "no_clear_change" | "regressed";
				label: string;
				confidence: "none" | "low" | "medium" | "high";
				confidence_label: string;
				comparable_rounds: number;
				model_agreement?: number | null;
				latest_model_directions?: Array<{ model_key: string; direction: string; before_rate: number; after_rate: number; delta: number }>;
				causal_warning?: string;
			};
			round_count: number;
			latest_retest_id?: number | null;
			latest_completed_at?: string | null;
			latest_delta: Record<string, unknown>;
			historical_signal?: {
				status: "no_history" | "history_up" | "history_down" | "history_flat";
				label: string;
				scope_quality: "none" | "same_scope" | "mixed_scope";
				scope_label: string;
				observation_count: number;
				before_positive?: number;
				before_total?: number;
				after_positive?: number;
				after_total?: number;
				delta_percentage_points?: number;
				first_batch_id?: number;
				latest_batch_id?: number;
				first_captured_at?: string;
				latest_captured_at?: string;
				attribution: "not_attributed";
				warning?: string;
				model_directions?: Array<{
					model_key: string;
					before_positive: number;
					before_total: number;
					after_positive: number;
					after_total: number;
					delta_percentage_points: number;
					direction: "up" | "down" | "flat";
				}>;
			};
			trend: Array<{
				kind: "baseline" | "retest";
				label: string;
				round_index: number;
				batch_id?: number | null;
				value?: number | null;
				captured_at?: string | null;
				conclusion?: string;
				comparable?: boolean;
			}>;
		}>;
	};
	roi: {
		status: "calculable" | "tracking" | "setup_required";
		status_label: string;
		currency?: string | null;
		total_cost_minor: number;
		direct_revenue_minor: number;
		assisted_revenue_minor: number;
		pipeline_value_minor: number;
		net_value_minor?: number | null;
		roi_percent?: number | null;
		quantities: Record<string, number>;
		missing_inputs: string[];
		formula: string;
		attribution_note: string;
		comparison: {
			cost_change_percent?: number | null;
			revenue_change_percent?: number | null;
			net_change_percent?: number | null;
			roi_change_percentage_points?: number | null;
			previous: {
				cost_minor: number;
				revenue_minor: number;
				net_value_minor?: number | null;
				roi_percent?: number | null;
			};
		};
		trend: Array<{
			date: string;
			cost_minor: number;
			revenue_minor: number;
			net_value_minor?: number | null;
			roi_percent?: number | null;
		}>;
		action_markers: Array<{ action_id: number; title: string; date: string }>;
		updated_at?: string | null;
		scope: { period_days: number; action_ids: number[]; action_label: string };
		decision: { status: string; headline: string; summary: string; next_action: string };
		readiness: {
			ready_count: number;
			total_count: number;
			percent: number;
			items: Array<{ key: string; label: string; status: "complete" | "missing"; evidence: string; next_action: string }>;
		};
		funnel: Array<{ key: string; label: string; value: number; kind: "money" | "quantity"; available: boolean }>;
		efficiency: {
			cost_per_referral_visit_minor?: number | null;
			cost_per_qualified_lead_minor?: number | null;
			pipeline_to_cost_multiple?: number | null;
			direct_revenue_to_cost_multiple?: number | null;
		};
		action_options: Array<{ id: number; label: string }>;
		action_portfolio: Array<{
			action_id: number;
			title: string;
			stage: string;
			effect_status: string;
			effect_label: string;
			comparable_rounds: number;
			cost_minor: number;
			direct_revenue_minor: number;
			pipeline_value_minor: number;
			net_value_minor?: number | null;
			roi_percent?: number | null;
			quantities: Record<string, number>;
			recommendation: string;
		}>;
		unallocated_entry_count: number;
		guardrails: string[];
		entry_count: number;
		entries: Array<{
			id: number;
			action_id?: number | null;
			metric_type: string;
			metric_label: string;
			amount_minor?: number | null;
			quantity?: number | null;
			currency?: string | null;
			attribution_type: string;
			source_type: string;
			source_label: string;
			source_reference?: string | null;
			evidence_note: string;
			verification_status: string;
			occurred_at: string;
			created_by_user_id: number;
			reverses_entry_id?: number | null;
			reversal_reason?: string | null;
			is_reversal: boolean;
			created_at: string;
		}>;
	};
};

export type GeoBusinessMetricImportRow = {
	id: number;
	row_number: number;
	record_id?: string | null;
	status: "valid" | "error" | "duplicate" | "imported";
	normalized: Record<string, string | number | null>;
	errors: Array<{ field: string; code: string; message: string }>;
	metric_entry_id?: number | null;
};

export type GeoBusinessMetricImportBatch = {
	id: number;
	file_name: string;
	file_sha256: string;
	status: "preflight" | "confirmed" | "reversed";
	mapping: {
		mapping?: Record<string, string>;
		file_errors?: Array<{ field: string; code: string; message: string }>;
	};
	total_rows: number;
	valid_rows: number;
	error_rows: number;
	duplicate_rows: number;
	imported_rows: number;
	confirmed_at?: string | null;
	reversed_at?: string | null;
	created_at: string;
	rows: GeoBusinessMetricImportRow[];
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
	return internalApiJson<T>(`/api/v1${path}`, init);
}

export function getCleanroomWorkspaces() {
	return apiRequest<CleanroomWorkspace[]>("/workspaces");
}

export function getGeoCollaborationCenter(
	workspaceId: string | number,
	selection?: { context_type: "action" | "alert" | "question" | "evidence"; context_id: number } | null,
) {
	const params = new URLSearchParams();
	if (selection) {
		params.set("context_type", selection.context_type);
		params.set("context_id", String(selection.context_id));
	}
	return apiRequest<GeoCollaborationCenter>(
		`/workspaces/${workspaceId}/collaboration${params.size ? `?${params}` : ""}`,
	);
}

export function createGeoCollaborationMessage(
	workspaceId: string | number,
	payload: {
		context_type: "action" | "alert" | "question" | "evidence";
		context_id: number;
		body: string;
		mention_user_ids: number[];
		attachment_refs?: Array<{ label: string; url?: string | null; kind: "link" | "evidence" | "file" }>;
		attachment_ids?: number[];
		shared_objects?: GeoCollaborationShareDraft[];
		idempotency_key: string;
	},
) {
	return apiRequest<{ id: number; thread_id: number; created_at: string; message: GeoCollaborationMessage }>(
		`/workspaces/${workspaceId}/collaboration/messages`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function updateGeoCollaborationWorkInfo(
	workspaceId: string | number,
	contextType: GeoCollaborationItem["context_type"],
	contextId: number,
	payload: {
		assignee_user_id: number | null;
		start_at: string | null;
		due_at: string | null;
		participant_user_ids: number[];
	},
) {
	return apiRequest<GeoCollaborationCenter>(
		`/workspaces/${workspaceId}/collaboration/contexts/${contextType}/${contextId}/work-info`,
		{ method: "PATCH", body: JSON.stringify(payload) },
	);
}

export function markGeoCollaborationThreadRead(
	workspaceId: string | number,
	threadId: number,
) {
	return apiRequest<{ thread_id: number; last_read_message_id?: number | null; read_at: string }>(
		`/workspaces/${workspaceId}/collaboration/threads/${threadId}/read`,
		{ method: "POST" },
	);
}

export function configureGeoCollaborationChannel(
	workspaceId: string | number,
	provider: GeoCollaborationChannel["provider"],
	payload: {
		connection_mode: "webhook" | "app";
		webhook_url?: string | null;
		corp_id?: string | null;
		app_id?: string | null;
		app_key?: string | null;
		agent_id?: string | null;
		app_secret?: string | null;
		display_name?: string | null;
		deep_link_base_url?: string | null;
	},
) {
	return apiRequest<GeoCollaborationChannel>(
		`/workspaces/${workspaceId}/collaboration/channels/${provider}`,
		{ method: "PUT", body: JSON.stringify({ provider, ...payload }) },
	);
}

export function bindGeoCollaborationMember(
	workspaceId: string | number,
	memberId: number,
	provider: GeoCollaborationProvider,
	payload: { external_user_id: string; external_id_type: "user_id" | "open_id" | "union_id" },
) {
	return apiRequest<GeoCollaborationMember>(
		`/workspaces/${workspaceId}/collaboration/members/${memberId}/bindings/${provider}`,
		{ method: "PUT", body: JSON.stringify(payload) },
	);
}

export function updateGeoCollaborationNotificationPreferences(
	workspaceId: string | number,
	memberId: number,
	payload: {
		provider_settings: Partial<Record<GeoCollaborationProvider, boolean>>;
		event_types: GeoCollaborationEventType[];
	},
) {
	return apiRequest<GeoCollaborationMember>(
		`/workspaces/${workspaceId}/collaboration/members/${memberId}/notification-preferences`,
		{ method: "PUT", body: JSON.stringify(payload) },
	);
}

export function previewGeoCollaborationNotification(
	workspaceId: string | number,
	payload: {
		recipient_user_id: number;
		context_type: GeoCollaborationItem["context_type"];
		context_id: number;
		event_type: GeoCollaborationEventType;
		providers: GeoCollaborationProvider[];
		note?: string;
	},
) {
	return apiRequest<GeoCollaborationNotificationPreview>(
		`/workspaces/${workspaceId}/collaboration/notifications/preview`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function sendGeoCollaborationNotification(
	workspaceId: string | number,
	payload: {
		recipient_user_id: number;
		context_type: GeoCollaborationItem["context_type"];
		context_id: number;
		event_type: GeoCollaborationEventType;
		providers: GeoCollaborationProvider[];
		note?: string;
		idempotency_key: string;
	},
) {
	return apiRequest<{ recipient_user_id: number; results: GeoCollaborationDelivery[]; truth_note: string }>(
		`/workspaces/${workspaceId}/collaboration/notifications/send`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function testGeoCollaborationChannel(
	workspaceId: string | number,
	provider: GeoCollaborationChannel["provider"],
) {
	return apiRequest<GeoCollaborationChannel>(
		`/workspaces/${workspaceId}/collaboration/channels/${provider}/test`,
		{ method: "POST" },
	);
}

export function getObservationAlertCenter(workspaceId: string | number) {
	return apiRequest<GeoObservationAlertCenter>(
		`/workspaces/${workspaceId}/observation-alert-center`,
	);
}

export function createObservationSchedule(
	workspaceId: string | number,
	payload: {
		name: string;
		cadence: "daily" | "weekly" | "custom";
		weekdays: number[];
		local_time: string;
		timezone_name: string;
		provider_ids: number[];
		question_plan_ids: number[];
		repeat_count: number;
	},
) {
	return apiRequest<GeoObservationSchedule>(`/workspaces/${workspaceId}/observation-schedules`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function updateObservationScheduleStatus(
	workspaceId: string | number,
	scheduleId: number,
	status: "active" | "paused",
) {
	return apiRequest<GeoObservationSchedule>(`/workspaces/${workspaceId}/observation-schedules/${scheduleId}`, {
		method: "PATCH",
		body: JSON.stringify({ status }),
	});
}

export function runObservationSchedule(workspaceId: string | number, scheduleId: number) {
	return apiRequest<GeoObservationScheduleRun>(`/workspaces/${workspaceId}/observation-schedules/${scheduleId}/run`, { method: "POST" });
}

export function updateChangeAlertStatus(
	workspaceId: string | number,
	alertId: number,
	status: "confirmed" | "ignored",
) {
	return apiRequest<GeoChangeAlert>(`/workspaces/${workspaceId}/change-alerts/${alertId}`, {
		method: "PATCH",
		body: JSON.stringify({ status }),
	});
}

export function convertChangeAlertToAction(workspaceId: string | number, alertId: number) {
	return apiRequest<{ action_id: number; created: boolean }>(`/workspaces/${workspaceId}/change-alerts/${alertId}/convert-to-action`, { method: "POST" });
}

export function getWorkspaceMembers(workspaceId: string | number) {
	return apiRequest<WorkspaceMembership[]>(`/workspaces/${workspaceId}/members`);
}

export function getWorkspaceInvitations(workspaceId: string | number) {
	return apiRequest<WorkspaceInvitation[]>(`/workspaces/${workspaceId}/invitations`);
}

export function createWorkspaceInvitation(
	workspaceId: string | number,
	payload: { email: string; role: WorkspaceMembership["role"]; expires_in_hours?: number },
) {
	return apiRequest<WorkspaceInvitationCreated>(`/workspaces/${workspaceId}/invitations`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function revokeWorkspaceInvitation(workspaceId: string | number, invitationId: number) {
	return apiRequest<{ message: string }>(`/workspaces/${workspaceId}/invitations/${invitationId}`, {
		method: "DELETE",
	});
}

export function updateWorkspaceMembership(
	workspaceId: string | number,
	membershipId: number,
	role: WorkspaceMembership["role"],
) {
	return apiRequest<WorkspaceMembership>(`/workspaces/${workspaceId}/members/${membershipId}`, {
		method: "PATCH",
		body: JSON.stringify({ role }),
	});
}

export function revokeWorkspaceMembership(workspaceId: string | number, membershipId: number) {
	return apiRequest<{ message: string }>(`/workspaces/${workspaceId}/members/${membershipId}`, {
		method: "DELETE",
	});
}

export function getLocalAgentNodes(workspaceId: string | number) {
	return apiRequest<LocalAgentNode[]>(`/workspaces/${workspaceId}/local-agent-nodes`);
}

export function getQueueWorkerStatus(workspaceId: string | number) {
	return apiRequest<QueueWorkerStatus>(`/workspaces/${workspaceId}/queue-worker-status`);
}

export function repairQueueWorker(workspaceId: string | number) {
	return apiRequest<QueueWorkerRepair>(`/workspaces/${workspaceId}/queue-worker-repair`, {
		method: "POST",
	});
}

export function createLocalAgentEnrollment(workspaceId: string | number) {
	return apiRequest<LocalAgentEnrollment>(`/workspaces/${workspaceId}/local-agent-enrollments`, {
		method: "POST",
	});
}

export function disableLocalAgentNode(workspaceId: string | number, nodeId: number) {
	return apiRequest<{ message: string }>(`/workspaces/${workspaceId}/local-agent-nodes/${nodeId}`, {
		method: "DELETE",
	});
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
		dateFrom?: string;
		dateTo?: string;
		modelKey?: string;
		modelKeys?: string[];
		scope?: "all" | "high";
		batchId?: number;
		batchIds?: number[];
		questionPlanIds?: number[];
	},
) {
	const params = new URLSearchParams();
	if (filters?.periodDays)
		params.set("period_days", String(filters.periodDays));
	if (filters?.dateFrom) params.set("date_from", filters.dateFrom);
	if (filters?.dateTo) params.set("date_to", filters.dateTo);
	if (filters?.modelKey && filters.modelKey !== "all")
		params.set("model_key", filters.modelKey);
	for (const value of filters?.modelKeys ?? []) params.append("model_keys", value);
	if (filters?.scope) params.set("scope", filters.scope);
	if (filters?.batchId) params.set("batch_id", String(filters.batchId));
	for (const value of filters?.batchIds ?? []) params.append("batch_ids", String(value));
	for (const value of filters?.questionPlanIds ?? []) params.append("question_plan_ids", String(value));
	const suffix = params.toString() ? `?${params.toString()}` : "";
	return apiRequest<CleanroomDecisionMap>(
		`/workspaces/${workspaceId}/decision-map${suffix}`,
	);
}

export function getCleanroomSourceMap(
	workspaceId: string | number,
	filters?: {
		periodDays?: number;
		dateFrom?: string;
		dateTo?: string;
		modelKey?: string;
		modelKeys?: string[];
		questionPlanId?: number;
		questionPlanIds?: number[];
		batchIds?: number[];
		limit?: number;
	},
) {
	const params = new URLSearchParams();
	if (filters?.periodDays)
		params.set("period_days", String(filters.periodDays));
	if (filters?.dateFrom) params.set("date_from", filters.dateFrom);
	if (filters?.dateTo) params.set("date_to", filters.dateTo);
	if (filters?.modelKey && filters.modelKey !== "all")
		params.set("model_key", filters.modelKey);
	for (const value of filters?.modelKeys ?? []) params.append("model_keys", value);
	if (filters?.questionPlanId)
		params.set("question_plan_id", String(filters.questionPlanId));
	for (const value of filters?.questionPlanIds ?? []) params.append("question_plan_ids", String(value));
	for (const value of filters?.batchIds ?? []) params.append("batch_ids", String(value));
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
		dateFrom?: string;
		dateTo?: string;
		modelKey?: string;
		modelKeys?: string[];
		questionPlanId?: number;
		questionPlanIds?: number[];
		batchIds?: number[];
		evidenceLimit?: number;
	},
) {
	const params = new URLSearchParams();
	if (filters?.periodDays)
		params.set("period_days", String(filters.periodDays));
	if (filters?.dateFrom) params.set("date_from", filters.dateFrom);
	if (filters?.dateTo) params.set("date_to", filters.dateTo);
	if (filters?.modelKey && filters.modelKey !== "all")
		params.set("model_key", filters.modelKey);
	for (const value of filters?.modelKeys ?? []) params.append("model_keys", value);
	if (filters?.questionPlanId)
		params.set("question_plan_id", String(filters.questionPlanId));
	for (const value of filters?.questionPlanIds ?? []) params.append("question_plan_ids", String(value));
	for (const value of filters?.batchIds ?? []) params.append("batch_ids", String(value));
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
		question_plan_ids?: number[];
	},
) {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(filters ?? {})) {
		if (key === "question_plan_ids" && Array.isArray(value)) {
			for (const questionId of value) params.append("question_plan_ids", String(questionId));
		} else if (typeof value === "string" && value) params.set(key, value);
	}
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

export function getActionExecutionList(
	workspaceId: string | number,
	view: ActionExecutionView = "all",
) {
	return apiRequest<ActionExecutionDetail[]>(
		`/workspaces/${workspaceId}/actions-v2?view=${view}`,
	);
}

export function getActionExecutionDetail(
	workspaceId: string | number,
	actionId: number,
) {
	return apiRequest<ActionExecutionDetail>(
		`/workspaces/${workspaceId}/actions/${actionId}`,
	);
}

export function acceptActionExecution(
	workspaceId: string | number,
	actionId: number,
	payload: { assignee_user_id: number; due_at: string },
) {
	return apiRequest<ActionExecutionDetail>(
		`/workspaces/${workspaceId}/actions/${actionId}/accept`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function blockActionExecution(
	workspaceId: string | number,
	actionId: number,
	payload: { reason_code: string; note: string },
) {
	return apiRequest<ActionExecutionDetail>(
		`/workspaces/${workspaceId}/actions/${actionId}/block`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function unblockActionExecution(
	workspaceId: string | number,
	actionId: number,
	payload: { note?: string | null } = {},
) {
	return apiRequest<ActionExecutionDetail>(
		`/workspaces/${workspaceId}/actions/${actionId}/unblock`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function transitionActionExecutionTarget(
	workspaceId: string | number,
	actionId: number,
	targetId: number,
	payload: { to_status: string; note?: string | null; idempotency_key: string },
) {
	return apiRequest<ActionExecutionDetail>(
		`/workspaces/${workspaceId}/actions/${actionId}/targets/${targetId}/transition`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function submitActionExecutionEvidence(
	workspaceId: string | number,
	actionId: number,
	targetId: number,
	payload: {
		evidence_type: string;
		source_url?: string | null;
		artifact_uri?: string | null;
		sha256?: string | null;
		detail?: Record<string, unknown>;
		idempotency_key: string;
		supersedes_evidence_id?: number | null;
	},
) {
	return apiRequest<ActionExecutionEvidence>(
		`/workspaces/${workspaceId}/actions/${actionId}/targets/${targetId}/evidence`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function requestActionExecutionApproval(
	workspaceId: string | number,
	actionId: number,
	payload: {
		target_id?: number | null;
		approval_type: string;
		reviewer_user_id: number;
		due_at: string;
		subject_fingerprint: string;
		note?: string | null;
	},
) {
	return apiRequest<ActionExecutionApproval>(
		`/workspaces/${workspaceId}/actions/${actionId}/approvals`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function decideActionExecutionApproval(
	workspaceId: string | number,
	actionId: number,
	approvalId: number,
	payload: { decision: "approved" | "changes_requested"; note?: string | null },
) {
	return apiRequest<ActionExecutionDetail>(
		`/workspaces/${workspaceId}/actions/${actionId}/approvals/${approvalId}/decide`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function selfApproveActionExecutionTarget(
	workspaceId: string | number,
	actionId: number,
	targetId: number,
) {
	return apiRequest<ActionExecutionDetail>(
		`/workspaces/${workspaceId}/actions/${actionId}/targets/${targetId}/self-approve`,
		{ method: "POST" },
	);
}

export function createTargetActionRetest(
	workspaceId: string | number,
	actionId: number,
	payload: { target_ids: number[]; idempotency_key: string },
) {
	return apiRequest<CleanroomActionRetest>(
		`/workspaces/${workspaceId}/actions/${actionId}/retests`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function getCleanroomActionWorkbenchState(workspaceId: string | number) {
	return apiRequest<CleanroomActionWorkbenchState>(`/workspaces/${workspaceId}/action-workbench-state`);
}

export function getAgentRuntime(workspaceId: string | number) {
	return apiRequest<AgentRuntime>(`/workspaces/${workspaceId}/agent-runtime`);
}

export function getAgentRuntimes(workspaceId: string | number) {
	return apiRequest<AgentRuntime[]>(`/workspaces/${workspaceId}/agent-runtimes`);
}

export function getAgentWorkspaceContextOptions(workspaceId: string | number) {
	return apiRequest<AgentWorkspaceContextOptions>(`/workspaces/${workspaceId}/agent-workspace/context-options`);
}

export function getAgentWorkspaceConversations(workspaceId: string | number) {
	return apiRequest<AgentWorkspaceConversation[]>(`/workspaces/${workspaceId}/agent-workspace/conversations`);
}

export function getAgentWorkspaceConversation(workspaceId: string | number, conversationId: number) {
	return apiRequest<AgentWorkspaceConversation>(`/workspaces/${workspaceId}/agent-workspace/conversations/${conversationId}`);
}

export function createAgentWorkspaceConversation(
	workspaceId: string | number,
	payload: { title?: string; context: AgentWorkspaceContext },
) {
	return apiRequest<AgentWorkspaceConversation>(`/workspaces/${workspaceId}/agent-workspace/conversations`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function updateAgentWorkspaceConversation(
	workspaceId: string | number,
	conversationId: number,
	payload: { title?: string; status?: "active" | "archived"; context?: AgentWorkspaceContext },
) {
	return apiRequest<AgentWorkspaceConversation>(`/workspaces/${workspaceId}/agent-workspace/conversations/${conversationId}`, {
		method: "PATCH",
		body: JSON.stringify(payload),
	});
}

export function sendAgentWorkspaceMessage(
	workspaceId: string | number,
	conversationId: number,
	payload: {
		content: string;
		runtime_key: AgentRuntimeKey | "auto";
		model?: string | null;
		reasoning_effort?: CodexReasoningEffort | null;
	},
) {
	return apiRequest<AgentWorkspaceConversation>(`/workspaces/${workspaceId}/agent-workspace/conversations/${conversationId}/messages`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function createAgentWorkspaceSuggestionAction(
	workspaceId: string | number,
	conversationId: number,
	messageId: number,
	payload: { title: string; expected_goal: string; assignee_user_id: number; due_at: string },
) {
	return apiRequest<{ action_id: number; created: boolean }>(
		`/workspaces/${workspaceId}/agent-workspace/conversations/${conversationId}/messages/${messageId}/action`,
		{ method: "POST", body: JSON.stringify(payload) },
	);
}

export function testAgentRuntime(workspaceId: string | number, runtimeKey: AgentRuntimeKey = "local_codex") {
	return apiRequest<AgentRuntimeTest>(`/workspaces/${workspaceId}/agent-runtimes/${runtimeKey}/test`, {
		method: "POST",
	});
}

export function createCleanroomAgentRun(
	workspaceId: string | number,
	actionId: number,
	payload: {
		selected_platforms?: string[];
		runtime_key?: AgentRuntimeKey;
		model?: string | null;
		reasoning_effort?: CodexReasoningEffort | null;
	} = {},
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
	options: { batch_id?: number | null; model_key?: string | null; question_plan_id?: number | null; action_id?: number | null; include_legacy?: boolean } = {},
) {
	const params = new URLSearchParams();
	if (options.batch_id) params.set("batch_id", String(options.batch_id));
	if (options.model_key) params.set("model_key", options.model_key);
	if (options.question_plan_id) params.set("question_plan_id", String(options.question_plan_id));
	if (options.action_id) params.set("action_id", String(options.action_id));
	params.set("include_legacy", String(options.include_legacy ?? false));
	const suffix = params.size ? `?${params.toString()}` : "";
	return apiRequest<CleanroomActionOpportunity[]>(`/workspaces/${workspaceId}/action-opportunities${suffix}`);
}

export function discoverCleanroomActionOpportunities(
	workspaceId: string | number,
	payload: {
		batch_id?: number | null;
		question_plan_ids?: number[];
		model_keys?: string[];
		max_items?: number;
		runtime_key?: AgentRuntimeKey;
		model?: string | null;
		reasoning_effort?: CodexReasoningEffort | null;
	} = {},
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

export function createWebsiteGapAnalysis(
	workspaceId: string | number,
	payload: {
		batch_id: number;
		question_plan_ids?: number[];
		model_keys?: string[];
		runtime_key?: AgentRuntimeKey;
		model?: string | null;
		reasoning_effort?: CodexReasoningEffort | null;
	},
) {
	return apiRequest<WebsiteGapAnalysisRun>(`/workspaces/${workspaceId}/website-gap-analyses`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function getLatestWebsiteGapAnalysis(
	workspaceId: string | number,
	options: { batch_id: number; model_key?: string | null; question_plan_id?: number | null },
) {
	const params = new URLSearchParams({ batch_id: String(options.batch_id) });
	if (options.model_key) params.set("model_key", options.model_key);
	if (options.question_plan_id) params.set("question_plan_id", String(options.question_plan_id));
	return apiRequest<WebsiteGapAnalysisRun | null>(`/workspaces/${workspaceId}/website-gap-analyses/latest?${params.toString()}`);
}

export function getWebsiteGapAnalysis(workspaceId: string | number, jobId: number) {
	return apiRequest<WebsiteGapAnalysisRun>(`/workspaces/${workspaceId}/website-gap-analyses/${jobId}`);
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
		request_status: "draft_link_returned" | "failed" | "cancelled";
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

export function issueGeoArticleAssistantTask(workspaceId: string | number, runId: number) {
	return apiRequest<GeoArticleAssistantTask>(`/workspaces/${workspaceId}/distribution-runs/${runId}/assistant-task`, {
		method: "POST",
	});
}

export function recordGeoArticleAssistantResults(
	workspaceId: string | number,
	runId: number,
	task: Pick<GeoArticleAssistantTask, "protocol_version" | "task_token" | "content_fingerprint">,
	targets: Array<{
		platform_key: string;
		request_status: "draft_link_returned" | "failed" | "cancelled";
		draft_url?: string | null;
		external_draft_id?: string | null;
		message?: string | null;
	}>,
) {
	return apiRequest<CleanroomDistributionRun>(`/workspaces/${workspaceId}/distribution-runs/${runId}/assistant-results`, {
		method: "POST",
		body: JSON.stringify({
			protocol_version: task.protocol_version,
			task_token: task.task_token,
			content_fingerprint: task.content_fingerprint,
			targets,
		}),
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

export function refreshCleanroomActionRetest(workspaceId: string | number, actionId: number) {
	return apiRequest<CleanroomActionRetest>(`/workspaces/${workspaceId}/actions/${actionId}/retest/refresh`, {
		method: "POST",
	});
}

export function getGeoResultsOverview(
	workspaceId: string | number,
	filters?: { period_days?: number; model_key?: string | null; model_keys?: string[]; batch_ids?: number[]; question_plan_id?: number | null; question_plan_ids?: number[]; roi_action_ids?: number[] },
) {
	const query = new URLSearchParams();
	if (filters?.period_days) query.set("period_days", String(filters.period_days));
	if (filters?.model_key) query.set("model_key", filters.model_key);
	for (const modelKey of filters?.model_keys ?? []) query.append("model_keys", modelKey);
	for (const batchId of filters?.batch_ids ?? []) query.append("batch_ids", String(batchId));
	if (filters?.question_plan_id) query.set("question_plan_id", String(filters.question_plan_id));
	for (const questionId of filters?.question_plan_ids ?? []) query.append("question_plan_ids", String(questionId));
	for (const actionId of filters?.roi_action_ids ?? []) query.append("roi_action_ids", String(actionId));
	const suffix = query.size ? `?${query.toString()}` : "";
	return apiRequest<GeoResultsOverview>(`/workspaces/${workspaceId}/results-overview${suffix}`);
}

export type GeoBusinessGoal = {
	id: number;
	workspace_id: number;
	title: string;
	metric_key: "shortlist_rate";
	metric_label: "候选进入率";
	baseline_value?: number | null;
	current_value?: number | null;
	target_value: number;
	progress_percent?: number | null;
	remaining_value?: number | null;
	start_at: string;
	due_at: string;
	owner_user_id?: number | null;
	owner_name?: string | null;
	status: "active";
	question_plan_ids: number[];
	model_keys: string[];
	action_ids: number[];
	scope_snapshot: {
		period_days?: number;
		batch_ids?: number[];
		model_keys?: string[];
		question_plan_ids?: number[];
		metric_contract?: string;
	};
	created_at: string;
	updated_at: string;
};

export type GeoBusinessGoalInput = {
	title: string;
	metric_key: "shortlist_rate";
	target_value: number;
	due_at: string;
	owner_user_id?: number | null;
	question_plan_ids: number[];
	model_keys: string[];
	action_ids: number[];
	period_days: number;
	batch_ids: number[];
};

export function getGeoBusinessGoal(workspaceId: string | number) {
	return apiRequest<GeoBusinessGoal | null>(`/workspaces/${workspaceId}/business-goal`);
}

export function upsertGeoBusinessGoal(
	workspaceId: string | number,
	payload: GeoBusinessGoalInput,
) {
	return apiRequest<GeoBusinessGoal>(`/workspaces/${workspaceId}/business-goal`, {
		method: "PUT",
		body: JSON.stringify(payload),
	});
}

export function createGeoBusinessMetric(
	workspaceId: string | number,
	payload: {
		action_id?: number | null;
		metric_type: "content_cost" | "labor_cost" | "distribution_cost" | "tool_cost" | "ai_referral_visit" | "qualified_lead" | "sales_opportunity" | "pipeline_value" | "won_revenue";
		amount?: string | null;
		quantity?: number | null;
		currency?: string | null;
		attribution_type: "direct" | "assisted" | "unallocated" | "not_applicable";
		source_type: "manual" | "manual_import" | "analytics" | "crm" | "finance";
		source_label: string;
		source_reference?: string | null;
		evidence_note: string;
		occurred_at: string;
		idempotency_key: string;
	},
) {
	return apiRequest<{ id: number; status: string }>(`/workspaces/${workspaceId}/business-metrics`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function reverseGeoBusinessMetric(
	workspaceId: string | number,
	entryId: number,
	payload: { reason: string; idempotency_key: string },
) {
	return apiRequest<{ id: number; status: string }>(`/workspaces/${workspaceId}/business-metrics/${entryId}/reverse`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function preflightGeoBusinessMetricCsv(
	workspaceId: string | number,
	payload: { file_name: string; csv_text: string; mapping?: Record<string, string> },
) {
	return apiRequest<GeoBusinessMetricImportBatch>(`/workspaces/${workspaceId}/business-metric-imports/preflight`, {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function getGeoBusinessMetricImports(workspaceId: string | number) {
	return apiRequest<GeoBusinessMetricImportBatch[]>(`/workspaces/${workspaceId}/business-metric-imports`);
}

export function getGeoBusinessMetricImport(workspaceId: string | number, batchId: number) {
	return apiRequest<GeoBusinessMetricImportBatch>(`/workspaces/${workspaceId}/business-metric-imports/${batchId}`);
}

export function confirmGeoBusinessMetricImport(workspaceId: string | number, batchId: number) {
	return apiRequest<GeoBusinessMetricImportBatch>(`/workspaces/${workspaceId}/business-metric-imports/${batchId}/confirm`, {
		method: "POST",
	});
}

export function reverseGeoBusinessMetricImport(
	workspaceId: string | number,
	batchId: number,
	reason: string,
) {
	return apiRequest<GeoBusinessMetricImportBatch>(`/workspaces/${workspaceId}/business-metric-imports/${batchId}/reverse`, {
		method: "POST",
		body: JSON.stringify({ reason }),
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
