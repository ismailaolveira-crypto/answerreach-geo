export const API_BASE_URL = typeof window === "undefined"
  ? process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
  : process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export type Company = {
  id: number;
  name: string;
  industry?: string | null;
  website_url?: string | null;
  description?: string | null;
  brand_aliases: string[];
  status: string;
};

export type GeoV1Observation = {
  id: number;
  task_id: number;
  project_id: number;
  target_question_id?: number | null;
  question_text?: string | null;
  provider_id?: number | null;
  provider_name: string;
  provider_type: string;
  collection_method: "api" | "web_search_api" | "web_ui_observation" | "mock" | "manual_import";
  is_real_evidence: boolean;
  status: string;
  brand_status: "absent" | "mentioned" | "shortlisted" | "recommended" | "cited" | "failed" | "insufficient";
  visibility_eligible: boolean;
  prompt_text: string;
  answer_summary?: string | null;
  raw_answer: string;
  collected_at?: string | null;
  confidence?: number | null;
  citation_count: number;
  owned_or_placed_citation_count: number;
  competitors: string[];
  review?: {
    id: number;
    crawl_result_id: number;
    reviewer_user_id?: number | null;
    company_mentioned?: boolean | null;
    company_shortlisted?: boolean | null;
    company_recommended?: boolean | null;
    claim_accuracy: string;
    citation_valid?: boolean | null;
    note?: string | null;
  } | null;
};

export type GeoV1DecisionMap = {
  project_id: number;
  company_name: string;
  metrics: Array<{ key: string; label: string; value: number; help_text: string }>;
  questions: Array<{ id: number; question_text: string; journey_stage: string; contains_brand: boolean; counts_for_visibility: boolean; visibility_eligible: boolean }>;
  providers: Array<{ id: number; name: string; provider_type: string }>;
  cells: Array<{ question_id: number; provider_id?: number | null; observation_id?: number | null; brand_status: string; collection_method?: string | null; is_real_evidence: boolean; collected_at?: string | null }>;
  pending_action_count: number;
  data_notice: string;
};

export type GeoV1Action = {
  id: number;
  project_id: number;
  target_question_id?: number | null;
  source_result_ids: number[];
  title: string;
  category: string;
  priority: "high" | "medium" | "low";
  status: string;
  rationale: string;
  hypothesis?: string | null;
  target_url?: string | null;
  owner?: string | null;
  change_summary?: string | null;
  implemented_at?: string | null;
  verification_result_id?: number | null;
  verification_summary?: string | null;
  concluded_at?: string | null;
  question_text?: string | null;
};

export type GeoV1BrandClaim = {
  id: number;
  project_id: number;
  title: string;
  claim_text: string;
  category: string;
  source_url?: string | null;
  status: string;
  valid_from?: string | null;
  valid_until?: string | null;
  owner?: string | null;
};

export type User = {
  id: number;
  company_id?: number | null;
  name: string;
  email: string;
  phone?: string | null;
  role: string;
  status: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  user: User;
};

export type Project = {
  id: number;
  company_id: number;
  name: string;
  description?: string | null;
  target_industry?: string | null;
  target_audience?: string | null;
  status: string;
  target_question_count?: number;
  keyword_count?: number;
  competitor_count?: number;
  content_asset_count?: number;
  placement_count?: number;
  diagnostic_readiness_score?: number;
  diagnostic_readiness_status?: string;
  diagnostic_readiness_checks?: Array<{
    key: string;
    label: string;
    current: number;
    required: number;
    ok: boolean;
    help_text: string;
  }>;
};

export type ProjectStageGoal = {
  id: number;
  project_id: number;
  title: string;
  metric_key: string;
  target_value: number;
  baseline_value: number;
  due_at?: string | null;
  owner?: string | null;
  status: string;
  note?: string | null;
  current_value: number;
  progress_rate: number;
  remaining_value: number;
  risk_level: string;
  review_summary?: string | null;
  recommendations: string[];
  suggested_actions: Array<{
    action_type: string;
    label: string;
    reason: string;
    priority: string;
  }>;
  due_days_remaining?: number | null;
  active_alert_type?: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectOperatingTrendPoint = {
  date: string;
  maturity_score: number;
  health_score: number;
  answer_count: number;
  browser_observation_count: number;
  recommendation_rate: number;
  approved_content_count: number;
  published_placement_count: number;
  accepted_delivery_count: number;
};

export type ProjectOperatingTrends = {
  project_id: number;
  days: number;
  points: ProjectOperatingTrendPoint[];
};

export type ProjectOperationalReadiness = {
  project_id: number;
  status: "ready" | "partial" | "blocked" | string;
  summary: string;
  ok_count: number;
  check_count: number;
  ready_platform_count: number;
  required_platform_count: number;
  platforms: Array<{
    key: string;
    label: string;
    configured: boolean;
    active: boolean;
    latest_test_ok: boolean;
    project_result_count: number;
    ready: boolean;
    provider_ids: number[];
    blockers: string[];
  }>;
  checks: Array<{
    key: string;
    label: string;
    ok: boolean;
    detail: string;
    next_action?: string | null;
  }>;
  metrics: Record<string, number>;
  updated_at: string;
};

export type ProjectStageGoalActionResult = {
  action_type: string;
  status: string;
  message: string;
  resource_type?: string | null;
  resource_id?: number | null;
  resource_url?: string | null;
  detail: Record<string, unknown>;
};

export type DiagnosticRunResult = {
  task_id: number;
  task_status: string;
  task_url: string;
  report_id?: number | null;
  report_url?: string | null;
  action_goal_count: number;
  provider_count: number;
  target_question_count: number;
  keyword_count: number;
  prompt_count: number;
  expected_call_count: number;
  estimated_total_tokens: number;
  estimated_cost: number;
  currency: string;
  result_count: number;
  delivery_readiness_status?: string | null;
  delivery_readiness_score?: number | null;
  warnings: string[];
  blockers: string[];
};

export type ProjectStageGoalTimelineItem = {
  event_type: string;
  title: string;
  message?: string | null;
  resource_type?: string | null;
  resource_id?: number | null;
  resource_url?: string | null;
  status?: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export type ProjectMvpStatusAction = {
  action_type: string;
  status: string;
  message: string;
  resource_type?: string | null;
  resource_id?: number | null;
  resource_url?: string | null;
  detail: Record<string, unknown>;
  created_at?: string | null;
};

export type ProjectMvpStatus = {
  source: "api";
  generated_at: string;
  ok: boolean;
  user_email: string;
  company_id: number;
  project_id: number;
  project_url: string;
  crawl_task_id?: number | null;
  report_ids: number[];
  latest_report_url?: string | null;
  compare_url?: string | null;
  delivery_package_url: string;
  public_share_url?: string | null;
  provider_summary: {
    total?: number;
    ready?: number;
    real_ready?: number;
    real_collection_ready?: number;
    mock_ready?: number;
    web_search_ready?: number;
    has_real_provider?: boolean;
    has_web_search_provider?: boolean;
    mode?: string;
  };
  providers: Array<{
    provider_id: number;
    name: string;
    provider_type: string;
    model_name: string;
    status: string;
    ready: boolean;
    auth_ready: boolean;
    supports_web_search: boolean;
    access_method: string;
    search_mode: string;
    search_access_status: string;
    collection_ready: boolean;
    collection_blocker?: string | null;
    latest_test_ok?: boolean | null;
    latest_test_error?: string | null;
    project_total_task_count: number;
    project_success_task_count: number;
    project_failed_task_count: number;
    project_result_count: number;
    project_usage_record_count: number;
    project_total_tokens: number;
    project_latest_task_id?: number | null;
    project_latest_task_status?: string | null;
    project_latest_task_error_message?: string | null;
    project_latest_result_id?: number | null;
    project_latest_result_collected_at?: string | null;
    missing: string[];
    warnings: string[];
    recommendations: string[];
  }>;
  crawl_health?: {
    status: string;
    ok: boolean;
    total_tasks: number;
    pending_tasks: number;
    running_tasks: number;
    success_tasks: number;
    failed_tasks: number;
    latest_task_id?: number | null;
    latest_task_status?: string | null;
    latest_task_type?: string | null;
    latest_error_message?: string | null;
    latest_result_count: number;
    total_result_count: number;
    reason?: string | null;
    next_action_label?: string | null;
    next_action_type?: string | null;
    next_action_url?: string | null;
  } | null;
  schedule_status?: {
    ok: boolean;
    status: string;
    active_schedule_count: number;
    hourly_schedule_count: number;
    due_schedule_count: number;
    latest_schedule_id?: number | null;
    latest_schedule_name?: string | null;
    latest_schedule_type?: string | null;
    latest_interval_hours?: number | null;
    latest_provider_count: number;
    latest_target_question_count: number;
    latest_keyword_count: number;
    latest_last_run_at?: string | null;
    latest_next_run_at?: string | null;
    next_action_label: string;
    next_action_type: string;
    next_action_url?: string | null;
  } | null;
  content_delivery?: {
    ok: boolean;
    latest_draft_id?: number | null;
    latest_review_id?: number | null;
    latest_review_score?: number | null;
    latest_review_grade?: string | null;
    approved_draft_count: number;
    planned_placement_count: number;
    published_delivery_count: number;
    active_share_count: number;
    accepted_delivery_count: number;
    latest_placement_id?: number | null;
    latest_share_id?: number | null;
    latest_share_token?: string | null;
    latest_access_log_id?: number | null;
    next_action_label: string;
    next_action_type: string;
    next_action_url?: string | null;
  } | null;
  stage_goal: {
    goal_id?: number | null;
    goal_status: string;
    action_results: ProjectMvpStatusAction[];
    placement_id?: number | null;
    share_id?: number | null;
    share_token?: string | null;
    access_log_id?: number | null;
    review_status: string;
    metric_deltas: Record<string, number>;
    delivery_status: string;
  };
  checks: Array<{
    check: string;
    ok: boolean;
    reason?: string | null;
    next_action_label?: string | null;
    next_action_type?: string | null;
    next_action_url?: string | null;
    status?: string | null;
    total_score?: number | null;
    maturity_level?: string | null;
    event_count?: number | null;
    deliverable_count?: number | null;
    metric_deltas?: Record<string, number> | null;
  }>;
};

export type TargetQuestion = {
  id: number;
  project_id: number;
  question_text: string;
  question_type: string;
  priority: number;
  status: string;
};

export type Keyword = {
  id: number;
  project_id: number;
  keyword: string;
  keyword_type: string;
  priority: number;
  status: string;
};

export type Competitor = {
  id: number;
  project_id: number;
  name: string;
  aliases: string[];
  website_url?: string | null;
  description?: string | null;
  status: string;
};

export type CrawlResult = {
  id: number;
  task_id: number;
  project_id: number;
  target_question_id?: number | null;
  keyword_id?: number | null;
  provider_id?: number | null;
  prompt_text: string;
  raw_answer: string;
  answer_summary?: string | null;
  status: string;
  collected_at?: string | null;
};

export type CrawlResultDetail = CrawlResult & {
  analysis?: {
    company_mentioned: boolean;
    company_recommended: boolean;
    company_rank?: number | null;
    sentiment: string;
    confidence: number;
    analysis_json: Record<string, unknown>;
  } | null;
  mentioned_entities: Array<{
    entity_name: string;
    entity_type: string;
    is_company: boolean;
    is_competitor: boolean;
    mention_count: number;
    recommendation_rank?: number | null;
  }>;
  citation_sources: Array<{
    source_title?: string | null;
    source_url?: string | null;
    source_domain?: string | null;
    source_type: string;
    is_owned: boolean;
    is_placed: boolean;
    crawlable_score: number;
    ai_readiness_score: number;
  }>;
};

export type BrowserObservation = CrawlResult & {
  report_id?: number | null;
  platform_name?: string | null;
  observation_url?: string | null;
  screenshot_url?: string | null;
  observer_name?: string | null;
  note?: string | null;
  source_count: number;
  screenshot_evidence_count: number;
};

export type BrowserObservationCreatePayload = {
  provider_id?: number;
  report_id?: number;
  target_question_id?: number;
  keyword_id?: number;
  platform_name?: string;
  prompt_text: string;
  raw_answer: string;
  answer_summary?: string;
  source_urls?: string[];
  screenshot_url?: string;
  observation_url?: string;
  observer_name?: string;
  note?: string;
};

export type BrowserObservationBulkCreateResult = {
  created_count: number;
  result_ids: number[];
  source_count: number;
  screenshot_evidence_count: number;
  results: CrawlResultDetail[];
};

export type CrawlTask = {
  id: number;
  project_id: number;
  task_type: string;
  schedule_type: string;
  provider_ids: number[];
  target_question_ids: number[];
  keyword_ids: number[];
  sample_runs_per_prompt: number;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
};

export type CrawlTaskEstimate = {
  provider_count: number;
  real_provider_count: number;
  target_question_count: number;
  keyword_count: number;
  prompt_count: number;
  total_call_count: number;
  estimated_prompt_tokens: number;
  estimated_completion_tokens: number;
  estimated_total_tokens: number;
  estimated_cost: number;
  currency: string;
  cost_configured_provider_count: number;
  scope_mode: string;
  providers: Array<{
    id: number;
    name: string;
    provider_type: string;
    is_real: boolean;
    collection_ready: boolean;
    cost_configured: boolean;
    estimated_cost: number;
    currency: string;
  }>;
  blockers: string[];
  warnings: string[];
};

export type CrawlSchedule = {
  id: number;
  project_id: number;
  name: string;
  schedule_type: string;
  interval_hours: number;
  provider_ids: number[];
  target_question_ids: number[];
  keyword_ids: number[];
  sample_runs_per_prompt: number;
  status: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_created_task_id?: number | null;
};

export type CrawlScheduleRunResult = {
  checked_at: string;
  due_schedule_count: number;
  task_ids: number[];
};

export type QueueJob = {
  id: number;
  job_type: string;
  status: string;
  priority: number;
  payload_json: Record<string, unknown>;
  attempts: number;
  max_attempts: number;
  scheduled_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type QueueJobListResponse = {
  summary: {
    total: number;
    pending: number;
    running: number;
    success: number;
    failed: number;
  };
  jobs: QueueJob[];
};

export type QueueJobRunResult = {
  ran: boolean;
  job?: QueueJob | null;
  message: string;
};

export type QueueReadyRunResult = {
  checked_at: string;
  created_task_ids: number[];
  ran_job_ids: number[];
  ran_job_count: number;
  success_job_count: number;
  failed_job_count: number;
  pending_job_count: number;
  message: string;
};

export type ReviewRule = {
  id: number;
  rule_key: string;
  name: string;
  description?: string | null;
  applies_to: string;
  max_score: number;
  weight: number;
  checks_json: Record<string, unknown>;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
};

export type ReportTemplate = {
  id: number;
  template_key: string;
  name: string;
  description?: string | null;
  applies_to: string;
  sections_json: Array<Record<string, unknown>>;
  scoring_json: Record<string, unknown>;
  delivery_checks_json: Array<Record<string, unknown>>;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
};

export type LLMProviderTestResult = {
  id?: number | null;
  provider_id: number;
  actor_user_id?: number | null;
  ok: boolean;
  prompt_text: string;
  company_name?: string | null;
  industry?: string | null;
  answer_summary?: string | null;
  raw_answer_preview?: string | null;
  error_message?: string | null;
  latency_ms?: number | null;
  created_at?: string | null;
};

export type LLMProviderCollectionSummary = {
  provider_id: number;
  collection_ready: boolean;
  collection_blocker?: string | null;
  diagnostic_ready: boolean;
  latest_test_ok?: boolean | null;
  latest_test_error?: string | null;
  latest_test_created_at?: string | null;
  total_task_count: number;
  success_task_count: number;
  failed_task_count: number;
  result_count: number;
  usage_record_count: number;
  total_tokens: number;
  latest_task_id?: number | null;
  latest_task_project_id?: number | null;
  latest_task_type?: string | null;
  latest_task_status?: string | null;
  latest_task_started_at?: string | null;
  latest_task_finished_at?: string | null;
  latest_task_error_message?: string | null;
  latest_result_id?: number | null;
  latest_result_project_id?: number | null;
  latest_result_collected_at?: string | null;
};

export type ProviderNetworkCheck = {
  available: boolean;
  ok?: boolean | null;
  verification_method?: string;
  provider_ids?: number[] | null;
  output?: string;
  created_at?: string;
  message?: string;
  safety?: {
    api_keys_used?: boolean;
    chat_completions_called?: boolean;
  };
  results: Array<{
    provider_id: number;
    name: string;
    provider_type?: string;
    model_name?: string;
    api_base_url?: string | null;
    scheme?: string;
    host?: string;
    port?: number;
    ok: boolean;
    dns_ok?: boolean;
    tcp_ok?: boolean;
    tls_ok?: boolean;
    error_stage?: string | null;
    error?: string | null;
    latency_ms?: number;
  }>;
};

export type CrawlTaskLog = {
  id: number;
  task_id: number;
  project_id: number;
  level: string;
  message: string;
  detail_json: Record<string, unknown>;
  created_at: string;
};

export type SearchMetrics = {
  project_id: number;
  total_answers: number;
  company_mentions: number;
  company_recommendations: number;
  competitor_mentions: number;
  company_mention_rate: number;
  company_recommendation_rate: number;
  competitor_mention_rate: number;
  top_competitors: Array<{ name: string; mentions: number }>;
  provider_breakdown: Array<{ provider_id: number | null; answers: number }>;
};

export type MaturityReport = {
  id: number;
  project_id: number;
  title: string;
  total_score: number;
  maturity_level: string;
  summary?: string | null;
  report_json: {
    company?: string;
    competitive_analysis_document?: {
      version: number;
      generated_at: string;
      scope: {
        project_id: number;
        report_id: number;
        task_id: number;
        answer_count: number;
        question_count: number;
        samples_per_question: number;
        evidence_type: string;
      };
      executive_findings: string[];
      company_mentions: Array<{
        result_id: number;
        question_id: number;
        question: string;
        sample_run: number;
        recommended: boolean;
        rank?: number | null;
        context: string;
      }>;
      company_question_summary: Array<{
        question_id: number;
        question: string;
        sample_runs: number[];
        interpretation: string;
      }>;
      observation_plan: Array<{
        question_id: number;
        question: string;
        priority: string;
        platforms: string[];
        status: string;
        reason: string;
        required_evidence: string[];
      }>;
      competitors: Array<{
        name: string;
        answer_mentions: number;
        mention_count: number;
        recommendation_count: number;
        samples: Array<{
          result_id: number;
          question_id: number;
          question: string;
          sample_run: number;
          mention_count: number;
          rank?: number | null;
          context: string;
          claimed_source_urls: string[];
        }>;
      }>;
      source_leads: Array<{
        domain: string;
        url: string;
        occurrences: number;
        question_ids: number[];
        http_status: number;
        verification_note: string;
        lineage_status: string;
      }>;
      source_summary: {
        record_count: number;
        unique_url_count: number;
        all_from_question_ids: number[];
        company_official_source_count: number;
        lineage_verified_count: number;
        reachable_url_count: number;
        answers_with_claimed_urls: number;
        answers_without_claimed_urls: number;
      };
      article_plan: Array<{
        priority: string;
        platform: string;
        title: string;
        target_questions: number[];
        basis: string;
        must_include: string;
      }>;
      caveats: string[];
      markdown?: string;
    };
    scope?: {
      crawl_task_id?: number;
      expected_answer_count?: number;
      actual_answer_count?: number;
      historical_results_excluded?: boolean;
      provider_ids?: number[];
      sample_runs_per_prompt?: number;
    };
    evidence_source_mix?: {
      api_sample_count?: number;
      browser_observation_count?: number;
      mock_sample_count?: number;
      citation_source_count?: number;
      verified_citation_source_count?: number;
      unverified_claimed_url_count?: number;
      live_search_answer_count?: number;
      web_search_claim_allowed?: boolean;
    };
    providers?: Array<{
      id?: number | null;
      name: string;
      provider_type?: string | null;
      answer_count: number;
    }>;
    competitors?: Array<{
      name: string;
      answer_mentions: number;
      mention_count: number;
      recommendation_count: number;
      avg_rank?: number | null;
    }>;
    recommendations?: string[];
    next_content_topics?: string[];
    metrics?: Record<string, number | null>;
    top_competitors?: Array<{ name: string; mentions: number }>;
    provider_breakdown?: Array<{
      provider_id?: number | null;
      provider_name: string;
      provider_type?: string | null;
      answer_count: number;
    }>;
    top_sources?: Array<{
      domain?: string | null;
      url?: string | null;
      mentions: number;
      is_owned: boolean;
      is_placed: boolean;
      ai_readiness_score: number;
    }>;
    source_gaps?: Array<{ domain?: string | null; url?: string | null; mentions: number; reason: string }>;
    question_gaps?: Array<{ target_question_id: number; question_text: string }>;
    keyword_gaps?: Array<{ keyword_id: number; keyword: string }>;
    coverage?: {
      target_question_count: number;
      covered_question_count: number;
      question_coverage_rate: number;
      keyword_count: number;
      covered_keyword_count: number;
      keyword_coverage_rate: number;
      keyword_prompt_variant_target?: number;
      keyword_full_prompt_coverage_count?: number;
      keyword_prompt_coverage_rate?: number;
      avg_prompt_variants_per_keyword?: number;
      provider_count: number;
      sample_size: number;
      coverage_status: string;
    };
    keyword_prompt_coverage?: {
      target_variant_count: number;
      keyword_count: number;
      full_coverage_count: number;
      partial_coverage_count: number;
      missing_count: number;
      avg_prompt_variants_per_keyword: number;
      coverage_rate: number;
      items: Array<{
        keyword_id: number;
        keyword: string;
        prompt_variant_count: number;
        target_variant_count: number;
        provider_count: number;
        result_count: number;
        coverage_status: string;
        sample_prompts: string[];
      }>;
    };
    evidence_quality?: {
      sample_size: number;
      api_sample_count?: number;
      real_api_sample_count?: number;
      mock_sample_count?: number;
      browser_observation_count?: number;
      screenshot_evidence_count?: number;
      real_provider_count?: number;
      real_sample_rate?: number;
      mock_sample_rate?: number;
      browser_observation_rate?: number;
      manual_correction_count?: number;
      manual_correction_rate?: number;
      provider_count: number;
      sample_confidence_score: number;
      risk_level: string;
      notes: string[];
    };
    brand_visibility_matrix?: {
      company_name?: string | null;
      leader_name?: string | null;
      company_position?: number | null;
      competitor_count?: number;
      objective_notes?: string[];
      summary?: Array<{
        name: string;
        brand_type: string;
        answer_mentions: number;
        mention_count: number;
        recommendation_count: number;
        avg_rank?: number | null;
        provider_count: number;
      }>;
      by_provider?: Array<{
        provider_id?: number | null;
        provider_name: string;
        provider_type?: string | null;
        answer_count: number;
        company_mentions: number;
        company_recommendations: number;
        company_mention_rate: number;
        company_recommendation_rate: number;
        company_avg_rank?: number | null;
        top_entities: Array<{
          name: string;
          brand_type: string;
          answer_mentions: number;
          mention_count: number;
          recommendation_count: number;
          avg_rank?: number | null;
        }>;
      }>;
      company?: {
        name: string;
        brand_type: string;
        answer_mentions: number;
        mention_count: number;
        recommendation_count: number;
        avg_rank?: number | null;
        provider_count: number;
      } | null;
      top_competitor?: {
        name: string;
        brand_type: string;
        answer_mentions: number;
        mention_count: number;
        recommendation_count: number;
        avg_rank?: number | null;
        provider_count: number;
      } | null;
    };
    delivery_readiness?: {
      status: string;
      score: number;
      blocker_count: number;
      summary: string;
      missing_actions: string[];
      checks: Array<{
        key: string;
        label: string;
        ok: boolean;
        current: number;
        required: number;
        weight: number;
        fix: string;
      }>;
    };
    report_template_snapshot?: {
      id?: number;
      template_key?: string;
      name?: string;
      version?: number;
      sections?: Array<Record<string, unknown>>;
      scoring?: {
        total_score?: number;
        dimensions?: Array<{ key?: string; name?: string; max_score?: number }>;
        levels?: Array<Record<string, unknown>>;
      };
      delivery_checks?: Array<Record<string, unknown>>;
    };
    template_score_alignment?: {
      template_dimension_count: number;
      actual_dimension_count: number;
      matched_dimension_count: number;
      unmatched_template_dimensions: Array<{ key?: string; name?: string; max_score?: number }>;
      actual_dimensions: Array<{ name: string; score: number; max_score: number }>;
    };
  };
  status: string;
  generated_at?: string | null;
};

export type MaturityReportDetail = MaturityReport & {
  score_items: Array<{
    id: number;
    dimension: string;
    score: number;
    max_score: number;
    explanation?: string | null;
  }>;
};

export type MaturityReportCompare = {
  project_id: number;
  base_report: MaturityReport;
  target_report: MaturityReport;
  total_score_delta: number;
  maturity_level_changed: boolean;
  metric_deltas: Record<string, { base: number; target: number; delta: number }>;
  dimension_deltas: Array<{
    dimension: string;
    base_score: number;
    target_score: number;
    delta: number;
    max_score: number;
  }>;
  summary: string;
  recommendations: string[];
};

export type ArticleDraft = {
  id: number;
  project_id: number;
  content_asset_id?: number | null;
  title: string;
  summary?: string | null;
  body_text: string;
  target_question_id?: number | null;
  target_keyword_ids?: number[];
  source_context?: Record<string, unknown>;
  status: string;
  draft_type: string;
  generated_by: string;
};

export type ArticleReview = {
  id: number;
  article_draft_id: number;
  total_score: number;
  grade: string;
  dimension_scores: Record<string, number>;
  issues_json: Array<Record<string, unknown>>;
  suggestions_json: Array<Record<string, unknown>>;
  risk_expressions: Array<Record<string, unknown>>;
  review_rule_snapshot?: {
    standard?: string;
    version?: number;
    total_max_score?: number;
    rules?: Array<{
      id?: number;
      rule_key?: string;
      name?: string;
      max_score?: number;
      weight?: number;
      version?: number;
      checks?: Record<string, unknown>;
    }>;
    report_alignment?: {
      name?: string;
      max_score?: number;
      score?: number;
      source_report_id?: number;
    };
  };
  review_type?: string;
  reviewer_id?: number | null;
  status: string;
};

export type ContentAsset = {
  id: number;
  company_id: number;
  project_id?: number | null;
  title: string;
  content_type: string;
  source_url?: string | null;
  body_text?: string | null;
  publish_channel?: string | null;
  status: string;
};

export type ContentAssetReview = {
  id: number;
  content_asset_id: number;
  total_score: number;
  grade: string;
  dimension_scores: Record<string, number>;
  issues_json: Array<Record<string, unknown>>;
  suggestions_json: Array<Record<string, unknown>>;
  risk_expressions: Array<Record<string, unknown>>;
  review_rule_snapshot?: ArticleReview["review_rule_snapshot"];
  review_type: string;
  status: string;
};

export type ReviewQueueItem = {
  id: number;
  project_id: number;
  project_name: string;
  type: "draft" | "asset";
  title: string;
  status: string;
  latest_score?: number | null;
  latest_grade?: string | null;
  latest_review_type?: string | null;
  latest_review_status?: string | null;
};

export type PlacementRecord = {
  id: number;
  project_id: number;
  content_asset_id?: number | null;
  article_draft_id?: number | null;
  channel: string;
  target_url?: string | null;
  planned_at?: string | null;
  published_at?: string | null;
  status: string;
  notes?: string | null;
  archive_note?: string | null;
  visibility: string;
  delivery_status: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type PlacementImpact = {
  placement: PlacementRecord;
  baseline_time: string;
  before: Record<string, number>;
  after: Record<string, number>;
  source_after_appearances: number;
  summary: string;
  recommendations: string[];
  review_report: {
    status: string;
    conclusion: string;
    baseline_time?: string | null;
    archive?: {
      version?: string | null;
      archive_note?: string | null;
      archived_at?: string | null;
      visibility?: string | null;
      delivery_status?: string | null;
    };
    metric_deltas: Record<string, number>;
    evidence: {
      before_sample_size?: number;
      after_sample_size?: number;
      review_crawl_task_id?: number | null;
      review_queue_job_id?: number | null;
      review_task_status?: string | null;
      review_alert_id?: number | null;
    };
    next_actions: string[];
  };
};

export type SourceInsight = {
  source_domain?: string | null;
  source_url?: string | null;
  source_type: string;
  appearances: number;
  is_owned: boolean;
  is_placed: boolean;
  has_content_asset: boolean;
  placement_count: number;
  published_placement_count: number;
  latest_placement_at?: string | null;
  placement_frequency_label: string;
  ai_readiness_status: string;
  crawlability_status: string;
  crawlable_score: number;
  ai_readiness_score: number;
};

export type SourceDetail = {
  insight: SourceInsight;
  evidence_results: Array<{
    crawl_result_id: number;
    prompt_text: string;
    answer_summary?: string | null;
    collected_at?: string | null;
  }>;
  matching_content_assets: Array<{
    id: number;
    title: string;
    content_type: string;
    source_url?: string | null;
    status: string;
  }>;
  matching_placements: Array<{
    id: number;
    channel: string;
    target_url?: string | null;
    status: string;
    published_at?: string | null;
  }>;
  recommendations: string[];
};

export type LLMProvider = {
  id: number;
  name: string;
  provider_type: string;
  api_base_url?: string | null;
  model_name: string;
  auth_config: Record<string, unknown>;
  cost_rule: Record<string, unknown>;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type LLMProviderDiagnostic = {
  provider_id: number;
  provider_type: string;
  ready: boolean;
  auth_ready: boolean;
  auth_source: string;
  base_url?: string | null;
  endpoint_path: string;
  supports_web_search: boolean;
  access_method: string;
  search_mode: string;
  search_access_status: string;
  setup_steps: string[];
  last_blocker?: string | null;
  missing: string[];
  warnings: string[];
  recommendations: string[];
};

export type LLMProviderReadiness = {
  provider_id: number;
  diagnostic: LLMProviderDiagnostic;
  latest_test?: LLMProviderTestResult | null;
  test_fresh: boolean;
  collection_ready: boolean;
  collection_blocker?: string | null;
};

export type LLMProviderOnboardingItem = {
  provider_type: string;
  platform_key?: string | null;
  label: string;
  default_base_url?: string | null;
  template_name: string;
  template_base_url?: string | null;
  template_model_name: string;
  model_examples: string[];
  auth_env?: string | null;
  access_method: string;
  search_mode: string;
  supports_web_search: boolean;
  collection_fit: string;
  setup_steps: string[];
  caveats: string[];
};

export type AuditLog = {
  id: number;
  actor_user_id?: number | null;
  actor_role?: string | null;
  action: string;
  resource_type: string;
  resource_id?: number | null;
  project_id?: number | null;
  company_id?: number | null;
  detail_json: Record<string, unknown>;
  created_at: string;
};

export type SystemAlert = {
  id: number;
  company_id?: number | null;
  project_id?: number | null;
  provider_id?: number | null;
  provider_test_run_id?: number | null;
  alert_type: string;
  severity: string;
  status: string;
  title: string;
  message: string;
  detail_json: Record<string, unknown>;
  created_at: string;
};

export type SystemAlertActionResult = {
  action_type: string;
  alert_id: number;
  status: string;
  message: string;
  resource_type?: string | null;
  resource_ids: number[];
  resource_url?: string | null;
  detail: Record<string, unknown>;
};

export type UsageSummary = {
  company_id?: number | null;
  project_id?: number | null;
  total_records: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_estimated_cost: number;
  currency: string;
  by_action: Array<{
    action: string;
    records: number;
    total_tokens: number;
    estimated_cost: number;
  }>;
  by_provider: Array<{
    provider_id?: number | null;
    provider_name: string;
    records: number;
    total_tokens: number;
    estimated_cost: number;
  }>;
};

export type UsageRecord = {
  id: number;
  provider_id?: number | null;
  company_id?: number | null;
  project_id?: number | null;
  task_id?: number | null;
  crawl_result_id?: number | null;
  provider_test_run_id?: number | null;
  action: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  currency: string;
  detail_json: Record<string, unknown>;
  created_at: string;
};

async function apiFetch<T>(path: string, init?: RequestInit & { token?: string }): Promise<T> {
  let token = init?.token;
  if (!token && typeof window === "undefined") {
    const { cookies } = await import("next/headers");
    const cookieStore = await cookies();
    token = cookieStore.get("geo_session")?.value;
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {})
    }
  });

  if (!res.ok) {
    if (res.status === 401 && typeof window === "undefined") {
      const { redirect } = await import("next/navigation");
      redirect("/login?expired=1");
    }
    let detail = "";
    try {
      const payload = await res.json();
      if (typeof payload?.detail === "string") {
        detail = payload.detail;
      } else if (payload?.detail) {
        detail = JSON.stringify(payload.detail);
      } else if (typeof payload?.message === "string") {
        detail = payload.message;
      }
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(`API request failed: ${res.status} ${res.statusText}${detail ? ` - ${detail}` : ""}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function getCompanies() {
  return apiFetch<Company[]>("/api/companies");
}

export async function loginUser(payload: { email: string; password: string }) {
  return apiFetch<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function logoutUser() {
  return apiFetch<void>("/api/auth/logout", { method: "POST" });
}

export async function registerUser(payload: { name: string; email: string; password: string; role?: string }) {
  return apiFetch<User>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getUsers() {
  return apiFetch<User[]>("/api/users");
}

export async function createUser(payload: {
  name: string;
  email: string;
  password: string;
  company_id?: number;
  phone?: string;
  role?: string;
  status?: string;
}) {
  return apiFetch<User>("/api/users", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateUser(
  userId: number,
  payload: Partial<Pick<User, "company_id" | "name" | "phone" | "role" | "status">> & { password?: string }
) {
  return apiFetch<User>(`/api/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function deactivateUser(userId: number) {
  return apiFetch<{ message: string }>(`/api/users/${userId}`, {
    method: "DELETE"
  });
}

export async function getMe(token: string) {
  return apiFetch<User>("/api/auth/me", { token });
}

export async function getProjects() {
  return apiFetch<Project[]>("/api/projects");
}

export async function getProject(id: string) {
  return apiFetch<Project>(`/api/projects/${id}`);
}

export async function getLatestProjectMvpStatus() {
  return apiFetch<ProjectMvpStatus>("/api/projects/mvp-status/latest");
}

export async function getProjectMvpStatus(projectId: string) {
  return apiFetch<ProjectMvpStatus>(`/api/projects/${projectId}/mvp-status`);
}

export async function getProjectOperationalReadiness(projectId: string) {
  return apiFetch<ProjectOperationalReadiness>(`/api/projects/${projectId}/operational-readiness`);
}

export async function getProjectOperatingTrends(projectId: string, days = 14) {
  return apiFetch<ProjectOperatingTrends>(`/api/projects/${projectId}/operating-trends?days=${days}`);
}

export async function getProjectStageGoals(projectId: string) {
  return apiFetch<ProjectStageGoal[]>(`/api/projects/${projectId}/stage-goals`);
}

export async function createProjectStageGoal(
  projectId: string,
  payload: {
    title: string;
    metric_key: string;
    target_value: number;
    baseline_value?: number;
    due_at?: string | null;
    owner?: string;
    status?: string;
    note?: string;
  }
) {
  return apiFetch<ProjectStageGoal>(`/api/projects/${projectId}/stage-goals`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createMaturityReportActionGoals(projectId: string, reportId: string) {
  return apiFetch<ProjectStageGoal[]>(`/api/projects/${projectId}/maturity-reports/${reportId}/action-goals`, {
    method: "POST"
  });
}

export async function createPlacementImpactActionGoals(projectId: string, placementId: string) {
  return apiFetch<ProjectStageGoal[]>(`/api/projects/${projectId}/placements/${placementId}/impact/action-goals`, {
    method: "POST"
  });
}

export async function updateProjectStageGoal(
  projectId: string,
  goalId: number,
  payload: Partial<{
    title: string;
    metric_key: string;
    target_value: number;
    baseline_value: number;
    due_at: string | null;
    owner: string | null;
    status: string;
    note: string | null;
  }>
) {
  return apiFetch<ProjectStageGoal>(`/api/projects/${projectId}/stage-goals/${goalId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function runProjectStageGoalReminders(projectId: string) {
  return apiFetch<SystemAlert[]>(`/api/projects/${projectId}/stage-goals/reminders/run`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function runProjectStageGoalAction(projectId: string, goalId: number, actionType: string) {
  return apiFetch<ProjectStageGoalActionResult>(`/api/projects/${projectId}/stage-goals/${goalId}/actions/${actionType}`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function getProjectStageGoalTimeline(projectId: string, goalId: number) {
  return apiFetch<ProjectStageGoalTimelineItem[]>(`/api/projects/${projectId}/stage-goals/${goalId}/timeline`);
}

export async function deleteProjectStageGoal(projectId: string, goalId: number) {
  return apiFetch<{ message: string }>(`/api/projects/${projectId}/stage-goals/${goalId}`, {
    method: "DELETE"
  });
}

export async function getTargetQuestions(projectId: string) {
  return apiFetch<TargetQuestion[]>(`/api/projects/${projectId}/target-questions`);
}

export async function getGeoV1DecisionMap(projectId: string) {
  return apiFetch<GeoV1DecisionMap>(`/api/projects/${projectId}/geo-v1/decision-map`);
}

export async function getGeoV1Observations(projectId: string) {
  return apiFetch<GeoV1Observation[]>(`/api/projects/${projectId}/geo-v1/observations`);
}

export async function getGeoV1Actions(projectId: string) {
  return apiFetch<GeoV1Action[]>(`/api/projects/${projectId}/geo-v1/actions`);
}

export async function getGeoV1BrandClaims(projectId: string) {
  return apiFetch<GeoV1BrandClaim[]>(`/api/projects/${projectId}/geo-v1/brand-claims`);
}

export async function createGeoV1Action(
  projectId: string,
  payload: Pick<GeoV1Action, "title" | "rationale"> & Partial<Omit<GeoV1Action, "id" | "project_id" | "title" | "rationale" | "question_text">>
) {
  return apiFetch<GeoV1Action>(`/api/projects/${projectId}/geo-v1/actions`, { method: "POST", body: JSON.stringify(payload) });
}

export async function createGeoV1BrandClaim(
  projectId: string,
  payload: Pick<GeoV1BrandClaim, "title" | "claim_text"> & Partial<Omit<GeoV1BrandClaim, "id" | "project_id" | "title" | "claim_text">>
) {
  return apiFetch<GeoV1BrandClaim>(`/api/projects/${projectId}/geo-v1/brand-claims`, { method: "POST", body: JSON.stringify(payload) });
}

export async function getKeywords(projectId: string) {
  return apiFetch<Keyword[]>(`/api/projects/${projectId}/keywords`);
}

export async function getCompetitors(projectId: string) {
  return apiFetch<Competitor[]>(`/api/projects/${projectId}/competitors`);
}

export async function getCrawlResults(projectId: string, options: { taskId?: string | number } = {}) {
  const query = options.taskId ? `?task_id=${encodeURIComponent(String(options.taskId))}` : "";
  return apiFetch<CrawlResult[]>(`/api/projects/${projectId}/crawl-results${query}`);
}

export async function getCrawlTasks(projectId: string) {
  return apiFetch<CrawlTask[]>(`/api/projects/${projectId}/crawl-tasks`);
}

export async function getCrawlSchedules(projectId: string) {
  return apiFetch<CrawlSchedule[]>(`/api/projects/${projectId}/crawl-schedules`);
}

export async function getCrawlTask(projectId: string, taskId: string) {
  return apiFetch<CrawlTask>(`/api/projects/${projectId}/crawl-tasks/${taskId}`);
}

export async function getCrawlTaskLogs(projectId: string, taskId: string) {
  return apiFetch<CrawlTaskLog[]>(`/api/projects/${projectId}/crawl-tasks/${taskId}/logs`);
}

export async function getCrawlResult(projectId: string, resultId: string) {
  return apiFetch<CrawlResultDetail>(`/api/projects/${projectId}/crawl-results/${resultId}`);
}

export async function updateCrawlResultAnalysis(
  projectId: string,
  resultId: string,
  payload: {
    company_mentioned?: boolean;
    company_recommended?: boolean;
    company_rank?: number | null;
    sentiment?: string;
    confidence?: number;
    correction_note?: string | null;
  }
) {
  return apiFetch<CrawlResultDetail>(`/api/projects/${projectId}/crawl-results/${resultId}/analysis`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function getBrowserObservations(projectId: string, limit = 10) {
  return apiFetch<BrowserObservation[]>(`/api/projects/${projectId}/browser-observations?limit=${limit}`);
}

export async function createBrowserObservation(
  projectId: string,
  payload: BrowserObservationCreatePayload
) {
  return apiFetch<CrawlResultDetail>(`/api/projects/${projectId}/browser-observations`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function bulkCreateBrowserObservations(
  projectId: string,
  observations: BrowserObservationCreatePayload[]
) {
  return apiFetch<BrowserObservationBulkCreateResult>(`/api/projects/${projectId}/browser-observations/bulk`, {
    method: "POST",
    body: JSON.stringify({ observations })
  });
}

export async function getSearchMetrics(projectId: string) {
  return apiFetch<SearchMetrics>(`/api/projects/${projectId}/search-metrics`);
}

export async function createCompany(payload: Partial<Company> & { name: string }) {
  return apiFetch<Company>("/api/companies", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createProject(payload: Partial<Project> & { company_id: number; name: string }) {
  return apiFetch<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function bulkCreateTargetQuestions(
  projectId: number,
  questions: Array<{ question_text: string; question_type?: string; priority?: number }>
) {
  return apiFetch<TargetQuestion[]>(`/api/projects/${projectId}/target-questions/bulk`, {
    method: "POST",
    body: JSON.stringify(questions)
  });
}

export async function bulkCreateKeywords(
  projectId: number,
  keywords: Array<{ keyword: string; keyword_type?: string; priority?: number }>
) {
  return apiFetch<Keyword[]>(`/api/projects/${projectId}/keywords/bulk`, {
    method: "POST",
    body: JSON.stringify(keywords)
  });
}

export async function createCompetitor(projectId: number, payload: { name: string }) {
  return apiFetch<Competitor>(`/api/projects/${projectId}/competitors`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function runCrawlTask(
  projectId: string,
  payload: {
    task_type?: string;
    schedule_type?: string;
    provider_ids?: number[];
    target_question_ids?: number[];
    keyword_ids?: number[];
    sample_runs_per_prompt?: number;
    execute_now?: boolean;
    max_estimated_cost?: number;
    allow_over_budget?: boolean;
  } = {}
) {
  return apiFetch<CrawlTask>(`/api/projects/${projectId}/crawl-tasks`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function estimateCrawlTask(
  projectId: string,
  payload: {
    task_type?: string;
    schedule_type?: string;
    provider_ids?: number[];
    target_question_ids?: number[];
    keyword_ids?: number[];
    execute_now?: boolean;
    max_estimated_cost?: number;
    allow_over_budget?: boolean;
  } = {}
) {
  return apiFetch<CrawlTaskEstimate>(`/api/projects/${projectId}/crawl-tasks/estimate`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function retryCrawlTask(projectId: string, taskId: number) {
  return apiFetch<CrawlTask>(`/api/projects/${projectId}/crawl-tasks/${taskId}/retry`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function createCrawlSchedule(
  projectId: string,
  payload: {
    name: string;
    schedule_type?: string;
    interval_hours?: number;
    provider_ids?: number[];
    target_question_ids?: number[];
    keyword_ids?: number[];
    sample_runs_per_prompt?: number;
    status?: string;
    execute_now?: boolean;
  }
) {
  return apiFetch<CrawlSchedule>(`/api/projects/${projectId}/crawl-schedules`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function runCrawlSchedule(projectId: string, scheduleId: number) {
  return apiFetch<CrawlTask>(`/api/projects/${projectId}/crawl-schedules/${scheduleId}/run`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function runDueCrawlSchedules(projectId: string) {
  return apiFetch<CrawlScheduleRunResult>(`/api/projects/${projectId}/crawl-schedules/run-due`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function getMaturityReports(projectId: string) {
  return apiFetch<MaturityReport[]>(`/api/projects/${projectId}/maturity-reports`);
}

export async function getMaturityReport(projectId: string, reportId: string) {
  return apiFetch<MaturityReportDetail>(`/api/projects/${projectId}/maturity-reports/${reportId}`);
}

export async function getMaturityReportCompare(projectId: string) {
  return apiFetch<MaturityReportCompare>(`/api/projects/${projectId}/maturity-reports/compare`);
}

export function getMaturityReportMarkdownUrl(projectId: string, reportId: string) {
  return `${API_BASE_URL}/api/projects/${projectId}/maturity-reports/${reportId}/export/markdown`;
}

export function getMaturityReportPdfUrl(projectId: string, reportId: string) {
  return `${API_BASE_URL}/api/projects/${projectId}/maturity-reports/${reportId}/export/pdf`;
}

export async function generateMaturityReport(
  projectId: string,
  payload: { title?: string; report_period?: string } = {}
) {
  return apiFetch<MaturityReport>(`/api/projects/${projectId}/maturity-reports/generate`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function runDiagnostic(projectId: string, payload: {
  provider_ids?: number[];
  target_question_ids?: number[];
  keyword_ids?: number[];
  execute_now?: boolean;
  generate_report?: boolean;
  create_action_goals?: boolean;
  max_estimated_cost?: number;
  allow_over_budget?: boolean;
  title?: string;
  report_period?: string;
} = {}) {
  return apiFetch<DiagnosticRunResult>(`/api/projects/${projectId}/diagnostic-runs`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getArticleDrafts(projectId: string) {
  return apiFetch<ArticleDraft[]>(`/api/projects/${projectId}/article-drafts`);
}

export async function getArticleDraft(projectId: string, draftId: string) {
  return apiFetch<ArticleDraft>(`/api/projects/${projectId}/article-drafts/${draftId}`);
}

export async function generateArticleDraft(
  projectId: string,
  topic?: string,
  payload: { title?: string; draft_type?: string; source_context?: Record<string, unknown> } = {}
) {
  return apiFetch<ArticleDraft>(`/api/projects/${projectId}/article-drafts/generate`, {
    method: "POST",
    body: JSON.stringify({ ...payload, topic })
  });
}

export async function getArticleReviews(projectId: string, draftId: number) {
  return apiFetch<ArticleReview[]>(`/api/projects/${projectId}/article-drafts/${draftId}/reviews`);
}

export async function createArticleReview(projectId: string, draftId: number) {
  return apiFetch<ArticleReview>(`/api/projects/${projectId}/article-drafts/${draftId}/reviews`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function reviseArticleDraft(projectId: string, draftId: number) {
  return apiFetch<ArticleDraft>(`/api/projects/${projectId}/article-drafts/${draftId}/revise`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function decideArticleDraftReview(
  projectId: string,
  draftId: number,
  payload: { decision: "approved" | "rejected"; comment?: string }
) {
  return apiFetch<ArticleReview>(`/api/projects/${projectId}/article-drafts/${draftId}/human-review`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getLLMProviders() {
  return apiFetch<LLMProvider[]>("/api/llm-providers");
}

export async function getLLMProviderOnboarding() {
  return apiFetch<LLMProviderOnboardingItem[]>("/api/llm-providers/onboarding");
}

export async function getAuditLogs() {
  return apiFetch<AuditLog[]>("/api/audit-logs");
}

export async function getAlerts(status = "open", params?: { projectId?: string | number; limit?: number }) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (params?.projectId) query.set("project_id", String(params.projectId));
  if (params?.limit) query.set("limit", String(params.limit));
  const suffix = query.toString();
  return apiFetch<SystemAlert[]>(`/api/alerts${suffix ? `?${suffix}` : ""}`);
}

export async function updateAlert(alertId: number, status: "open" | "acknowledged" | "resolved") {
  return apiFetch<SystemAlert>(`/api/alerts/${alertId}`, {
    method: "PATCH",
    body: JSON.stringify({ status })
  });
}

export async function createAlertReportActionGoals(alertId: number) {
  return apiFetch<SystemAlertActionResult>(`/api/alerts/${alertId}/actions/create-report-action-goals`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function runPlacementReminders(projectId?: number) {
  const query = projectId ? `?project_id=${projectId}` : "";
  return apiFetch<SystemAlert[]>(`/api/alerts/placement-reminders/run${query}`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function runMonitoringAlerts(projectId?: number) {
  const query = projectId ? `?project_id=${projectId}` : "";
  return apiFetch<SystemAlert[]>(`/api/alerts/monitoring/run${query}`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function getQueueJobs(status?: string, limit = 100) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  query.set("limit", String(limit));
  return apiFetch<QueueJobListResponse>(`/api/queue/jobs?${query.toString()}`);
}

export async function runNextQueueJob() {
  return apiFetch<QueueJobRunResult>("/api/queue/jobs/run-next", {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function runReadyQueueJobs(maxJobs = 25, projectId?: string) {
  const query = new URLSearchParams({ max_jobs: String(maxJobs) });
  if (projectId) query.set("project_id", projectId);
  return apiFetch<QueueReadyRunResult>(`/api/queue/jobs/run-ready?${query.toString()}`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function getReviewRules(status?: string) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<ReviewRule[]>(`/api/review-rules${suffix}`);
}

export async function createReviewRule(payload: {
  rule_key: string;
  name: string;
  description?: string | null;
  applies_to?: string;
  max_score?: number;
  weight?: number;
  checks_json?: Record<string, unknown>;
  status?: string;
  version?: number;
}) {
  return apiFetch<ReviewRule>("/api/review-rules", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getReportTemplates(status?: string) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<ReportTemplate[]>(`/api/report-templates${suffix}`);
}

export async function createReportTemplate(payload: {
  template_key: string;
  name: string;
  description?: string | null;
  applies_to?: string;
  sections_json?: Array<Record<string, unknown>>;
  scoring_json?: Record<string, unknown>;
  delivery_checks_json?: Array<Record<string, unknown>>;
  status?: string;
  version?: number;
}) {
  return apiFetch<ReportTemplate>("/api/report-templates", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getUsageSummary() {
  return apiFetch<UsageSummary>("/api/usage/summary");
}

export async function getUsageRecords(limit = 30) {
  return apiFetch<UsageRecord[]>(`/api/usage/records?limit=${limit}`);
}

export async function getLLMProvider(providerId: string) {
  return apiFetch<LLMProvider>(`/api/llm-providers/${providerId}`);
}

export async function getLLMProviderDiagnostic(providerId: string) {
  return apiFetch<LLMProviderDiagnostic>(`/api/llm-providers/${providerId}/diagnostic`);
}

export async function getLLMProviderReadiness() {
  return apiFetch<LLMProviderReadiness[]>("/api/llm-providers/readiness");
}

export async function getLLMProviderCollectionSummary(providerId: string) {
  return apiFetch<LLMProviderCollectionSummary>(`/api/llm-providers/${providerId}/collection-summary`);
}

export async function getLatestProviderNetworkCheck() {
  return apiFetch<ProviderNetworkCheck>("/api/llm-providers/network-check/latest");
}

export async function createLLMProvider(payload: {
  name: string;
  provider_type: string;
  api_base_url?: string;
  model_name: string;
  auth_config?: Record<string, unknown>;
  cost_rule?: Record<string, unknown>;
  status?: string;
}) {
  return apiFetch<LLMProvider>("/api/llm-providers", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateLLMProvider(
  providerId: string,
  payload: {
    name?: string;
    provider_type?: string;
    api_base_url?: string | null;
    model_name?: string;
    auth_config?: Record<string, unknown>;
    cost_rule?: Record<string, unknown>;
    status?: string;
  }
) {
  return apiFetch<LLMProvider>(`/api/llm-providers/${providerId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function testLLMProvider(
  providerId: string,
  payload: { prompt_text: string; company_name?: string; industry?: string }
) {
  return apiFetch<LLMProviderTestResult>(`/api/llm-providers/${providerId}/test`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function queueLLMProviderTest(
  providerId: string,
  payload: { prompt_text: string; company_name?: string; industry?: string }
) {
  return apiFetch<QueueJob>(`/api/llm-providers/${providerId}/test-jobs`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getLLMProviderTestJob(providerId: string, jobId: number) {
  return apiFetch<QueueJob>(`/api/llm-providers/${providerId}/test-jobs/${jobId}`);
}

export async function getLLMProviderTestRuns(providerId: string) {
  return apiFetch<LLMProviderTestResult[]>(`/api/llm-providers/${providerId}/test-runs`);
}

export async function getContentAssets(projectId: string) {
  return apiFetch<ContentAsset[]>(`/api/projects/${projectId}/content-assets`);
}

const REVIEW_QUEUE_STATUSES = new Set(["draft", "pending_review", "needs_revision", "rejected"]);

export async function getReviewQueue() {
  const projects = await getProjects();
  const queueGroups = await Promise.all(
    projects.map(async (project) => {
      const projectId = String(project.id);
      const [drafts, assets] = await Promise.all([
        getArticleDrafts(projectId).catch(() => []),
        getContentAssets(projectId).catch(() => [])
      ]);
      const draftItems = await Promise.all(
        drafts
          .filter((draft) => REVIEW_QUEUE_STATUSES.has(draft.status))
          .map(async (draft) => {
            const latestReview = (await getArticleReviews(projectId, draft.id).catch(() => []))[0];
            return {
              id: draft.id,
              project_id: project.id,
              project_name: project.name,
              type: "draft" as const,
              title: draft.title,
              status: draft.status,
              latest_score: latestReview?.total_score ?? null,
              latest_grade: latestReview?.grade ?? null,
              latest_review_type: latestReview?.review_type ?? null,
              latest_review_status: latestReview?.status ?? null
            };
          })
      );
      const assetItems = await Promise.all(
        assets
          .filter((asset) => REVIEW_QUEUE_STATUSES.has(asset.status))
          .map(async (asset) => {
            const latestReview = (await getContentAssetReviews(projectId, asset.id).catch(() => []))[0];
            return {
              id: asset.id,
              project_id: project.id,
              project_name: project.name,
              type: "asset" as const,
              title: asset.title,
              status: asset.status,
              latest_score: latestReview?.total_score ?? null,
              latest_grade: latestReview?.grade ?? null,
              latest_review_type: latestReview?.review_type ?? null,
              latest_review_status: latestReview?.status ?? null
            };
          })
      );
      return [...draftItems, ...assetItems];
    })
  );
  return queueGroups.flat().sort((a, b) => b.project_id - a.project_id || b.id - a.id);
}

export async function createContentAsset(
  projectId: string,
  payload: {
    company_id: number;
    title: string;
    content_type?: string;
    source_url?: string;
    body_text?: string;
    publish_channel?: string;
    status?: string;
  }
) {
  return apiFetch<ContentAsset>(`/api/projects/${projectId}/content-assets`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function bulkCreateContentAssets(
  projectId: string,
  payload: Array<{
    company_id: number;
    title: string;
    content_type?: string;
    source_url?: string;
    body_text?: string;
    publish_channel?: string;
    status?: string;
  }>
) {
  return apiFetch<ContentAsset[]>(`/api/projects/${projectId}/content-assets/bulk`, {
    method: "POST",
    body: JSON.stringify({ items: payload })
  });
}

export async function getContentAssetReviews(projectId: string, assetId: number) {
  return apiFetch<ContentAssetReview[]>(`/api/projects/${projectId}/content-assets/${assetId}/reviews`);
}

export async function createContentAssetReview(projectId: string, assetId: number) {
  return apiFetch<ContentAssetReview>(`/api/projects/${projectId}/content-assets/${assetId}/reviews`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function createContentAssetRemediationGoals(projectId: string) {
  return apiFetch<ProjectStageGoal[]>(`/api/projects/${projectId}/content-assets/remediation-goals`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function decideContentAssetReview(
  projectId: string,
  assetId: number,
  payload: { decision: "approved" | "rejected"; comment?: string }
) {
  return apiFetch<ContentAssetReview>(`/api/projects/${projectId}/content-assets/${assetId}/human-review`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getPlacements(projectId: string) {
  return apiFetch<PlacementRecord[]>(`/api/projects/${projectId}/placements`);
}

export async function createPlacement(
  projectId: string,
  payload: {
    content_asset_id?: number;
    article_draft_id?: number;
    channel: string;
    target_url?: string;
    status?: string;
    notes?: string;
    archive_note?: string;
    visibility?: string;
    delivery_status?: string;
  }
) {
  return apiFetch<PlacementRecord>(`/api/projects/${projectId}/placements`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updatePlacement(
  projectId: string,
  placementId: number,
  payload: Partial<{
    content_asset_id: number;
    article_draft_id: number;
    channel: string;
    target_url: string;
    planned_at: string;
    published_at: string;
    status: string;
    notes: string;
    archive_note: string;
    visibility: string;
    delivery_status: string;
  }>
) {
  return apiFetch<PlacementRecord>(`/api/projects/${projectId}/placements/${placementId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function getSourceInsights(projectId: string) {
  return apiFetch<SourceInsight[]>(`/api/projects/${projectId}/source-insights`);
}

export async function getSourceDetail(projectId: string, params: { source_url?: string; source_domain?: string }) {
  const query = new URLSearchParams();
  if (params.source_url) query.set("source_url", params.source_url);
  if (params.source_domain) query.set("source_domain", params.source_domain);
  return apiFetch<SourceDetail>(`/api/projects/${projectId}/source-insights/detail?${query.toString()}`);
}

export async function getPlacementImpact(projectId: string, placementId: string) {
  return apiFetch<PlacementImpact>(`/api/projects/${projectId}/placements/${placementId}/impact`);
}

export function getPlacementImpactMarkdownUrl(projectId: string, placementId: string) {
  return `${API_BASE_URL}/api/projects/${projectId}/placements/${placementId}/impact/export/markdown`;
}

export function getPlacementImpactPdfUrl(projectId: string, placementId: string) {
  return `${API_BASE_URL}/api/projects/${projectId}/placements/${placementId}/impact/export/pdf`;
}

export function getDeliveryPackageMarkdownUrl(projectId: string) {
  return `${API_BASE_URL}/api/projects/${projectId}/delivery-package/export/markdown`;
}

export function getDeliveryPackagePdfUrl(projectId: string) {
  return `${API_BASE_URL}/api/projects/${projectId}/delivery-package/export/pdf`;
}

export type PlacementReviewArchiveItem = {
  placement: PlacementRecord;
  impact?: PlacementImpact | null;
};

export type DeliveryPackageShare = {
  id: number;
  project_id: number;
  token: string;
  name: string;
  status: string;
  expires_at?: string | null;
  created_by_user_id?: number | null;
  last_accessed_at?: string | null;
  confirmation_token?: string | null;
  created_at: string;
  updated_at: string;
};

export type DeliveryPackageAccessLog = {
  id: number;
  share_id: number;
  project_id: number;
  placement_id?: number | null;
  event_type: string;
  actor_name?: string | null;
  comment?: string | null;
  detail_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type PublicDeliveryPackage = {
  project: {
    id: number;
    name: string;
    description?: string | null;
  };
  share: {
    name: string;
    status: string;
    expires_at?: string | null;
    last_accessed_at?: string | null;
  };
  deliverables: Array<{
    placement: PlacementRecord;
    summary: string;
    recommendations: string[];
    review_report: PlacementImpact["review_report"];
    exports: {
      markdown: string;
      pdf: string;
    };
  }>;
};

export async function getPlacementReviewArchive(projectId: string) {
  const placements = await getPlacements(projectId);
  const publishedPlacements = placements.filter((placement) => placement.status === "published");
  const items = await Promise.all(
    publishedPlacements.map(async (placement) => ({
      placement,
      impact: await getPlacementImpact(projectId, String(placement.id)).catch(() => null)
    }))
  );
  return items satisfies PlacementReviewArchiveItem[];
}

export async function getDeliveryShares(projectId: string) {
  return apiFetch<DeliveryPackageShare[]>(`/api/projects/${projectId}/delivery-shares`);
}

export async function createDeliveryShare(
  projectId: string,
  payload: { name: string; expires_at?: string | null }
) {
  return apiFetch<DeliveryPackageShare>(`/api/projects/${projectId}/delivery-shares`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function revokeDeliveryShare(projectId: string, shareId: number) {
  return apiFetch<DeliveryPackageShare>(`/api/projects/${projectId}/delivery-shares/${shareId}/revoke`, {
    method: "PATCH"
  });
}

export async function rotateDeliveryConfirmationToken(projectId: string, shareId: number) {
  return apiFetch<DeliveryPackageShare>(
    `/api/projects/${projectId}/delivery-shares/${shareId}/confirmation-token`,
    { method: "POST" }
  );
}

export async function getDeliveryAccessLogs(projectId: string) {
  return apiFetch<DeliveryPackageAccessLog[]>(`/api/projects/${projectId}/delivery-shares/access-logs`);
}

export async function getPublicDeliveryPackage(token: string) {
  return apiFetch<PublicDeliveryPackage>(`/api/public/delivery-packages/${token}`);
}

export async function confirmPublicDeliveryReport(
  token: string,
  placementId: number,
  payload: { confirmation_token: string; actor_name: string; comment?: string }
) {
  return apiFetch<DeliveryPackageAccessLog>(
    `/api/public/delivery-packages/${token}/placements/${placementId}/confirm`,
    {
      method: "POST",
      body: JSON.stringify(payload)
    }
  );
}

export function getPublicDeliveryExportUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}
