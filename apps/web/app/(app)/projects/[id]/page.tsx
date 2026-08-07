import fs from "node:fs/promises";
import path from "node:path";

import {
  appendProjectConfigAction,
  bulkCreateBrowserObservationsAction,
  createCrawlScheduleAction,
  createBrowserObservationAction,
  createProjectStageGoalAction,
  generateDraftAndReviewAction,
  generateReportAction,
  importBrowserObservationPackAction,
  prepareBrowserObservationPackAction,
  validateBrowserObservationPackAction,
  reviewDraftAction,
  runDiagnosticAction,
  runProjectStageGoalRemindersAction,
  runProjectStageGoalActionAction,
  runCrawlAction,
  runCrawlScheduleAction,
  runDueCrawlSchedulesAction,
  retryCrawlTaskAction,
  seedMaturityConfigAction,
  updateProjectStageGoalStatusAction
} from "@/app/actions";
import {
  getArticleDrafts,
  getArticleReviews,
  getBrowserObservations,
  getCompetitors,
  getContentAssets,
  getCrawlResults,
  getCrawlSchedules,
  getCrawlTasks,
  getLatestProviderNetworkCheck,
  getLLMProviders,
  getAlerts,
  getKeywords,
  getMaturityReports,
  getPlacementReviewArchive,
  getPlacements,
  getProject,
  getProjectMvpStatus,
  getProjectOperatingTrends,
  getProjectOperationalReadiness,
  getProjectStageGoals,
  getProjectStageGoalTimeline,
  getSearchMetrics,
  getTargetQuestions
} from "@/lib/api";
import { CrawlLaunchForm } from "./crawl-launch-form";
import { SubmitButton } from "@/app/(app)/submit-button";
import Link from "next/link";
import type { Route } from "next";

type BrowserObservationPackStatus = {
  ready: boolean;
  input: string;
  evidence_dir: string;
  observation_count: number;
  covered_platforms: string[];
  ready_platforms: string[];
  missing_platforms: string[];
  blocking_issue_count: number;
  warning_count: number;
  next_action: string;
  items: Array<{
    platform_name: string;
    provider_id?: number | null;
    target_question_id?: number | null;
    keyword_id?: number | null;
    prompt_text: string;
    observation_url?: string | null;
    raw_answer_length: number;
    answer_ready: boolean;
    source_count: number;
    issues: string[];
    warnings: string[];
    ready: boolean;
    evidence: {
      evidence_filename?: string | null;
      evidence_path?: string | null;
      file_exists: boolean;
      ready: boolean;
    };
  }>;
};

type BrowserObservationTemplatePayload = {
  observations?: Array<Record<string, unknown>>;
};

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    config_added?: string;
    ready_created?: string;
    ready_ran?: string;
    ready_success?: string;
    ready_failed?: string;
    ready_pending?: string;
    observe_report_id?: string;
    observe_question_id?: string;
    observe_keyword_id?: string;
    observe_platform?: string;
    observe_prompt?: string;
    observation_created?: string;
    observation_bulk_created?: string;
    observation_bulk_sources?: string;
    observation_bulk_screenshots?: string;
    observation_validated?: string;
    observation_validated_platforms?: string;
    observation_result?: string;
    observation_sources?: string;
    observation_screenshots?: string;
    pack_prepared?: string;
    next_pack_prepared?: string;
    pack_dir?: string;
    diagnostic_task?: string;
    diagnostic_status?: string;
    diagnostic_report?: string;
    diagnostic_goals?: string;
    diagnostic_expected?: string;
    diagnostic_results?: string;
    diagnostic_estimated_cost?: string;
    diagnostic_estimated_tokens?: string;
    diagnostic_blockers?: string;
    action_error?: string;
  }>;
};

const REQUIRED_BROWSER_OBSERVATION_PACK_PLATFORMS = ["豆包", "DeepSeek", "Kimi", "千问"];
const BROWSER_OBSERVATION_PACK_PLACEHOLDERS = [
  "粘贴该平台网页端返回的完整答案",
  "粘贴网页端大模型返回的完整答案",
  "待填",
  "TODO",
  "如不使用 --evidence-dir",
  "/path/to/screenshot"
];

function outputPathCandidates(...segments: string[]) {
  return [
    path.resolve(process.cwd(), "outputs", ...segments),
    path.resolve(process.cwd(), "..", "..", "outputs", ...segments),
    path.resolve(process.cwd(), "..", "..", "..", "outputs", ...segments)
  ];
}

async function firstExistingPath(paths: string[]) {
  for (const item of paths) {
    try {
      await fs.access(item);
      return item;
    } catch {
      continue;
    }
  }
  return paths[0];
}

function packString(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === "string" ? value.trim() : "";
}

function packStringList(record: Record<string, unknown>, key: string) {
  const value = record[key];
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function hasPackPlaceholder(value: unknown) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
  return BROWSER_OBSERVATION_PACK_PLACEHOLDERS.some((pattern) => text.includes(pattern));
}

async function packFileExists(filePath: string) {
  try {
    const stat = await fs.stat(filePath);
    return stat.isFile();
  } catch {
    return false;
  }
}

async function readBrowserObservationPackStatus(): Promise<BrowserObservationPackStatus | null> {
  const packDir = await firstExistingPath(outputPathCandidates("yuanquan_browser_observation_pack_q1"));
  const inputPath = path.join(packDir, "observations.json");
  const evidenceDir = path.join(packDir, "raw-evidence");
  try {
    const raw = await fs.readFile(inputPath, "utf-8");
    const payload = JSON.parse(raw) as BrowserObservationTemplatePayload | Array<Record<string, unknown>>;
    const observations = Array.isArray(payload) ? payload : Array.isArray(payload.observations) ? payload.observations : [];
    const items = await Promise.all(
      observations.filter(Boolean).map(async (record) => {
        const platformName = packString(record, "platform_name");
        const providerId = Number(record.provider_id);
        const targetQuestionId = Number(record.target_question_id);
        const keywordId = Number(record.keyword_id);
        const promptText = packString(record, "prompt_text");
        const observationUrl = packString(record, "observation_url");
        const rawAnswer = packString(record, "raw_answer");
        const answerSummary = packString(record, "answer_summary");
        const sourceUrls = packStringList(record, "source_urls");
        const evidenceFilename = packString(record, "evidence_filename");
        const evidencePath = evidenceFilename ? path.join(evidenceDir, evidenceFilename) : "";
        const evidenceFileExists = evidencePath ? await packFileExists(evidencePath) : false;
        const screenshotUrl = packString(record, "screenshot_url");
        const externalUrlReady = Boolean(screenshotUrl && !hasPackPlaceholder(screenshotUrl));
        const evidenceReady = evidenceFileExists || externalUrlReady;
        const issues: string[] = [];
        const warnings: string[] = [];
        if (!REQUIRED_BROWSER_OBSERVATION_PACK_PLATFORMS.includes(platformName)) {
          issues.push("平台不在首批四平台范围内");
        }
        if (!promptText) issues.push("缺少 prompt_text");
        if (!rawAnswer || hasPackPlaceholder(rawAnswer)) {
          issues.push("raw_answer 仍是空值或占位文本");
        } else if (rawAnswer.length < 80) {
          issues.push("raw_answer 少于 80 个字符");
        }
        if (answerSummary && hasPackPlaceholder(answerSummary)) {
          warnings.push("answer_summary 仍是占位文本");
        }
        if (!evidenceReady) {
          issues.push("缺少截图/录屏证据文件或可用 screenshot_url");
        }
        if (sourceUrls.length === 0) {
          warnings.push("未填写页面可见信源 URL；如果网页端没有展示信源可以保留为空");
        }
        return {
          platform_name: platformName,
          provider_id: Number.isFinite(providerId) && providerId > 0 ? providerId : null,
          target_question_id: Number.isFinite(targetQuestionId) && targetQuestionId > 0 ? targetQuestionId : null,
          keyword_id: Number.isFinite(keywordId) && keywordId > 0 ? keywordId : null,
          prompt_text: promptText,
          observation_url: observationUrl || null,
          raw_answer_length: rawAnswer.length,
          answer_ready: Boolean(rawAnswer && !hasPackPlaceholder(rawAnswer) && rawAnswer.length >= 80),
          source_count: sourceUrls.length,
          issues,
          warnings,
          ready: issues.length === 0,
          evidence: {
            evidence_filename: evidenceFilename || null,
            evidence_path: evidencePath || null,
            file_exists: evidenceFileExists,
            ready: evidenceReady
          }
        };
      })
    );
    const coveredPlatforms = [...new Set(items.map((item) => item.platform_name).filter(Boolean))].sort();
    const readyPlatforms = [...new Set(items.filter((item) => item.ready).map((item) => item.platform_name).filter(Boolean))].sort();
    const missingPlatforms = REQUIRED_BROWSER_OBSERVATION_PACK_PLATFORMS.filter((platform) => !coveredPlatforms.includes(platform));
    const issueCount = items.reduce((sum, item) => sum + item.issues.length, 0) + missingPlatforms.length;
    const warningCount = items.reduce((sum, item) => sum + item.warnings.length, 0);
    const ready =
      issueCount === 0 &&
      missingPlatforms.length === 0 &&
      observations.length >= REQUIRED_BROWSER_OBSERVATION_PACK_PLATFORMS.length;
    return {
      ready,
      input: inputPath,
      evidence_dir: evidenceDir,
      observation_count: observations.length,
      covered_platforms: coveredPlatforms,
      ready_platforms: readyPlatforms,
      missing_platforms: missingPlatforms,
      blocking_issue_count: issueCount,
      warning_count: warningCount,
      next_action: ready
        ? "可运行 dry-run，随后正式导入并生成报告/稿件。"
        : "继续补齐 raw_answer 和 raw-evidence 里的截图/录屏文件。",
      items
    };
  } catch {
    return null;
  }
}

function pct(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${Math.round(value * 100)}%`;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    accepted: "已确认",
    active: "进行中",
    completed: "已完成",
    created: "已创建",
    empty: "无样本",
    failed: "失败",
    missing: "待补齐",
    pending: "排队中",
    positive: "正向效果",
    ready: "待交付",
    running: "执行中",
    success: "成功",
    unavailable: "待复盘",
    unknown: "待确认"
  };
  return labels[value] ?? value;
}

function checkLabel(value: string) {
  const labels: Record<string, string> = {
    "project.detail": "项目配置",
    "crawl.health": "搜索采集",
    "crawl.schedule_ready": "每小时监测",
    "provider.real_collection_ready": "真实渠道",
    maturity_report: "成熟度报告",
    "stage_goal.completed": "阶段目标",
    "stage_goal.timeline": "闭环时间线",
    "placement.impact.positive": "投放复盘",
    public_delivery_package: "客户交付"
  };
  return labels[value] ?? value;
}

function actionLabel(value: string) {
  const labels: Record<string, string> = {
    run_crawl: "搜索采集",
    generate_draft: "撰稿评分",
    create_placement: "创建投放",
    approve_and_create_placement: "人工审核投放",
    publish_prepare_delivery: "发布交付",
    create_delivery_followup: "交付跟进",
    open_browser_observation: "录入网页观测",
    run_real_provider_smoke: "真实模型小样本",
    run_full_loop: "一键闭环"
  };
  return labels[value] ?? value;
}

function providerModeLabel(value?: string) {
  const labels: Record<string, string> = {
    real: "真实渠道",
    mock: "Mock 演示",
    not_ready: "待配置"
  };
  return labels[value ?? ""] ?? "待确认";
}

function searchAccessLabel(value?: string) {
  const labels: Record<string, string> = {
    api_ready_no_live_search: "普通 API",
    needs_config: "待配置",
    ready_for_collection: "联网可采集",
    ready_for_demo: "演示可用"
  };
  return labels[value ?? ""] ?? "待确认";
}

function isProviderPreflightError(message?: string | null) {
  return Boolean(message?.includes("Provider preflight failed"));
}

function asRoute(value: string) {
  return value as Route;
}

const BROWSER_OBSERVATION_PLATFORMS = ["豆包", "DeepSeek", "Kimi", "千问", "腾讯元宝", "其他"];
const BROWSER_OBSERVATION_PLATFORM_LINKS = [
  { platform_name: "豆包", api_base_url: "https://www.doubao.com/chat/" },
  { platform_name: "DeepSeek", api_base_url: "https://chat.deepseek.com/" },
  { platform_name: "Kimi", api_base_url: "https://www.kimi.com/" },
  { platform_name: "千问", api_base_url: "https://www.qianwen.com/" }
];

export default async function ProjectDetailPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const queryParams = await searchParams;
  const [
    project,
    questions,
    keywords,
    competitors,
    results,
    tasks,
    schedules,
    metrics,
    reports,
    drafts,
    assets,
    placements,
    reviewArchive,
    browserObservations,
    openAlerts,
    acknowledgedAlerts,
    stageGoals,
    operatingTrends,
    operationalReadiness,
    providers,
    mvpStatus,
    providerNetworkCheck
  ] = await Promise.all([
    getProject(id),
    getTargetQuestions(id),
    getKeywords(id),
    getCompetitors(id),
    getCrawlResults(id),
    getCrawlTasks(id).catch(() => []),
    getCrawlSchedules(id).catch(() => []),
    getSearchMetrics(id).catch(() => null),
    getMaturityReports(id).catch(() => []),
    getArticleDrafts(id).catch(() => []),
    getContentAssets(id).catch(() => []),
    getPlacements(id).catch(() => []),
    getPlacementReviewArchive(id).catch(() => []),
    getBrowserObservations(id, 50).catch(() => []),
    getAlerts("open", { projectId: id, limit: 100 }).catch(() => []),
    getAlerts("acknowledged", { projectId: id, limit: 100 }).catch(() => []),
    getProjectStageGoals(id).catch(() => []),
    getProjectOperatingTrends(id, 14).catch(() => ({ project_id: Number(id), days: 14, points: [] })),
    getProjectOperationalReadiness(id).catch(() => null),
    getLLMProviders().catch(() => []),
    getProjectMvpStatus(id).catch(() => null),
    getLatestProviderNetworkCheck().catch(() => null)
  ]);
  const browserObservationPackStatus = Number(id) === 1 ? await readBrowserObservationPackStatus() : null;
  const runCrawl = runCrawlAction.bind(null, id);
  const createSchedule = createCrawlScheduleAction.bind(null, id);
  const createBrowserObservation = createBrowserObservationAction.bind(null, id);
  const bulkCreateBrowserObservations = bulkCreateBrowserObservationsAction.bind(null, id);
  const runDueSchedules = runDueCrawlSchedulesAction.bind(null, id);
  const generateReport = generateReportAction.bind(null, id);
  const validateObservationPack = validateBrowserObservationPackAction.bind(null, id);
  const importObservationPack = importBrowserObservationPackAction.bind(null, id);
  const prepareObservationPack = prepareBrowserObservationPackAction.bind(null, id);
  const runDiagnostic = runDiagnosticAction.bind(null, id);
  const appendProjectConfig = appendProjectConfigAction.bind(null, id);
  const generateDraftAndReview = generateDraftAndReviewAction.bind(null, id);
  const createStageGoal = createProjectStageGoalAction.bind(null, id);
  const seedMaturityConfig = seedMaturityConfigAction.bind(null, id);
  const runStageGoalReminders = runProjectStageGoalRemindersAction.bind(null, id);
  const latestReport = reports[0];
  const readyRan = queryParams.ready_ran ? Number(queryParams.ready_ran) : null;
  const readyFailed = queryParams.ready_failed ? Number(queryParams.ready_failed) : 0;
  const readyPending = queryParams.ready_pending ? Number(queryParams.ready_pending) : 0;
  const draftReviews = await Promise.all(
    drafts.slice(0, 5).map(async (draft) => ({
      draftId: draft.id,
      reviews: await getArticleReviews(id, draft.id).catch(() => [])
    }))
  );
  const reviewMap = new Map(draftReviews.map((item) => [item.draftId, item.reviews]));
  const providerNetworkFailures = providerNetworkCheck?.results.filter((item) => !item.ok) ?? [];
  const providerNetworkEnvironmentBlocked =
    providerNetworkFailures.length > 0 &&
    providerNetworkFailures.length === (providerNetworkCheck?.results.length ?? 0) &&
    providerNetworkFailures.every((item) => item.error_stage === "dns");
  const stageGoalTimelineEntries = await Promise.all(
    stageGoals.map(async (goal) => ({
      goalId: goal.id,
      items: await getProjectStageGoalTimeline(id, goal.id).catch(() => [])
    }))
  );
  const stageGoalTimelineMap = new Map(stageGoalTimelineEntries.map((entry) => [entry.goalId, entry.items]));
  const approvedDrafts = drafts.filter((draft) => draft.status === "approved").length;
  const approvedAssets = assets.filter((asset) => asset.status === "approved").length;
  const publishedPlacements = placements.filter((placement) => placement.status === "published");
  const deliverablePlacements = placements.filter(
    (placement) => placement.visibility === "customer_visible" && ["ready", "delivered", "accepted"].includes(placement.delivery_status)
  );
  const acceptedDeliveries = deliverablePlacements.filter((placement) => placement.delivery_status === "accepted").length;
  const reviewedPlacements = reviewArchive.filter((item) => item.impact?.review_report.evidence.review_crawl_task_id).length;
  const positiveReviews = reviewArchive.filter((item) => item.impact?.review_report.status === "positive").length;
  const followUpAlerts = [...openAlerts, ...acknowledgedAlerts].filter((alert) => alert.alert_type === "delivery.confirmed");
  const stageGoalAlerts = [...openAlerts, ...acknowledgedAlerts].filter((alert) =>
    ["stage_goal.overdue", "stage_goal.at_risk"].includes(alert.alert_type)
  );
  const maturityScore = latestReport?.total_score ?? 0;
  const geoHealthScore = Math.round(
    Math.min(100, maturityScore * 0.45)
      + Math.min(20, (metrics?.company_recommendation_rate ?? 0) * 20)
      + Math.min(15, reviewedPlacements * 5)
      + Math.min(10, acceptedDeliveries * 5)
      + Math.min(10, (approvedDrafts + approvedAssets) * 2)
  );
  const latestTrend = operatingTrends.points.at(-1);
  const firstTrend = operatingTrends.points[0];
  const healthDelta = latestTrend && firstTrend ? latestTrend.health_score - firstTrend.health_score : 0;
  const recommendationDelta =
    latestTrend && firstTrend ? Math.round((latestTrend.recommendation_rate - firstTrend.recommendation_rate) * 100) : 0;
  const maxTrendValue = Math.max(
    1,
    ...operatingTrends.points.map((point) =>
      Math.max(point.health_score, point.maturity_score, point.answer_count, point.approved_content_count * 10)
    )
  );
  const metricOptions: Array<[string, string]> = [
    ["health_score", "健康度"],
    ["maturity_score", "成熟度"],
    ["recommendation_rate", "推荐率"],
    ["approved_content_count", "已通过内容"],
    ["published_placement_count", "已发布投放"],
    ["accepted_delivery_count", "客户确认交付"],
    ["answer_count", "AI 答案样本"],
    ["browser_observation_count", "网页端观测"]
  ];
  const metricLabel = new Map<string, string>(metricOptions);
  const mvpDeltas = mvpStatus?.stage_goal.metric_deltas ?? {};
  const crawlHealth = mvpStatus?.crawl_health;
  const activeProviders = providers.filter((provider) => provider.status === "active");
  const providerNameById = new Map(providers.map((provider) => [provider.id, provider.name]));
  const providerStatusById = new Map((mvpStatus?.providers ?? []).map((provider) => [provider.provider_id, provider]));
  const crawlProviderOptions = activeProviders.map((provider) => ({
    id: provider.id,
    name: provider.name,
    provider_type: provider.provider_type,
    cost_rule: provider.cost_rule,
    collection_ready: provider.provider_type === "mock" || Boolean(providerStatusById.get(provider.id)?.collection_ready)
  }));
  const diagnosticProviders = crawlProviderOptions.filter((provider) => provider.collection_ready).slice(0, 3);
  const realSmokeProviders = activeProviders
    .filter(
      (provider) =>
        provider.provider_type !== "mock" &&
        provider.provider_type !== "browser_observation" &&
        Boolean(providerStatusById.get(provider.id)?.collection_ready)
    )
    .slice(0, 3);
  const realSmokeQuestion = questions[0];
  const realSmokeCallCount = realSmokeProviders.length * (realSmokeQuestion ? 1 : 0);
  const browserObservationProviders = activeProviders.filter((provider) => provider.provider_type === "browser_observation");
  const browserObservationEntryLinks =
    browserObservationProviders.length > 0
      ? browserObservationProviders.map((provider) => ({
          id: provider.id,
          platform_name: String(provider.cost_rule?.platform_name ?? provider.name),
          api_base_url: provider.api_base_url
        }))
      : BROWSER_OBSERVATION_PLATFORM_LINKS.map((item) => ({ ...item, id: item.platform_name }));
  const questionTextById = new Map(questions.map((question) => [question.id, question.question_text]));
  const keywordTextById = new Map(keywords.map((keyword) => [keyword.id, keyword.keyword]));
  const reportDraftTopics = [
    ...(latestReport?.report_json.next_content_topics ?? []),
    ...(latestReport?.report_json.question_gaps ?? []).map((gap) => gap.question_text),
    ...(latestReport?.report_json.keyword_gaps ?? []).map((gap) => `${gap.keyword}怎么做 GEO 优化`)
  ].filter((topic, index, list) => topic && list.indexOf(topic) === index);
  const providerTestPrompt =
    questions[0]?.question_text ??
    (keywords[0] ? `${keywords[0].keyword} 相关服务商怎么选？` : "网络安全培训公司哪家好？");
  const providerTestQuery = `prompt=${encodeURIComponent(providerTestPrompt)}&return_to=${encodeURIComponent(
    `/projects/${id}`
  )}`;
  const configAddedCount = Number(queryParams.config_added ?? 0);
  const diagnosticTaskId = Number(queryParams.diagnostic_task ?? 0);
  const diagnosticStatus = queryParams.diagnostic_status ?? "";
  const diagnosticReportId = Number(queryParams.diagnostic_report ?? 0);
  const diagnosticGoalCount = Number(queryParams.diagnostic_goals ?? 0);
  const diagnosticExpectedCount = Number(queryParams.diagnostic_expected ?? 0);
  const diagnosticResultCount = Number(queryParams.diagnostic_results ?? 0);
  const diagnosticEstimatedCost = Number(queryParams.diagnostic_estimated_cost ?? 0);
  const diagnosticEstimatedTokens = Number(queryParams.diagnostic_estimated_tokens ?? 0);
  const diagnosticBlockers = queryParams.diagnostic_blockers ?? "";
  const diagnosticCostText =
    diagnosticEstimatedTokens > 0 || diagnosticEstimatedCost > 0
      ? ` 预估 ${Math.round(diagnosticEstimatedTokens)} tokens，成本约 ${diagnosticEstimatedCost.toFixed(6)}。`
      : "";
  const observeReportId = Number(queryParams.observe_report_id ?? 0);
  const observeQuestionId = Number(queryParams.observe_question_id ?? 0);
  const observeKeywordId = Number(queryParams.observe_keyword_id ?? 0);
  const observePlatform = String(queryParams.observe_platform ?? "豆包") || "豆包";
  const observationCreated = queryParams.observation_created === "1";
  const observationBulkCreated = Number(queryParams.observation_bulk_created ?? 0);
  const observationBulkSourceCount = Number(queryParams.observation_bulk_sources ?? 0);
  const observationBulkScreenshotCount = Number(queryParams.observation_bulk_screenshots ?? 0);
  const observationValidatedCount = Number(queryParams.observation_validated ?? 0);
  const observationValidatedPlatformCount = Number(queryParams.observation_validated_platforms ?? 0);
  const observationResultId = Number(queryParams.observation_result ?? 0);
  const observationSourceCount = Number(queryParams.observation_sources ?? 0);
  const observationScreenshotCount = Number(queryParams.observation_screenshots ?? 0);
  const packPreparedCount = Number(queryParams.pack_prepared ?? 0);
  const nextPackPreparedCount = Number(queryParams.next_pack_prepared ?? 0);
  const coveredQuestionIds = new Set(results.map((result) => result.target_question_id).filter(Boolean));
  const coveredKeywordIds = new Set(results.map((result) => result.keyword_id).filter(Boolean));
  const coveredProviderIds = new Set(results.map((result) => result.provider_id).filter(Boolean));
  const requiredBrowserPlatforms = BROWSER_OBSERVATION_PLATFORM_LINKS.map((platform) => platform.platform_name);
  const browserObservedPlatformNames = new Set(browserObservations.map((item) => item.platform_name).filter(Boolean).map(String));
  const browserObservedPlatformQuestionKeys = new Set(
    browserObservations
      .filter((item) => item.platform_name && item.target_question_id)
      .map((item) => `${item.platform_name}:${item.target_question_id}`)
  );
  const browserObservedPlatformKeywordKeys = new Set(
    browserObservations
      .filter((item) => item.platform_name && item.keyword_id)
      .map((item) => `${item.platform_name}:${item.keyword_id}`)
  );
  const fullyObservedQuestionIds = new Set(
    questions
      .filter((question) =>
        requiredBrowserPlatforms.every((platform) => browserObservedPlatformQuestionKeys.has(`${platform}:${question.id}`))
      )
      .map((question) => question.id)
  );
  const fullyObservedKeywordIds = new Set(
    keywords
      .filter((keyword) =>
        requiredBrowserPlatforms.every((platform) => browserObservedPlatformKeywordKeys.has(`${platform}:${keyword.id}`))
      )
      .map((keyword) => keyword.id)
  );
  const browserObservationQuestionGaps = questions.filter((question) => !fullyObservedQuestionIds.has(question.id));
  const browserObservationKeywordGaps = keywords.filter((keyword) => !fullyObservedKeywordIds.has(keyword.id));
  const requestedObservationQuestion = questions.find((question) => question.id === observeQuestionId);
  const requestedObservationKeyword = keywords.find((keyword) => keyword.id === observeKeywordId);
  const suggestedObservationQuestion = browserObservationQuestionGaps[0] ?? questions[0];
  const suggestedObservationKeyword = browserObservationKeywordGaps[0] ?? keywords[0];
  const selectedObservationQuestion = requestedObservationQuestion ?? (requestedObservationKeyword ? undefined : suggestedObservationQuestion);
  const selectedObservationKeyword = requestedObservationKeyword ?? (selectedObservationQuestion ? undefined : suggestedObservationKeyword);
  const selectedObservationProvider = browserObservationProviders.find(
    (provider) => String(provider.cost_rule?.platform_name ?? provider.name) === observePlatform
  );
  const browserObservationTasks = questions.slice(0, 10).flatMap((question) =>
    BROWSER_OBSERVATION_PLATFORM_LINKS.map((platform) => ({
      platform_name: platform.platform_name,
      api_base_url: platform.api_base_url,
      question,
      observed: browserObservedPlatformQuestionKeys.has(`${platform.platform_name}:${question.id}`)
    }))
  );
  const nextBrowserObservationTasks = browserObservationTasks.filter((task) => !task.observed).slice(0, 8);
  const browserPlatformCoverageText = `${browserObservedPlatformNames.size}/${BROWSER_OBSERVATION_PLATFORM_LINKS.length}`;
  const browserObservationChecklist = browserObservationTasks
    .filter((task) => !task.observed)
    .map(
      (task, index) =>
        `${index + 1}. [${task.platform_name}] ${task.question.question_text}\n` +
        `   网页入口：${task.api_base_url}\n` +
        `   提问文本：${task.question.question_text}\n` +
        "   执行动作：复制完整答案，保存截图或录屏地址，记录页面可见信源 URL。"
    )
    .join("\n\n");
  const nextObservationPrompt =
    queryParams.observe_prompt ||
    selectedObservationQuestion?.question_text ||
    (selectedObservationKeyword ? `${selectedObservationKeyword.keyword} 相关服务商怎么选？` : providerTestPrompt);
  const selectedObservationPlatformLinks = BROWSER_OBSERVATION_PLATFORM_LINKS.filter((platform) => {
    if (selectedObservationQuestion) {
      return !browserObservedPlatformQuestionKeys.has(`${platform.platform_name}:${selectedObservationQuestion.id}`);
    }
    if (selectedObservationKeyword) {
      return !browserObservedPlatformKeywordKeys.has(`${platform.platform_name}:${selectedObservationKeyword.id}`);
    }
    return true;
  });
  const browserObservationTemplatePlatforms =
    selectedObservationPlatformLinks.length > 0 ? selectedObservationPlatformLinks : BROWSER_OBSERVATION_PLATFORM_LINKS;
  const browserObservationEvidenceType = selectedObservationQuestion ? "question" : "keyword";
  const browserObservationEvidenceId = selectedObservationQuestion?.id ?? selectedObservationKeyword?.id ?? "manual";
  const browserObservationBulkExample = JSON.stringify(
    browserObservationTemplatePlatforms.map((platform) => ({
      platform_name: platform.platform_name,
      target_question_id: selectedObservationQuestion?.id,
      keyword_id: selectedObservationKeyword?.id,
      prompt_text: nextObservationPrompt,
      raw_answer: "粘贴该平台网页端返回的完整答案",
      answer_summary: "可选：一句话摘要",
      observation_url: platform.api_base_url,
      evidence_filename: `${platform.platform_name}-${browserObservationEvidenceType}-${browserObservationEvidenceId}.png`,
      screenshot_url: "",
      source_urls: ["https://example.com/source"],
      observer_name: "运营同事",
      note: "网页端人工观测，含截图留证"
    })),
    null,
    2
  );
  const browserObservationDownloadTemplate = JSON.stringify(
    {
      project: {
        id: project.id,
        name: project.name,
        target_industry: project.target_industry,
        target_audience: project.target_audience
      },
      instructions: [
        "在外部浏览器打开 observation_url。",
        "复制 prompt_text 到对应平台提问。",
        "把完整答案填入 raw_answer。",
        "保存截图或录屏；推荐把文件放到同一个证据目录，并在 evidence_filename 填文件名。",
        "如果不使用证据目录，也可以把本地 file:// 路径或共享链接填入 screenshot_url。",
        "把页面可见信源填入 source_urls；如果没有可见信源，填空数组 []。",
        "填完后可在本页批量录入，也可运行 scripts/import_browser_observations.py --project-id 1 --input 本文件 --generate-draft。"
      ],
      observations: JSON.parse(browserObservationBulkExample)
    },
    null,
    2
  );
  const browserObservationDownloadHref = `data:application/json;charset=utf-8,${encodeURIComponent(
    browserObservationDownloadTemplate
  )}`;
  const browserObservationWorkOrderMarkdown = [
    `# ${project.name} 网页端 GEO 采集工单`,
    "",
    "## 执行目标",
    "",
    "在外部浏览器分别打开豆包、DeepSeek、Kimi、千问网页端，使用同一目标问题提问，复制完整答案，保存截图或录屏，并把结果填回 JSON 模板。",
    "",
    "## 填写规则",
    "",
    "- `raw_answer`：粘贴网页端返回的完整答案，不要只写摘要。",
    "- `answer_summary`：用一句话概括该平台回答。",
    "- `source_urls`：填页面可见信源 URL；如果没有可见信源，填 `[]`。",
    "- `evidence_filename`：推荐填写截图/录屏文件名，并把文件统一放到证据目录。",
    "- `screenshot_url`：如果不用证据目录，可填本地 `file://` 路径、对象存储地址或共享链接。",
    "- 保留 `platform_name`、`provider_id`、`target_question_id`、`prompt_text` 不变。",
    "",
    "## 采集任务",
    "",
    ...BROWSER_OBSERVATION_PLATFORM_LINKS.flatMap((platform, index) => [
      `### ${index + 1}. ${platform.platform_name}`,
      "",
      `- 网页入口：${platform.api_base_url}`,
      `- 目标问题：${nextObservationPrompt}`,
      `- 截图文件名：\`${platform.platform_name}-question-${selectedObservationQuestion?.id ?? "keyword"}.png\``,
      "- 操作步骤：",
      "  1. 打开网页入口。",
      "  2. 复制目标问题并提问。",
      "  3. 等待答案完整生成。",
      "  4. 复制完整答案到 JSON 的 `raw_answer`。",
      "  5. 截图或录屏，文件名保持为 JSON 中的 `evidence_filename`；如使用外部链接，则填入 `screenshot_url`。",
      "  6. 如果页面展示来源，把 URL 填入 `source_urls`。",
      ""
    ]),
    "## 导入前校验",
    "",
    "填完 JSON 后先执行 dry-run，不写入数据库：",
    "",
    "```bash",
    "UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/import_browser_observations.py \\",
    "  --project-id 1 \\",
    "  --input ../../outputs/yuanquan_browser_observation_q1_template.json \\",
    "  --evidence-dir ../../outputs/browser-observation-evidence/raw-yuanquan-q1 \\",
    "  --dry-run",
    "```",
    "",
    "## 正式导入",
    "",
    "dry-run 通过后执行：",
    "",
    "```bash",
    "UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/import_browser_observations.py \\",
    "  --project-id 1 \\",
    "  --input ../../outputs/yuanquan_browser_observation_q1_template.json \\",
    "  --evidence-dir ../../outputs/browser-observation-evidence/raw-yuanquan-q1 \\",
    "  --generate-draft",
    "```",
    ""
  ].join("\n");
  const browserObservationWorkOrderHref = `data:text/markdown;charset=utf-8,${encodeURIComponent(
    browserObservationWorkOrderMarkdown
  )}`;
  const questionCoverageRate = questions.length > 0 ? coveredQuestionIds.size / questions.length : 0;
  const keywordCoverageRate = keywords.length > 0 ? coveredKeywordIds.size / keywords.length : 0;
  const reportSampleStatus =
    results.length >= 20 && questionCoverageRate >= 0.8 && keywordCoverageRate >= 0.8
      ? "ready"
      : results.length >= 10
        ? "partial"
        : "thin";
  const reportSampleLabel: Record<string, string> = {
    ready: "样本充足",
    partial: "可先生成",
    thin: "样本偏薄"
  };
  const reportSampleSuggestion: Record<string, string> = {
    ready: "当前样本量和问题/关键词覆盖度较好，可生成客户版成熟度报告。",
    partial: "当前样本可用于内部判断，正式客户报告建议继续补齐问题、关键词或真实模型渠道。",
    thin: "建议先补跑搜索采集，至少形成 10 条以上答案样本后再生成报告。"
  };

  return (
    <div className="stack">
      <div className="topbar" id="top">
        <div>
          <div className="eyebrow">项目详情</div>
          <h1>{project.name}</h1>
          <p className="subtle">{project.description ?? "配置目标问题、关键词和竞品后即可发起搜索采集。"}</p>
        </div>
        <CrawlLaunchForm action={runCrawl} providers={crawlProviderOptions} questions={questions} keywords={keywords} />
        {realSmokeProviders.length > 0 && realSmokeQuestion ? (
          <div className="crawl-launch-form" id="real-provider-smoke">
            <form action={runDiagnostic} className="inline-form">
              {realSmokeProviders.map((provider) => (
                <input key={provider.id} type="hidden" name="provider_ids" value={provider.id} />
              ))}
              <input type="hidden" name="target_question_ids" value={realSmokeQuestion.id} />
              <input type="hidden" name="title" value={`真实模型小样本诊断 - ${project.name}`} />
              <input type="hidden" name="report_period" value="real_provider_smoke" />
              <input
                name="max_estimated_cost"
                type="number"
                min="0"
                step="0.000001"
                placeholder="预算上限"
                aria-label="真实模型诊断预算上限"
              />
              <SubmitButton
                className="button secondary"
                pendingText="真实诊断中..."
                title="使用前 3 个已就绪真实 Provider 采集第 1 个目标问题，并生成报告和阶段目标"
              >
                真实模型诊断
              </SubmitButton>
            </form>
            <div className="crawl-estimate paid">
              <span>预计 {realSmokeCallCount} 次真实 API 调用，会生成报告和阶段目标</span>
              <span>模型 {realSmokeProviders.map((provider) => provider.name).join("、")}</span>
              <span>问题：{realSmokeQuestion.question_text}</span>
            </div>
          </div>
        ) : (
          <div className="crawl-launch-form" id="real-provider-smoke">
            <Link className="button secondary" href={`/admin/providers?return_to=/projects/${id}`}>
              配置真实渠道
            </Link>
            <div className="crawl-estimate">
              <span>{realSmokeQuestion ? "还没有已测试通过的真实 Provider" : "还没有目标问题"}</span>
              <span>完成后可运行 1 个问题 x 3 个模型的小样本对比</span>
            </div>
          </div>
        )}
        <form action={generateReport}>
          <SubmitButton className="button secondary" pendingText="生成报告中...">
            生成成熟度报告
          </SubmitButton>
        </form>
        <form action={runDiagnostic}>
          {diagnosticProviders.map((provider) => (
            <input key={provider.id} type="hidden" name="provider_ids" value={provider.id} />
          ))}
          <input
            name="max_estimated_cost"
            type="number"
            min="0"
            step="0.000001"
            placeholder="诊断预算上限"
            aria-label="一键诊断预算上限"
          />
          <SubmitButton pendingText="诊断中..." title="立即采集当前项目范围，生成成熟度报告并沉淀阶段目标">
            一键诊断
          </SubmitButton>
        </form>
        <Link className="button secondary" href={asRoute(`/projects/${id}/reports`)}>
          报告中心
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/dashboard`)}>
          交付驾驶舱
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/geo`)}>
          GEO 决策地图
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/config`)}>
          项目配置
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/answers`)}>
          搜索结果
        </Link>
        <Link className="button secondary" href={`/projects/${id}/assets`}>
          内容资产库
        </Link>
        <Link className="button secondary" href={`/projects/${id}/sources`}>
          信源与投放
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/placements`)}>
          投放计划
        </Link>
        <Link className="button secondary" href={`/projects/${id}/calendar`}>
          内容日历
        </Link>
        <Link className="button secondary" href={`/projects/${id}/review-archive`}>
          复盘归档
        </Link>
        <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
          客户交付包
        </Link>
      </div>

      {queryParams.action_error ? (
        <div className="notice danger">
          操作没有完成：{queryParams.action_error}
        </div>
      ) : null}

      {operationalReadiness ? (
        <section className="panel">
          <div className="section-head">
            <div>
              <h2>正式运营就绪度</h2>
              <p className="subtle">
                {operationalReadiness.summary}。已满足 {operationalReadiness.ok_count}/{operationalReadiness.check_count} 项，真实平台就绪{" "}
                {operationalReadiness.ready_platform_count}/{operationalReadiness.required_platform_count}。
              </p>
            </div>
            <span className={operationalReadiness.status === "ready" ? "tag active" : "tag"}>
              {operationalReadiness.status === "ready"
                ? "可持续运行"
                : operationalReadiness.status === "partial"
                  ? "部分可用"
                  : "待补齐"}
            </span>
          </div>
          {providerNetworkCheck?.available && providerNetworkEnvironmentBlocked ? (
            <div className="notice danger">
              Provider 网络预检显示当前运行环境 DNS 阻塞：{providerNetworkFailures.length} 个真实渠道域名均无法解析。先修复外网/DNS 后，再判断
              DeepSeek、Kimi、千问的 Key、模型权限和采集链路。
            </div>
          ) : null}
          <div className="grid cols-4">
            {operationalReadiness.platforms.map((platform) => (
              <div className="metric" key={platform.key}>
                <span>{platform.label}</span>
                <strong>{platform.ready ? "已采集" : platform.active ? "待补跑" : platform.configured ? "待启用" : "未配置"}</strong>
                <small>
                  结果 {platform.project_result_count} 条
                  {platform.latest_test_ok ? "｜测试通过" : "｜未通过测试"}
                </small>
                {platform.blockers.length > 0 ? <small>{platform.blockers[0]}</small> : null}
              </div>
            ))}
          </div>
          <div className="grid cols-4">
            {operationalReadiness.checks.map((check) => (
              <div className="metric" key={check.key}>
                <span>{check.label}</span>
                <strong>{check.ok ? "完成" : "待办"}</strong>
                <small>{check.detail}</small>
                {check.next_action ? <small>{check.next_action}</small> : null}
              </div>
            ))}
          </div>
          <div className="row-actions">
            <Link className="button secondary" href="/admin/providers">
              配置模型渠道
            </Link>
            <Link className="button secondary" href={asRoute(`/projects/${id}/drafts`)}>
              进入撰稿审核
            </Link>
            <Link className="button secondary" href={asRoute(`/projects/${id}/placements`)}>
              推进投放承接
            </Link>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>诊断输入完整度</h2>
            <p className="subtle">成熟度研判建议先准备 10 个目标问题、10 个关键词、竞品和可审核/可投放内容。</p>
          </div>
          <span className={project.diagnostic_readiness_status === "ready" ? "tag active" : "tag"}>
            {project.diagnostic_readiness_score ?? 0}%
          </span>
        </div>
        {diagnosticTaskId > 0 && diagnosticStatus === "failed" ? (
          <div className="notice danger">
            诊断任务 #{diagnosticTaskId} 未完成：{diagnosticBlockers || "采集任务失败，请查看任务详情。"}
            {diagnosticExpectedCount > 0 ? ` 本次原计划调用 ${diagnosticExpectedCount} 次，实际生成 ${diagnosticResultCount} 条结果。` : ""}
            {diagnosticCostText}
            <Link className="inline-link" href={asRoute(`/projects/${id}/tasks/${diagnosticTaskId}`)}>
              查看任务
            </Link>
          </div>
        ) : null}
        {diagnosticTaskId > 0 && diagnosticStatus !== "failed" ? (
          <div className="notice success">
            已完成一键诊断任务 #{diagnosticTaskId}
            {diagnosticReportId > 0 ? `，生成报告 #${diagnosticReportId}` : ""}
            {Number.isFinite(diagnosticGoalCount) ? `，新增阶段目标 ${diagnosticGoalCount} 个` : ""}
            {diagnosticExpectedCount > 0 ? `，计划调用 ${diagnosticExpectedCount} 次，生成 ${diagnosticResultCount} 条结果` : ""}。
            {diagnosticCostText}
          </div>
        ) : null}
        <div className="grid cols-4">
          {(project.diagnostic_readiness_checks ?? []).map((check) => (
            <div className="metric" key={check.key}>
              <span>{check.label}</span>
              <strong>
                {check.current}/{check.required}
              </strong>
              <small>{check.ok ? "已满足" : check.help_text}</small>
            </div>
          ))}
        </div>
        {project.diagnostic_readiness_status !== "ready" ? (
          <div className="row-actions">
            <Link className="button secondary" href={`/projects/${id}#project-config`}>
              补齐问题关键词
            </Link>
            <Link className="button secondary" href={asRoute(`/projects/${id}/config`)}>
              配置工作台
            </Link>
            <form action={seedMaturityConfig}>
              <SubmitButton className="button secondary" pendingText="补齐中...">
                自动补齐 10+10
              </SubmitButton>
            </form>
            <Link className="button secondary" href={`/projects/${id}/assets`}>
              导入内容资产
            </Link>
            <Link className="button secondary" href={`/projects/${id}/sources`}>
              维护投放信源
            </Link>
          </div>
        ) : null}
        <div className="row-actions">
          <form action={runDiagnostic}>
            {diagnosticProviders.map((provider) => (
              <input key={provider.id} type="hidden" name="provider_ids" value={provider.id} />
            ))}
            <SubmitButton pendingText="采集诊断中...">采集并生成诊断报告</SubmitButton>
          </form>
          <small className="subtle">
            默认使用 {diagnosticProviders.length || 1} 个可采集模型，覆盖项目内全部目标问题和关键词。
          </small>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>MVP 闭环状态</h2>
            <p className="subtle">从数据库实时汇总搜索采集、成熟度报告、撰稿审核、投放复盘和客户交付。</p>
          </div>
          <div className="row-actions">
            <span className={mvpStatus?.ok ? "tag active" : "tag"}>
              {mvpStatus?.ok ? "闭环已跑通" : "闭环待补齐"}
            </span>
            <Link className="button secondary" href="/demo">
              演示总览
            </Link>
          </div>
        </div>
        {mvpStatus ? (
          <div className="stack">
            <div className="grid cols-4">
              <div className="metric">
                <span>搜索采集</span>
                <strong>{crawlHealth ? statusLabel(crawlHealth.status) : "待确认"}</strong>
                <small>
                  样本 {crawlHealth?.total_result_count ?? results.length}｜任务 {crawlHealth?.total_tasks ?? tasks.length}
                </small>
              </div>
              <div className="metric">
                <span>最新报告</span>
                <strong>{mvpStatus.report_ids.at(-1) ?? "暂无"}</strong>
                <small>{mvpStatus.latest_report_url ? "可查看成熟度报告" : "先生成成熟度报告"}</small>
              </div>
              <div className="metric">
                <span>阶段目标</span>
                <strong>{statusLabel(mvpStatus.stage_goal.goal_status)}</strong>
                <small>ID {mvpStatus.stage_goal.goal_id ?? "-"}</small>
              </div>
              <div className="metric">
                <span>复盘结论</span>
                <strong>{statusLabel(mvpStatus.stage_goal.review_status)}</strong>
                <small>
                  提及 {pct(mvpDeltas.company_mention_rate_delta ?? 0)}｜推荐{" "}
                  {pct(mvpDeltas.company_recommendation_rate_delta ?? 0)}
                </small>
              </div>
              <div className="metric">
                <span>客户交付</span>
                <strong>{statusLabel(mvpStatus.stage_goal.delivery_status)}</strong>
                <small>Share {mvpStatus.stage_goal.share_id ?? "-"}</small>
              </div>
            </div>
            <div className="row review-row">
              <div>
                <div className="meta-line">
                  <span>{providerModeLabel(mvpStatus.provider_summary.mode)}</span>
                  <span>可用 {mvpStatus.provider_summary.ready ?? 0}/{mvpStatus.provider_summary.total ?? 0}</span>
                  <span>真实可采集 {mvpStatus.provider_summary.real_collection_ready ?? 0}</span>
                  <span>联网搜索 {mvpStatus.provider_summary.web_search_ready ?? 0}</span>
                </div>
                <h3>模型渠道就绪度</h3>
                <small>
                  {mvpStatus.provider_summary.has_real_provider
                    ? "已配置可用真实模型渠道，可以进行真实搜索采集验证。"
                    : "当前闭环主要依赖 Mock Provider；真实大模型检索还需要配置 API Key 或中转站渠道。"}
                </small>
                {mvpStatus.providers.length > 0 ? (
                  <div className="mini-list">
                    {mvpStatus.providers.slice(0, 3).map((provider) => (
                      <Link
                        href={asRoute(`/admin/providers/${provider.provider_id}/test?${providerTestQuery}`)}
                        key={provider.provider_id}
                      >
                        {provider.name}｜{provider.provider_type}｜{searchAccessLabel(provider.search_access_status)}｜
                        {provider.search_mode}｜{provider.collection_ready ? "可采集" : "不可采集"}{" "}
                        {provider.collection_blocker ? `｜${provider.collection_blocker}` : ""}
                        {provider.missing.length > 0 ? `｜缺 ${provider.missing.join("、")}` : ""}
                        {provider.latest_test_ok === false ? `｜最近测试失败：${provider.latest_test_error ?? "未知错误"}` : ""}
                      </Link>
                    ))}
                  </div>
                ) : null}
              </div>
              <Link className="button secondary" href="/admin/providers">
                配置模型渠道
              </Link>
            </div>
            <div className="grid cols-3">
              {mvpStatus.checks.map((check) => (
                <div className="row review-row" key={check.check}>
                  <div>
                    <div className="meta-line">
                      <span>{check.ok ? "通过" : "待补齐"}</span>
                      {check.status ? <span>{statusLabel(check.status)}</span> : null}
                    </div>
                    <h3>{checkLabel(check.check)}</h3>
                    <small>
                      {typeof check.total_score === "number"
                        ? `${check.total_score} 分｜${check.maturity_level ?? ""}`
                        : null}
                      {typeof check.event_count === "number" ? `${check.event_count} 个事件` : null}
                      {typeof check.deliverable_count === "number" ? `${check.deliverable_count} 份交付` : null}
                      {check.metric_deltas
                        ? `提及 ${pct(check.metric_deltas.company_mention_rate_delta ?? 0)}｜推荐 ${pct(
                            check.metric_deltas.company_recommendation_rate_delta ?? 0
                          )}`
                        : null}
                    </small>
                    {check.reason ? <small>{check.reason}</small> : null}
                  </div>
                  <div className="row-actions">
                    <span className={check.ok ? "tag active" : "tag"}>{check.ok ? "OK" : "TODO"}</span>
                    {check.next_action_type === "generate_report" ? (
                      <form action={generateReport}>
                        <button className="button secondary" type="submit">
                          {check.next_action_label ?? "生成报告"}
                        </button>
                      </form>
                    ) : null}
                    {check.next_action_type === "run_crawl" && mvpStatus.stage_goal.goal_id ? (
                      <form
                        action={runProjectStageGoalActionAction.bind(
                          null,
                          id,
                          mvpStatus.stage_goal.goal_id,
                          "run_crawl"
                        )}
                      >
                        <button className="button secondary" type="submit">
                          {check.next_action_label ?? "发起采集"}
                        </button>
                      </form>
                    ) : null}
                    {check.next_action_type === "run_crawl" && !mvpStatus.stage_goal.goal_id ? (
                      <form action={runCrawl}>
                        <button className="button secondary" type="submit">
                          {check.next_action_label ?? "发起采集"}
                        </button>
                      </form>
                    ) : null}
                    {check.next_action_type === "retry_crawl_task" && crawlHealth?.latest_task_id ? (
                      <form action={retryCrawlTaskAction.bind(null, id, crawlHealth.latest_task_id)}>
                        <button className="button secondary" type="submit">
                          {check.next_action_label ?? "重试采集"}
                        </button>
                      </form>
                    ) : null}
                    {check.next_action_type === "open_task" && check.next_action_url ? (
                      <Link className="button secondary" href={asRoute(check.next_action_url)}>
                        {check.next_action_label ?? "查看任务"}
                      </Link>
                    ) : null}
                    {check.next_action_type === "run_full_loop" && mvpStatus.stage_goal.goal_id ? (
                      <form
                        action={runProjectStageGoalActionAction.bind(
                          null,
                          id,
                          mvpStatus.stage_goal.goal_id,
                          "run_full_loop"
                        )}
                      >
                        <button className="button" type="submit">
                          {check.next_action_label ?? "一键跑通闭环"}
                        </button>
                      </form>
                    ) : null}
                    {check.next_action_type === "publish_prepare_delivery" && mvpStatus.stage_goal.goal_id ? (
                      <form
                        action={runProjectStageGoalActionAction.bind(
                          null,
                          id,
                          mvpStatus.stage_goal.goal_id,
                          "publish_prepare_delivery"
                        )}
                      >
                        <button className="button secondary" type="submit">
                          {check.next_action_label ?? "发布交付"}
                        </button>
                      </form>
                    ) : null}
                    {check.next_action_type === "create_placement" && check.next_action_url ? (
                      <Link className="button secondary" href={asRoute(check.next_action_url)}>
                        {check.next_action_label ?? "进入投放运营"}
                      </Link>
                    ) : null}
                    {check.next_action_type &&
                    ![
                      "generate_report",
                      "run_crawl",
                      "retry_crawl_task",
                      "open_task",
                      "run_full_loop",
                      "publish_prepare_delivery",
                      "create_placement"
                    ].includes(
                      check.next_action_type
                    ) &&
                    check.next_action_url ? (
                      <Link className="button secondary" href={asRoute(check.next_action_url)}>
                        {check.next_action_label ?? "查看"}
                      </Link>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
            <div className="list">
              {mvpStatus.stage_goal.action_results.length === 0 ? (
                <p className="subtle">还没有阶段目标动作。可以从下方阶段目标卡片发起采集、生成稿件并推进投放。</p>
              ) : (
                mvpStatus.stage_goal.action_results.map((action) => (
                  <Link
                    className="row"
                    href={asRoute(action.resource_url ?? `/projects/${id}`)}
                    key={`${action.action_type}-${action.resource_id ?? "none"}`}
                  >
                    <div>
                      <div className="meta-line">
                        <span>{actionLabel(action.action_type)}</span>
                        <span>{statusLabel(action.status)}</span>
                        <span>ID {action.resource_id ?? "-"}</span>
                      </div>
                      <h3>{action.message}</h3>
                    </div>
                    <span className="tag">{action.resource_type ?? "resource"}</span>
                  </Link>
                ))
              )}
            </div>
          </div>
        ) : (
          <p className="subtle">暂时无法读取闭环状态 API。下方经营视图仍会展示项目当前数据。</p>
        )}
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>GEO 经营视图</h2>
            <p className="subtle">把搜索采集、成熟度、内容生产、投放复盘和客户交付放在同一张项目经营图里。</p>
          </div>
          <span className="tag">健康度 {geoHealthScore}</span>
        </div>
        <div className="grid cols-4">
          <div className="metric">
            <span>成熟度</span>
            <strong>{latestReport ? latestReport.total_score : "暂无"}</strong>
            <small>{latestReport ? latestReport.maturity_level : "先生成成熟度报告"}</small>
          </div>
          <div className="metric">
            <span>内容生产</span>
            <strong>{approvedDrafts + approvedAssets}</strong>
            <small>已通过稿件 {approvedDrafts}｜资产 {approvedAssets}</small>
          </div>
          <div className="metric">
            <span>投放复盘</span>
            <strong>{reviewedPlacements}/{publishedPlacements.length}</strong>
            <small>正向复盘 {positiveReviews}</small>
          </div>
          <div className="metric">
            <span>客户交付</span>
            <strong>{acceptedDeliveries}/{deliverablePlacements.length}</strong>
            <small>待跟进 {followUpAlerts.length + stageGoalAlerts.length}</small>
          </div>
        </div>
        <div className="list">
          {latestReport ? (
            <div className="row">
              <div>
                <h3>{latestReport.summary ?? latestReport.title}</h3>
                <small>
                  推荐率 {Math.round((metrics?.company_recommendation_rate ?? 0) * 100)}%｜
                  采集样本 {metrics?.total_answers ?? 0}｜
                  交付确认 {acceptedDeliveries}
                </small>
              </div>
              <div className="row-actions">
                <Link className="button secondary" href={asRoute(`/projects/${id}/answers`)}>
                  搜索结果
                </Link>
                <Link className="button secondary" href={`/projects/${id}/reports/${latestReport.id}`}>
                  成熟度报告
                </Link>
                <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
                  交付包
                </Link>
              </div>
            </div>
          ) : (
            <p className="subtle">暂无成熟度报告。完成搜索采集后生成报告，经营视图会自动补齐建议和交付进度。</p>
          )}
          {followUpAlerts.length > 0 ? (
            <div className="row">
              <div>
                <h3>客户确认后待跟进</h3>
                <small>{followUpAlerts[0].message}</small>
              </div>
              <Link className="button secondary" href={`/projects/${id}/delivery-package`}>
                处理跟进
              </Link>
            </div>
          ) : null}
          {stageGoalAlerts.length > 0 ? (
            <div className="row">
              <div>
                <h3>阶段目标需要跟进</h3>
                <small>{stageGoalAlerts[0].message}</small>
              </div>
              <Link className="button secondary" href="/admin/alerts">
                查看告警
              </Link>
            </div>
          ) : null}
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel" id="stage-goals">
          <div className="section-head">
            <div>
              <h2>经营趋势</h2>
              <p className="subtle">最近 {operatingTrends.days} 天的健康度、成熟度、采集样本和内容生产变化。</p>
            </div>
            <span className="tag">
              健康度 {healthDelta >= 0 ? "+" : ""}
              {healthDelta}
            </span>
          </div>
          {operatingTrends.points.length === 0 ? (
            <p className="subtle">暂无趋势数据。完成采集、生成报告或发布投放后会出现曲线。</p>
          ) : (
            <div className="trend-chart" aria-label="项目经营趋势">
              {operatingTrends.points.map((point) => (
                <div className="trend-day" key={point.date}>
                  <div className="trend-bars">
                    <span
                      className="trend-bar health"
                      style={{ height: `${Math.max(8, (point.health_score / maxTrendValue) * 100)}%` }}
                      title={`健康度 ${point.health_score}`}
                    />
                    <span
                      className="trend-bar maturity"
                      style={{ height: `${Math.max(8, (point.maturity_score / maxTrendValue) * 100)}%` }}
                      title={`成熟度 ${point.maturity_score}`}
                    />
                    <span
                      className="trend-bar volume"
                      style={{ height: `${Math.max(8, (point.answer_count / maxTrendValue) * 100)}%` }}
                      title={`样本 ${point.answer_count}`}
                    />
                  </div>
                  <small>{point.date.slice(5)}</small>
                </div>
              ))}
            </div>
          )}
          <div className="meta-line">
            <span>推荐率变化 {recommendationDelta >= 0 ? "+" : ""}{recommendationDelta}%</span>
            <span>最新样本 {latestTrend?.answer_count ?? 0}</span>
            <span>已通过内容 {latestTrend?.approved_content_count ?? approvedDrafts + approvedAssets}</span>
          </div>
        </div>

        <div className="panel">
          <div className="section-head">
            <div>
              <h2>阶段目标</h2>
              <p className="subtle">把 GEO 优化从一次性报告推进为连续运营目标。</p>
            </div>
            <div className="row-actions">
              <span className="tag">目标 {stageGoals.length}</span>
              <form action={runStageGoalReminders}>
                <button className="button secondary" type="submit">
                  检查目标提醒
                </button>
              </form>
            </div>
          </div>
          <form action={createStageGoal} className="form compact-form">
            <div className="grid cols-2">
              <label className="field">
                <span>目标名称</span>
                <input name="title" placeholder="例如：30 天健康度达到 75" required />
              </label>
              <label className="field">
                <span>指标</span>
                <select name="metric_key" defaultValue="health_score">
                  {metricOptions.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="grid cols-3">
              <label className="field">
                <span>基线</span>
                <input name="baseline_value" type="number" step="0.01" defaultValue={0} />
              </label>
              <label className="field">
                <span>目标值</span>
                <input name="target_value" type="number" step="0.01" required />
              </label>
              <label className="field">
                <span>截止时间</span>
                <input name="due_at" type="datetime-local" />
              </label>
            </div>
            <div className="grid cols-2">
              <label className="field">
                <span>负责人</span>
                <input name="owner" placeholder="运营 / 内容 / 客户成功" />
              </label>
              <label className="field">
                <span>备注</span>
                <input name="note" placeholder="阶段策略或复盘说明" />
              </label>
            </div>
            <button className="button" type="submit">
              新增阶段目标
            </button>
          </form>
          <div className="list goal-list">
            {stageGoals.length === 0 ? (
              <p className="subtle">暂无阶段目标。可以先设置健康度、推荐率或内容生产目标。</p>
            ) : (
              stageGoals.map((goal) => {
                const isBrowserObservationGoal = Boolean(goal.note?.includes("report_observation_id="));
                return (
                <div className="row review-row" key={goal.id}>
                  <div className="goal-main">
                    <div className="meta-line">
                      <span>{metricLabel.get(goal.metric_key) ?? goal.metric_key}</span>
                      <span>{goal.status}</span>
                      <span>{goal.risk_level}</span>
                      {goal.active_alert_type ? <span>已提醒</span> : null}
                      {goal.owner ? <span>{goal.owner}</span> : null}
                      {goal.due_at ? <span>截止 {goal.due_at.slice(0, 10)}</span> : null}
                    </div>
                    <h3>{goal.title}</h3>
                    <small>
                      当前 {goal.current_value} / 目标 {goal.target_value}，还差 {goal.remaining_value}
                    </small>
                    <div className="scorebar wide">
                      <span style={{ width: `${Math.round(goal.progress_rate * 100)}%` }} />
                    </div>
                    {goal.review_summary ? <small>{goal.review_summary}</small> : null}
                    {goal.recommendations.length > 0 ? (
                      <div className="mini-list">
                        <small>
                          <strong>复盘建议</strong>
                        </small>
                        {goal.recommendations.slice(0, 3).map((recommendation) => (
                          <small key={recommendation}>- {recommendation}</small>
                        ))}
                      </div>
                    ) : null}
                    {goal.suggested_actions.length > 0 ? (
                      <div className="mini-list">
                        <small>
                          <strong>建议动作</strong>
                        </small>
                        <div className="goal-actions">
                          {goal.suggested_actions.map((action) =>
                            action.action_type === "open_browser_observation" ? (
                              <Link
                                className={action.priority === "primary" ? "button" : "button secondary"}
                                href={asRoute(`/projects/${id}#browser-observation`)}
                                key={`${goal.id}-${action.action_type}`}
                              >
                                {action.label || actionLabel(action.action_type)}
                              </Link>
                            ) : action.action_type === "run_real_provider_smoke" ? (
                              <Link
                                className={action.priority === "primary" ? "button" : "button secondary"}
                                href={asRoute(`/projects/${id}#real-provider-smoke`)}
                                key={`${goal.id}-${action.action_type}`}
                              >
                                {action.label || actionLabel(action.action_type)}
                              </Link>
                            ) : (
                              <form
                                action={runProjectStageGoalActionAction.bind(null, id, goal.id, action.action_type)}
                                key={`${goal.id}-${action.action_type}`}
                              >
                                <button className={action.priority === "primary" ? "button" : "button secondary"} type="submit">
                                  {action.label || actionLabel(action.action_type)}
                                </button>
                              </form>
                            )
                          )}
                        </div>
                        {goal.suggested_actions.slice(0, 2).map((action) => (
                          <small key={`${goal.id}-${action.action_type}-reason`}>- {action.reason}</small>
                        ))}
                      </div>
                    ) : null}
                    <div className="goal-actions">
                      {isBrowserObservationGoal ? (
                        <Link className="button" href={asRoute(`/projects/${id}#browser-observation`)}>
                          录入网页观测
                        </Link>
                      ) : null}
                      <form action={runProjectStageGoalActionAction.bind(null, id, goal.id, "run_crawl")}>
                        <button className="button secondary" type="submit">
                          发起采集
                        </button>
                      </form>
                      <form action={runProjectStageGoalActionAction.bind(null, id, goal.id, "generate_draft")}>
                        <button className="button secondary" type="submit">
                          生成并评分
                        </button>
                      </form>
                      <form action={runProjectStageGoalActionAction.bind(null, id, goal.id, "create_placement")}>
                        <button className="button secondary" type="submit">
                          创建投放
                        </button>
                      </form>
                      <form action={runProjectStageGoalActionAction.bind(null, id, goal.id, "create_delivery_followup")}>
                        <button className="button secondary" type="submit">
                          交付跟进
                        </button>
                      </form>
                      <form action={runProjectStageGoalActionAction.bind(null, id, goal.id, "approve_and_create_placement")}>
                        <button className="button" type="submit">
                          通过并投放
                        </button>
                      </form>
                      <form action={runProjectStageGoalActionAction.bind(null, id, goal.id, "run_full_loop")}>
                        <button className="button" type="submit">
                          一键闭环
                        </button>
                      </form>
                      <form action={runProjectStageGoalActionAction.bind(null, id, goal.id, "publish_prepare_delivery")}>
                        <button className="button" type="submit">
                          发布交付
                        </button>
                      </form>
                    </div>
                    <div className="mini-list timeline-list">
                      <small>
                        <strong>复盘时间线</strong>
                      </small>
                      {(stageGoalTimelineMap.get(goal.id) ?? []).slice(0, 5).map((item) => (
                        <small key={`${item.event_type}-${item.resource_type}-${item.resource_id}-${item.created_at}`}>
                          {item.created_at.slice(0, 16)}｜{item.title}
                          {item.resource_url ? (
                            <>
                              {" ｜ "}
                              <a href={item.resource_url}>查看</a>
                            </>
                          ) : null}
                        </small>
                      ))}
                    </div>
                    {goal.note ? <small>{goal.note}</small> : null}
                  </div>
                  <div className="row-actions">
                    {goal.status !== "completed" ? (
                      <form action={updateProjectStageGoalStatusAction.bind(null, id, goal.id, "completed")}>
                        <button className="button secondary" type="submit">
                          完成
                        </button>
                      </form>
                    ) : null}
                    {goal.status !== "archived" ? (
                      <form action={updateProjectStageGoalStatusAction.bind(null, id, goal.id, "archived")}>
                        <button className="button secondary" type="submit">
                          归档
                        </button>
                      </form>
                    ) : null}
                  </div>
                </div>
                );
              })
            )}
          </div>
        </div>
      </section>

      <section className="grid cols-3" id="project-config">
        <div className="panel metric">
          <span>目标问题</span>
          <strong>{questions.length}</strong>
        </div>
        <div className="panel metric">
          <span>关键词</span>
          <strong>{keywords.length}</strong>
        </div>
        <div className="panel metric">
          <span>竞品</span>
          <strong>{competitors.length}</strong>
        </div>
      </section>

      {configAddedCount > 0 ? (
        <section className="panel">
          <h2>项目配置已更新</h2>
          <p className="subtle">本次已追加 {configAddedCount} 条目标问题、关键词或竞品。</p>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>补齐诊断输入</h2>
            <p className="subtle">按行追加目标问题、关键词和竞品，用于搜索采集与企业 GEO 成熟度研判。</p>
          </div>
          <div className="row-actions">
            <span className="tag">建议 10 问题 / 10 关键词 / 3+ 竞品</span>
            <form action={seedMaturityConfig}>
              <button className="button secondary" type="submit">
                自动补齐缺口
              </button>
            </form>
          </div>
        </div>
        <form action={appendProjectConfig} className="form">
          <div className="grid cols-3">
            <label className="field">
              <span>目标问题</span>
              <textarea name="target_questions" placeholder={"每行一个问题\n例如：企业如何建设数据安全治理体系？"} />
            </label>
            <label className="field">
              <span>关键词</span>
              <textarea name="keywords" placeholder={"每行一个关键词\n例如：数据安全治理"} />
            </label>
            <label className="field">
              <span>竞品</span>
              <textarea name="competitors" placeholder={"每行一个竞品\n例如：某某科技"} />
            </label>
          </div>
          <button className="button" type="submit">
            追加配置
          </button>
        </form>
      </section>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>AI 答案样本</span>
          <strong>{metrics?.total_answers ?? 0}</strong>
        </div>
        <div className="panel metric">
          <span>企业提及率</span>
          <strong>{Math.round((metrics?.company_mention_rate ?? 0) * 100)}%</strong>
        </div>
        <div className="panel metric">
          <span>企业推荐率</span>
          <strong>{Math.round((metrics?.company_recommendation_rate ?? 0) * 100)}%</strong>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>目标问题</h2>
          <div className="list">
            {questions.length === 0 ? (
              <p className="subtle">还没有目标问题。</p>
            ) : (
              questions.map((item) => (
                <div className="row" key={item.id}>
                  <div>
                    <h3>{item.question_text}</h3>
                    <small>{item.question_type}</small>
                  </div>
                  <span className="tag">P{item.priority}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="panel">
          <h2>关键词</h2>
          <div className="list">
            {keywords.length === 0 ? (
              <p className="subtle">还没有关键词。</p>
            ) : (
              keywords.map((item) => (
                <div className="row" key={item.id}>
                  <div>
                    <h3>{item.keyword}</h3>
                    <small>{item.keyword_type}</small>
                  </div>
                  <span className="tag">P{item.priority}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>竞品</h2>
        <div className="list">
          {competitors.length === 0 ? (
            <p className="subtle">还没有竞品。</p>
          ) : (
            competitors.map((item) => (
              <div className="row" key={item.id}>
                <div>
                  <h3>{item.name}</h3>
                  <small>{item.website_url ?? "未设置官网"}</small>
                </div>
                <span className="tag">{item.status}</span>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <h2>采集结果</h2>
        <div className="list">
          {results.length === 0 ? (
            <p className="subtle">还没有采集结果。点击右上角发起搜索采集。</p>
          ) : (
            results.slice(0, 8).map((item) => (
              <div className="row" key={item.id}>
                <div>
                  <Link href={`/projects/${id}/answers/${item.id}`}>
                    <h3>{item.prompt_text}</h3>
                  </Link>
                  <small>{item.answer_summary ?? item.raw_answer.slice(0, 90)}</small>
                </div>
                <span className="tag">{item.status}</span>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <h2>采集任务</h2>
        <div className="list">
          {tasks.length === 0 ? (
            <p className="subtle">还没有采集任务。</p>
          ) : (
            tasks.slice(0, 5).map((task) => (
              <Link className="row" href={`/projects/${id}/tasks/${task.id}`} key={task.id}>
                <div>
                  <h3>任务 #{task.id}</h3>
                  <small>
                    {task.task_type}｜{task.started_at ?? "未开始"}
                    {task.provider_ids.length > 0
                      ? `｜渠道 ${task.provider_ids.map((providerId) => providerNameById.get(providerId) ?? `#${providerId}`).join("、")}`
                      : ""}
                    {task.target_question_ids.length > 0
                      ? `｜问题 ${task.target_question_ids
                          .map((questionId) => questionTextById.get(questionId) ?? `#${questionId}`)
                          .join("、")}`
                      : ""}
                    {task.keyword_ids.length > 0
                      ? `｜关键词 ${task.keyword_ids.map((keywordId) => keywordTextById.get(keywordId) ?? `#${keywordId}`).join("、")}`
                      : ""}
                  </small>
                  {task.error_message ? (
                    <small>
                      {isProviderPreflightError(task.error_message)
                        ? "模型渠道未通过预检，先完成配置或测试调用。"
                        : task.error_message.slice(0, 120)}
                    </small>
                  ) : null}
                </div>
                <span className="tag">{task.status}</span>
              </Link>
            ))
          )}
        </div>
      </section>

      <section className="panel" id="browser-observation">
        <div className="section-head">
          <div>
            <h2>网页端观测入库</h2>
            <p className="subtle">用于豆包、DeepSeek、Kimi、千问等网页端低频抽样，把人工观察到的答案和截图证据纳入项目样本。</p>
          </div>
          <span className="tag">人工留证</span>
        </div>
        {observationCreated ? (
          <div className="notice success">
            已入库网页端观测样本
            {observationResultId > 0 ? ` #${observationResultId}` : ""}
            {Number.isFinite(observationSourceCount) ? `，识别信源 ${observationSourceCount} 条` : ""}
            {Number.isFinite(observationScreenshotCount) ? `，截图证据 ${observationScreenshotCount} 条` : ""}。
            {observationResultId > 0 ? (
              <Link className="inline-link" href={asRoute(`/projects/${id}/answers/${observationResultId}`)}>
                查看答案证据
              </Link>
            ) : null}
          </div>
        ) : null}
        {observationBulkCreated > 0 ? (
          <div className="notice success">
            已批量入库网页端观测样本 {observationBulkCreated} 条，识别信源 {observationBulkSourceCount} 条，截图证据{" "}
            {observationBulkScreenshotCount} 条。
          </div>
        ) : null}
        {observationValidatedCount > 0 ? (
          <div className="notice success">
            已完成观测 JSON 校验：{observationValidatedCount} 条记录，覆盖 {observationValidatedPlatformCount} 个平台。未写入数据库，可取消“只校验不入库”后正式入库。
          </div>
        ) : null}
        {packPreparedCount > 0 ? (
          <div className="notice success">
            已刷新春秋元泉四平台采集包：{packPreparedCount} 条任务
            {queryParams.pack_dir ? `，目录 ${queryParams.pack_dir}` : ""}。
          </div>
        ) : null}
        {nextPackPreparedCount > 0 ? (
          <div className="notice success">
            本批观测已入库，系统已自动准备下一批网页端采集包：{nextPackPreparedCount} 条任务。
          </div>
        ) : null}
        <div className="grid cols-4">
          <div className="metric">
            <span>观测样本</span>
            <strong>{browserObservations.length}</strong>
            <small>最近 {Math.min(browserObservations.length, 5)} 条</small>
          </div>
          <div className="metric">
            <span>问题观测</span>
            <strong>{fullyObservedQuestionIds.size}/{questions.length}</strong>
            <small>待四平台补齐 {browserObservationQuestionGaps.length}</small>
          </div>
          <div className="metric">
            <span>关键词观测</span>
            <strong>{fullyObservedKeywordIds.size}/{keywords.length}</strong>
            <small>待四平台补齐 {browserObservationKeywordGaps.length}</small>
          </div>
          <div className="metric">
            <span>截图证据</span>
            <strong>{browserObservations.reduce((sum, item) => sum + item.screenshot_evidence_count, 0)}</strong>
            <small>目标至少 4 条</small>
          </div>
          <div className="metric">
            <span>平台覆盖</span>
            <strong>{browserPlatformCoverageText}</strong>
            <small>目标覆盖 4 个平台</small>
          </div>
        </div>
        <div className="mini-list">
          <small>
            下一条建议观测：
            {selectedObservationQuestion
              ? selectedObservationQuestion.question_text
              : selectedObservationKeyword
                ? `${selectedObservationKeyword.keyword} 相关服务商怎么选？`
                : "暂无目标问题或关键词"}
          </small>
          <small>页面信源累计 {browserObservations.reduce((sum, item) => sum + item.source_count, 0)} 条。</small>
        </div>
        {browserObservationEntryLinks.length > 0 ? (
          <div className="grid cols-4">
            {browserObservationEntryLinks.map((provider) => (
              <div className="metric" key={provider.id}>
                <span>{provider.platform_name}</span>
                <strong>网页观测</strong>
                {provider.api_base_url ? (
                  <a href={provider.api_base_url} rel="noreferrer" target="_blank">
                    打开网页端
                  </a>
                ) : (
                  <small>未配置网页入口</small>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="notice warning">
            尚未配置网页观测渠道。可运行 <code>pnpm run ensure:browser-observation-providers</code> 初始化豆包、DeepSeek、Kimi、千问入口。
          </div>
        )}
        {browserObservationPackStatus ? (
          <div className="subsection">
            <div className="section-head">
              <div>
                <h3>采集包状态</h3>
                <p className="subtle">
                  来源：<code>{browserObservationPackStatus.input}</code>。证据目录：
                  <code>{browserObservationPackStatus.evidence_dir}</code>。
                </p>
              </div>
              <span className={browserObservationPackStatus.ready ? "tag active" : "tag"}>
                {browserObservationPackStatus.ready ? "可导入" : "待补齐"}
              </span>
            </div>
            <div className="grid cols-4">
              <div className="metric">
                <span>采集任务</span>
                <strong>{browserObservationPackStatus.observation_count}</strong>
                <small>覆盖 {browserObservationPackStatus.covered_platforms.join("、") || "暂无"}</small>
              </div>
              <div className="metric">
                <span>已就绪平台</span>
                <strong>{browserObservationPackStatus.ready_platforms.length}/4</strong>
                <small>{browserObservationPackStatus.ready_platforms.join("、") || "暂无"}</small>
              </div>
              <div className="metric">
                <span>阻塞项</span>
                <strong>{browserObservationPackStatus.blocking_issue_count}</strong>
                <small>{browserObservationPackStatus.next_action}</small>
              </div>
              <div className="metric">
                <span>提醒项</span>
                <strong>{browserObservationPackStatus.warning_count}</strong>
                <small>信源可为空，但答案和截图必须补齐</small>
              </div>
            </div>
            <div className="list compact-list">
              {browserObservationPackStatus.items.map((item) => (
                <div className="row review-row" key={`${item.platform_name}-${item.prompt_text}`}>
                  <div>
                    <div className="meta-line">
                      <span>{item.platform_name}</span>
                      <span>{item.answer_ready ? "答案已填" : "缺答案"}</span>
                      <span>{item.evidence.ready ? "证据已填" : "缺截图"}</span>
                      <span>答案 {item.raw_answer_length} 字</span>
                    </div>
                    <h3>{item.prompt_text}</h3>
                    <small>
                      证据文件：{item.evidence.evidence_filename || "未填写"}｜
                      {item.evidence.file_exists ? "文件已存在" : "文件未找到"}｜信源 {item.source_count} 条
                    </small>
                    {item.issues.length > 0 ? <small>待处理：{item.issues.join("；")}</small> : null}
                  </div>
                  <div className="row-actions">
                    <Link
                      className="button secondary"
                      href={asRoute(
                        `/projects/${id}?observe_platform=${encodeURIComponent(item.platform_name)}${
                          item.target_question_id ? `&observe_question_id=${item.target_question_id}` : ""
                        }${item.keyword_id ? `&observe_keyword_id=${item.keyword_id}` : ""}&observe_prompt=${encodeURIComponent(
                          item.prompt_text
                        )}#browser-observation`
                      )}
                    >
                      填入表单
                    </Link>
                    {item.observation_url ? (
                      <a className="button secondary" href={item.observation_url} rel="noreferrer" target="_blank">
                        打开网页
                      </a>
                    ) : null}
                    <span className={item.ready ? "tag active" : "tag"}>{item.ready ? "OK" : "TODO"}</span>
                  </div>
                </div>
              ))}
            </div>
            <div className="row-actions">
              <form action={prepareObservationPack}>
                <SubmitButton className="button secondary" pendingText="刷新中...">
                  刷新采集包
                </SubmitButton>
              </form>
              <form action={validateObservationPack}>
                <SubmitButton className="button secondary" pendingText="校验中...">
                  校验采集包
                </SubmitButton>
              </form>
              {browserObservationPackStatus.ready ? (
                <form action={importObservationPack}>
                  <SubmitButton pendingText="导入并生成中...">
                    导入并生成报告稿件
                  </SubmitButton>
                </form>
              ) : (
                <button className="button secondary" disabled type="button">
                  补齐后可导入生成
                </button>
              )}
              <code>pnpm run inspect:yuanquan-pack</code>
              <code>outputs/yuanquan_browser_observation_pack_q1/README.md</code>
            </div>
          </div>
        ) : null}
        <div className="subsection">
          <div className="section-head">
            <div>
              <h3>真实采集执行清单</h3>
              <p className="subtle">按清单逐条打开网页端提问。正式项目当前建议先完成同一目标问题的四个平台截图留证，再生成报告和稿件。</p>
            </div>
            <span className="tag">{browserObservationTasks.filter((task) => !task.observed).length} 条待采集</span>
          </div>
          <label className="field">
            <span>可复制清单</span>
            <textarea
              readOnly
              rows={10}
              value={
                browserObservationChecklist ||
                "前 10 个目标问题在豆包、DeepSeek、Kimi、千问四个平台上都已有网页观测样本。"
              }
            />
          </label>
        </div>
        <div className="section-head">
          <div>
            <h3>下一批网页观测任务</h3>
            <p className="subtle">优先覆盖 4 个网页端平台和前 10 个目标问题。点击任务会把平台、问题和提问带入下方录入表单。</p>
          </div>
          <span className="tag">{nextBrowserObservationTasks.length} 条待做</span>
        </div>
        <div className="grid cols-4">
          {nextBrowserObservationTasks.length === 0 ? (
            <p className="subtle">前 10 个目标问题在四个平台上都已有网页观测样本。</p>
          ) : (
            nextBrowserObservationTasks.map((task) => (
              <div className="metric" key={`${task.platform_name}-${task.question.id}`}>
                <span>{task.platform_name}</span>
                <strong>待观测</strong>
                <small>{task.question.question_text}</small>
                <div className="row-actions">
                  <Link
                    className="button secondary"
                    href={asRoute(
                      `/projects/${id}?observe_platform=${encodeURIComponent(task.platform_name)}&observe_question_id=${task.question.id}&observe_prompt=${encodeURIComponent(task.question.question_text)}#browser-observation`
                    )}
                  >
                    填入表单
                  </Link>
                  <a className="button secondary" href={task.api_base_url} rel="noreferrer" target="_blank">
                    打开网页
                  </a>
                </div>
              </div>
            ))
          )}
        </div>
        <div className="list">
          {browserObservations.length === 0 ? (
            <p className="subtle">还没有网页端观测样本。可以先打开目标大模型网页端搜索，把答案和截图证据录入。</p>
          ) : (
            browserObservations.map((item) => (
              <Link className="row" href={`/projects/${id}/answers/${item.id}`} key={item.id}>
                <div>
                  <h3>{item.prompt_text}</h3>
                  <small>
                    {item.collected_at ?? "未记录时间"}｜观察员 {item.observer_name || "未填写"}｜
                    平台 {item.platform_name || "未填写"}｜
                    信源 {item.source_count}｜截图 {item.screenshot_evidence_count}
                  </small>
                  {item.note ? <small>{item.note}</small> : null}
                </div>
                <span className="tag">{item.screenshot_url ? "有截图" : "待截图"}</span>
              </Link>
            ))
          )}
        </div>
        <div className="subsection">
          <div className="section-head">
            <div>
              <h3>批量录入四平台观测</h3>
              <p className="subtle">适合一次粘贴豆包、DeepSeek、Kimi、千问四条网页端答案。字段名保持不变，替换答案、截图和信源即可。</p>
            </div>
            <div className="row-actions">
              <a
                className="button secondary"
                download={`project-${id}-browser-observation-template.json`}
                href={browserObservationDownloadHref}
              >
                下载采集模板
              </a>
              <a
                className="button secondary"
                download={`project-${id}-browser-observation-work-order.md`}
                href={browserObservationWorkOrderHref}
              >
                下载采集工单
              </a>
              <span className="tag">JSON 数组</span>
            </div>
          </div>
          <form action={bulkCreateBrowserObservations} className="form">
            <label className="field">
              <span>上传已填写模板</span>
              <input accept="application/json,.json" name="observations_file" type="file" />
            </label>
            <label className="field">
              <span>或粘贴观测 JSON</span>
              <textarea
                name="observations_json"
                defaultValue={browserObservationBulkExample}
                rows={16}
              />
            </label>
            <label className="checkline">
              <input name="dry_run" type="checkbox" defaultChecked />
              <span>只校验不入库</span>
            </label>
            <label className="checkline">
              <input name="generate_report" type="checkbox" defaultChecked />
              <span>入库后立即生成成熟度报告</span>
            </label>
            <label className="checkline">
              <input name="generate_draft" type="checkbox" defaultChecked />
              <span>生成报告后继续生成首篇稿件并评分</span>
            </label>
            <SubmitButton pendingText="校验或入库中...">
              校验/批量入库观测样本
            </SubmitButton>
          </form>
        </div>
        <form action={createBrowserObservation} className="form">
          <input type="hidden" name="report_id" value={observeReportId > 0 ? observeReportId : ""} />
          <div className="grid cols-3">
            <label className="field">
              <span>观测渠道</span>
              <select name="provider_id" defaultValue={selectedObservationProvider ? String(selectedObservationProvider.id) : ""}>
                <option value="">浏览器观测渠道</option>
                {browserObservationProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>观测平台</span>
              <select name="platform_name" defaultValue={observePlatform}>
                {BROWSER_OBSERVATION_PLATFORMS.map((platform) => (
                  <option key={platform} value={platform}>
                    {platform}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>目标问题</span>
              <select name="target_question_id" defaultValue={selectedObservationQuestion ? String(selectedObservationQuestion.id) : ""}>
                <option value="">不关联问题</option>
                {questions.map((question) => (
                  <option key={question.id} value={question.id}>
                    {question.question_text}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>关键词</span>
              <select name="keyword_id" defaultValue={selectedObservationKeyword ? String(selectedObservationKeyword.id) : ""}>
                <option value="">不关联关键词</option>
                {keywords.map((keyword) => (
                  <option key={keyword.id} value={keyword.id}>
                    {keyword.keyword}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid cols-2">
            <label className="field">
              <span>实际提问</span>
              <input name="prompt_text" defaultValue={nextObservationPrompt} required />
            </label>
            <label className="field">
              <span>观察员</span>
              <input name="observer_name" placeholder="例如：运营同事 / 客户成功" />
            </label>
          </div>
          <label className="field">
            <span>网页端原始答案</span>
            <textarea name="raw_answer" placeholder="粘贴网页端大模型返回的完整答案。" required />
          </label>
          <div className="grid cols-2">
            <label className="field">
              <span>答案摘要</span>
              <input name="answer_summary" placeholder="可选，留空则自动截取答案前 160 字" />
            </label>
            <label className="field">
              <span>网页入口</span>
              <input name="observation_url" placeholder="例如：https://www.doubao.com" />
            </label>
          </div>
          <div className="grid cols-2">
            <label className="field">
              <span>上传截图/录屏文件</span>
              <input accept="image/*,application/pdf,video/mp4,video/quicktime" name="screenshot_file" type="file" />
            </label>
            <label className="field">
              <span>备注</span>
              <input name="note" placeholder="例如：网页端联网搜索，含来源卡片" />
            </label>
          </div>
          <label className="field">
            <span>截图或录屏地址</span>
            <input name="screenshot_url" placeholder="可选；上传文件会自动生成 file:// 存证路径，也可填写对象存储地址或共享链接" />
          </label>
          <label className="field">
            <span>页面可见信源 URL</span>
            <textarea name="source_urls" placeholder={"每行一个网页端可见来源\n例如：https://example.com/article"} />
          </label>
          <label className="checkline">
            <input name="auto_generate_on_completion" type="checkbox" defaultChecked />
            <span>同一问题/关键词四个平台齐备后，自动生成成熟度报告、稿件和 AI 评分</span>
          </label>
          <SubmitButton pendingText="观测入库中...">
            入库为观测样本
          </SubmitButton>
        </form>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <div className="section-head">
            <div>
              <h2>采集计划</h2>
              <p className="subtle">用于每小时或按周期监测不同模型下的目标问题和关键词。</p>
            </div>
            <form action={runDueSchedules}>
              <SubmitButton className="button secondary" pendingText="推进中...">推进到期监测</SubmitButton>
            </form>
          </div>
          {readyRan !== null ? (
            <div className={readyFailed > 0 ? "notice danger" : readyPending > 0 ? "notice warning" : "notice success"}>
              已创建 {queryParams.ready_created ?? 0} 个到期采集任务，执行 {queryParams.ready_ran ?? 0} 个队列任务，成功{" "}
              {queryParams.ready_success ?? 0} 个，失败 {queryParams.ready_failed ?? 0} 个
              {readyPending > 0 ? `，仍有 ${readyPending} 个待执行任务` : "。"}
            </div>
          ) : null}
          <div className="list">
            {schedules.length === 0 ? (
              <p className="subtle">还没有定时计划。建议按周创建稳定、可复核的模型评测计划。</p>
            ) : (
              schedules.map((schedule) => {
                const runSchedule = runCrawlScheduleAction.bind(null, id, schedule.id);
                return (
                  <div className="row" key={schedule.id}>
                    <div>
                      <h3>{schedule.name}</h3>
                      <small>
                        {schedule.schedule_type === "weekly" ? "每周" : `${schedule.schedule_type}｜每 ${schedule.interval_hours} 小时`}｜每题采样 {schedule.sample_runs_per_prompt} 次｜下次{" "}
                        {schedule.next_run_at ?? "未设置"}
                        {schedule.provider_ids.length > 0
                          ? `｜渠道 ${schedule.provider_ids
                              .map((providerId) => providerNameById.get(providerId) ?? `#${providerId}`)
                              .join("、")}`
                          : ""}
                        {schedule.target_question_ids.length > 0
                          ? `｜问题 ${schedule.target_question_ids
                              .map((questionId) => questionTextById.get(questionId) ?? `#${questionId}`)
                              .join("、")}`
                          : ""}
                        {schedule.keyword_ids.length > 0
                          ? `｜关键词 ${schedule.keyword_ids
                              .map((keywordId) => keywordTextById.get(keywordId) ?? `#${keywordId}`)
                              .join("、")}`
                          : ""}
                      </small>
                    </div>
                    <form action={runSchedule}>
                      <button className="button secondary" type="submit">
                        立即运行
                      </button>
                    </form>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="panel">
          <h2>新增计划</h2>
          <form action={createSchedule} className="form">
            <div className="field">
              <label>计划名称</label>
              <input name="name" defaultValue="每周 GEO 100 次搜索评测" />
            </div>
            <div className="grid cols-2">
              <div className="field">
                <label>频率</label>
                <select name="schedule_type" defaultValue="weekly">
                  <option value="hourly">每小时</option>
                  <option value="daily">每天</option>
                  <option value="weekly">每周</option>
                </select>
              </div>
              <div className="field">
                <label>间隔小时</label>
                <input name="interval_hours" type="number" min="1" max="720" defaultValue="168" />
              </div>
            </div>
            <div className="field">
              <label>每个问题独立采样次数</label>
              <input name="sample_runs_per_prompt" type="number" min="1" max="20" defaultValue="4" />
              <small>总调用数 = 问题提示数 × 渠道数 × 采样次数；提交前请先核对费用预估。</small>
            </div>
            {crawlProviderOptions.length > 0 ? (
              <div className="field">
                <label>采集渠道</label>
                <select name="provider_ids" multiple size={Math.min(5, Math.max(2, crawlProviderOptions.length))}>
                  {crawlProviderOptions.map((provider) => (
                    <option disabled={!provider.collection_ready} key={provider.id} value={provider.id}>
                      {provider.name}｜{provider.provider_type}
                      {provider.provider_type !== "mock"
                        ? provider.collection_ready
                          ? "｜真实可采集"
                          : "｜需先测试"
                        : "｜Mock"}
                    </option>
                  ))}
                </select>
                <small>这里只能选择已通过预检的渠道；未测试或失败的真实渠道需先到模型渠道页修复。</small>
              </div>
            ) : null}
            {questions.length > 0 ? (
              <div className="field">
                <label>目标问题范围</label>
                <select name="target_question_ids" multiple size={Math.min(5, Math.max(2, questions.length))}>
                  {questions.map((question) => (
                    <option key={question.id} value={question.id}>
                      {question.question_text}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            {keywords.length > 0 ? (
              <div className="field">
                <label>关键词范围</label>
                <select name="keyword_ids" multiple size={Math.min(5, Math.max(2, keywords.length))}>
                  {keywords.map((keyword) => (
                    <option key={keyword.id} value={keyword.id}>
                      {keyword.keyword}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <label className="checkline">
              <input name="execute_now" type="checkbox" />
              创建后立即跑一次
            </label>
            <button className="button" type="submit">
              创建采集计划
            </button>
          </form>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <div className="section-head">
            <div>
              <h2>成熟度报告</h2>
              <p className="subtle">{reportSampleSuggestion[reportSampleStatus]}</p>
            </div>
            <span className={reportSampleStatus === "ready" ? "tag active" : "tag"}>{reportSampleLabel[reportSampleStatus]}</span>
          </div>
          <div className="grid cols-4">
            <div className="metric">
              <span>答案样本</span>
              <strong>{results.length}</strong>
              <small>{results.length >= 10 ? "达到内部判断线" : "建议至少 10 条"}</small>
            </div>
            <div className="metric">
              <span>问题覆盖</span>
              <strong>
                {coveredQuestionIds.size}/{questions.length}
              </strong>
              <small>{Math.round(questionCoverageRate * 100)}%</small>
            </div>
            <div className="metric">
              <span>关键词覆盖</span>
              <strong>
                {coveredKeywordIds.size}/{keywords.length}
              </strong>
              <small>{Math.round(keywordCoverageRate * 100)}%</small>
            </div>
            <div className="metric">
              <span>模型覆盖</span>
              <strong>{coveredProviderIds.size}</strong>
              <small>{coveredProviderIds.size >= 3 ? "交叉验证较好" : "建议 3+ 渠道"}</small>
            </div>
          </div>
          {latestReport ? (
            <div className="list">
              <div className="row">
                <div>
                  <h3>{latestReport.title}</h3>
                  <small>{latestReport.summary}</small>
                </div>
                <Link className="tag" href={`/projects/${id}/reports/${latestReport.id}`}>
                  {latestReport.maturity_level}
                </Link>
              </div>
              <div className="grid cols-2">
                <div className="metric">
                  <span>总分</span>
                  <strong>{latestReport.total_score}</strong>
                </div>
                <div className="metric">
                  <span>建议数</span>
                  <strong>{latestReport.report_json.recommendations?.length ?? 0}</strong>
                </div>
              </div>
              <Link className="button secondary" href={asRoute(`/projects/${id}/reports`)}>
                查看全部报告
              </Link>
              <Link className="button secondary" href={`/projects/${id}/reports/compare`}>
                查看报告对比
              </Link>
              <form action={generateReport}>
                <button className="button secondary" type="submit">
                  重新生成报告
                </button>
              </form>
            </div>
          ) : (
            <form action={generateReport}>
              <button className="button" type="submit">
                生成成熟度报告
              </button>
            </form>
          )}
        </div>

        <div className="panel" id="drafts">
          <h2>AI 撰稿</h2>
          <div className="row-actions">
            <Link className="button secondary" href={asRoute(`/projects/${id}/drafts`)}>
              进入稿件工作台
            </Link>
          </div>
          {queryParams.action_error ? (
            <div className="notice danger">
              稿件没有创建成功：{queryParams.action_error}
            </div>
          ) : null}
          <form action={generateDraftAndReview} className="form">
            {reportDraftTopics.length > 0 ? (
              <div className="field">
                <label>报告建议选题</label>
                <select name="suggested_topic" defaultValue={reportDraftTopics[0]}>
                  {reportDraftTopics.slice(0, 10).map((topic) => (
                    <option key={topic} value={topic}>
                      {topic}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="field">
              <label>自定义选题</label>
              <input
                name="topic"
                placeholder={reportDraftTopics[0] ?? "网络安全培训公司哪家好？"}
              />
            </div>
            <SubmitButton pendingText="生成并评分中...">
              基于报告生成并评分
            </SubmitButton>
          </form>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>稿件审核</h2>
            <p className="subtle">最近 6 篇稿件，完整列表和来源承接请进入稿件工作台。</p>
          </div>
          <Link className="button secondary" href={asRoute(`/projects/${id}/drafts`)}>
            全部稿件
          </Link>
        </div>
        <div className="list">
          {drafts.length === 0 ? (
            <p className="subtle">还没有稿件。先从上方生成一篇优化稿。</p>
          ) : (
            drafts.slice(0, 6).map((draft) => {
              const latestReview = reviewMap.get(draft.id)?.[0];
              const reviewDraft = reviewDraftAction.bind(null, id, draft.id);
              return (
                <div className="row" key={draft.id}>
                  <div>
                    <Link className="title-link" href={`/projects/${id}/drafts/${draft.id}`}>
                      <h3>{draft.title}</h3>
                    </Link>
                    <small>
                      {draft.summary}
                      {latestReview ? `｜审核 ${latestReview.total_score} 分 ${latestReview.grade}` : ""}
                    </small>
                  </div>
                  <form action={reviewDraft}>
                    <div className="row-actions">
                      <Link className="button secondary" href={asRoute(`/projects/${id}/drafts/${draft.id}`)}>
                        查看稿件
                      </Link>
                      <SubmitButton className="button secondary" pendingText="评分中...">
                        审核打分
                      </SubmitButton>
                    </div>
                  </form>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
