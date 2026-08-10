"use server";

import { randomUUID } from "node:crypto";
import { copyFile, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { revalidatePath } from "next/cache";
import type { Route } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  bulkCreateKeywords,
  bulkCreateBrowserObservations,
  bulkCreateTargetQuestions,
  createArticleReview,
  createAlertReportActionGoals,
  createCompany,
  createContentAsset,
  createContentAssetReview,
  createContentAssetRemediationGoals,
  createCompetitor,
  createCrawlSchedule,
  createBrowserObservation,
  createDeliveryShare,
  createLLMProvider,
  createMaturityReportActionGoals,
  createPlacement,
  createPlacementImpactActionGoals,
  createProject,
  createReviewRule,
  createReportTemplate,
  createProjectStageGoal,
  createUser,
  deactivateUser,
  decideArticleDraftReview,
  decideContentAssetReview,
  confirmPublicDeliveryReport,
  generateArticleDraft,
  generateMaturityReport,
  getMaturityReport,
  getArticleDraft,
  getArticleReviews,
  getContentAssetReviews,
  getContentAssets,
  getPlacementImpact,
  getProject,
  getKeywords,
  getLLMProviders,
  getLLMProviderTestJob,
  getBrowserObservations,
  getReviewQueue,
  getTargetQuestions,
  loginUser,
  queueLLMProviderTest,
  registerUser,
  retryCrawlTask,
  reviseArticleDraft,
  runDiagnostic,
  revokeDeliveryShare,
  runProjectStageGoalAction,
  runProjectStageGoalReminders,
  runDueCrawlSchedules,
  runMonitoringAlerts,
  runNextQueueJob,
  runReadyQueueJobs,
  runPlacementReminders,
  runCrawlSchedule,
  runCrawlTask,
  testLLMProvider,
  updateCrawlResultAnalysis,
  updateLLMProvider,
  updatePlacement,
  updateProjectStageGoal,
  updateAlert
} from "@/lib/api";
import { SESSION_COOKIE } from "@/lib/session";
import { sessionCookieOptions } from "@/lib/session-security";
import { PROVIDER_CATALOG, isOfficialProvider, providerMatchesCatalog, type ProviderCatalogKey } from "@/lib/provider-catalog";

function lines(value: FormDataEntryValue | null): string[] {
  return String(value ?? "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function numberList(values: FormDataEntryValue[]): number[] {
  return values
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);
}

function checkboxValue(formData: FormData, key: string) {
  return formData.get(key) === "on";
}

function asRoute(value: string) {
  return value as Route;
}

function actionErrorTarget(path: string, error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  const normalized =
    message.includes("fetch failed") || message.includes("ECONNREFUSED")
      ? "后端服务暂时不可用，请确认 API 服务已启动后重试。"
      : message.replace(/^API request failed:\s*/i, "");
  const [basePath, hash] = path.split("#", 2);
  const separator = basePath.includes("?") ? "&" : "?";
  return asRoute(
    `${basePath}${separator}action_error=${encodeURIComponent(normalized.slice(0, 240))}${hash ? `#${hash}` : ""}`
  );
}

function dueInDays(days: number) {
  return new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
}

function missingTemplates(existing: string[], templates: string[], targetCount = 10) {
  const seen = new Set(existing.map((item) => item.trim()).filter(Boolean));
  const needed = Math.max(0, targetCount - seen.size);
  const additions: string[] = [];
  for (const item of templates) {
    const normalized = item.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    additions.push(normalized);
    if (additions.length >= needed) break;
  }
  return additions;
}

function parseJsonObject(text: string, fallback: Record<string, unknown> = {}) {
  const trimmed = text.trim();
  if (!trimmed) return fallback;
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : fallback;
  } catch {
    return { note: trimmed };
  }
}

function parseJsonArray(text: string, fallback: Array<Record<string, unknown>> = []) {
  const trimmed = text.trim();
  if (!trimmed) return fallback;
  try {
    const parsed = JSON.parse(trimmed);
    return Array.isArray(parsed) ? (parsed as Array<Record<string, unknown>>) : fallback;
  } catch {
    return [{ note: trimmed }];
  }
}

const OBSERVATION_PLACEHOLDER_PATTERNS = [
  "粘贴该平台网页端返回的完整答案",
  "粘贴网页端大模型返回的完整答案",
  "可选：一句话摘要",
  "https://example.com",
  "example.com",
  "/path/to/screenshot",
  "待填",
  "TODO"
];
const REQUIRED_BROWSER_OBSERVATION_PLATFORMS = ["豆包", "DeepSeek", "Kimi", "千问"];
const MAX_EVIDENCE_UPLOAD_BYTES = 25 * 1024 * 1024;
const ALLOWED_EVIDENCE_UPLOAD_TYPES = new Set([
  "application/pdf",
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/webp",
  "video/mp4",
  "video/quicktime"
]);
const PACK_EVIDENCE_FILENAME_KEYS = ["evidence_filename", "screenshot_filename", "evidence_file", "screenshot_file"];

function safeFilename(value: string) {
  const fallback = "evidence";
  const cleaned = value
    .normalize("NFKC")
    .replace(/[^\w.\-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return cleaned || fallback;
}

function workspaceRoot() {
  return process.env.GEO_WORKSPACE_ROOT ?? join(process.cwd(), "..", "..");
}

function uploadFileLike(value: FormDataEntryValue | null) {
  if (!value || typeof value !== "object") return null;
  if (!("size" in value) || !("arrayBuffer" in value) || typeof value.arrayBuffer !== "function") return null;
  const size = Number(value.size);
  if (!Number.isFinite(size) || size <= 0) return null;
  return value as FormDataEntryValue & {
    arrayBuffer: () => Promise<ArrayBuffer>;
    name?: string;
    size: number;
    type?: string;
  };
}

async function saveEvidenceUpload(projectId: string, value: FormDataEntryValue | null) {
  const file = uploadFileLike(value);
  if (!file) return undefined;
  if (file.size > MAX_EVIDENCE_UPLOAD_BYTES) {
    throw new Error("截图/录屏文件不能超过 25MB。");
  }
  const mimeType = String(file.type ?? "").trim();
  if (mimeType && !ALLOWED_EVIDENCE_UPLOAD_TYPES.has(mimeType)) {
    throw new Error("截图/录屏文件仅支持 PNG、JPG、WEBP、GIF、PDF、MP4 或 MOV。");
  }
  const originalName = safeFilename(String(file.name ?? "evidence"));
  const extension = extname(originalName) || (mimeType === "image/png" ? ".png" : "");
  const basename = safeFilename(originalName.replace(/\.[^.]+$/, ""));
  const evidenceDir = join(workspaceRoot(), "outputs", "browser-observation-evidence", `project-${projectId}`);
  await mkdir(evidenceDir, { recursive: true });
  const filename = `${new Date().toISOString().replace(/[:.]/g, "-")}-${randomUUID().slice(0, 8)}-${basename}${extension}`;
  const filePath = join(evidenceDir, filename);
  await writeFile(filePath, Buffer.from(await file.arrayBuffer()));
  return `file://${filePath}`;
}

async function readYuanquanObservationPackJson() {
  const candidates = [
    join(workspaceRoot(), "outputs", "yuanquan_browser_observation_pack_q1", "observations.json"),
    join(process.cwd(), "outputs", "yuanquan_browser_observation_pack_q1", "observations.json"),
    join(process.cwd(), "..", "..", "outputs", "yuanquan_browser_observation_pack_q1", "observations.json")
  ];
  for (const candidate of candidates) {
    try {
      return await readFile(candidate, "utf-8");
    } catch {
      continue;
    }
  }
  throw new Error("未找到春秋元泉网页端观测采集包 observations.json。请先运行 pnpm run prepare:yuanquan-pack。");
}

async function localFileExists(filePath: string) {
  try {
    const fileStat = await stat(filePath);
    return fileStat.isFile();
  } catch {
    return false;
  }
}

function evidenceFileCandidates(filename: string) {
  if (!filename || filename.startsWith("file://") || filename.startsWith("http://") || filename.startsWith("https://")) {
    return [];
  }
  if (filename.startsWith("/")) return [filename];
  return [
    join(workspaceRoot(), "outputs", "yuanquan_browser_observation_pack_q1", "raw-evidence", filename),
    join(process.cwd(), "outputs", "yuanquan_browser_observation_pack_q1", "raw-evidence", filename),
    join(process.cwd(), "..", "..", "outputs", "yuanquan_browser_observation_pack_q1", "raw-evidence", filename)
  ];
}

async function archiveEvidenceFile(projectId: string, sourcePath: string, platformName: string) {
  const evidenceDir = join(workspaceRoot(), "outputs", "browser-observation-evidence", `project-${projectId}`);
  await mkdir(evidenceDir, { recursive: true });
  const originalName = safeFilename(sourcePath.split("/").pop() ?? "evidence");
  const extension = extname(originalName);
  const basename = safeFilename(originalName.replace(/\.[^.]+$/, ""));
  const filename = `${new Date().toISOString().replace(/[:.]/g, "-")}-${randomUUID().slice(0, 8)}-${safeFilename(
    platformName
  )}-${basename}${extension}`;
  const targetPath = join(evidenceDir, filename);
  await copyFile(sourcePath, targetPath);
  return `file://${targetPath}`;
}

function hasPlaceholderText(value: string) {
  return OBSERVATION_PLACEHOLDER_PATTERNS.some((pattern) => value.includes(pattern));
}

async function resolvePackEvidenceUrl(projectId: string, record: Record<string, unknown>, archive: boolean) {
  const screenshotUrl = stringFromRecord(record, "screenshot_url");
  if (screenshotUrl && !hasPlaceholderText(screenshotUrl)) return screenshotUrl;
  const evidenceFilename = PACK_EVIDENCE_FILENAME_KEYS.map((key) => stringFromRecord(record, key)).find(Boolean);
  if (!evidenceFilename) return "";
  for (const candidate of evidenceFileCandidates(evidenceFilename)) {
    if (await localFileExists(candidate)) {
      return archive
        ? archiveEvidenceFile(projectId, candidate, stringFromRecord(record, "platform_name") || "platform")
        : `file://${candidate}`;
    }
  }
  return "";
}

function hasObservationPlaceholder(record: Record<string, unknown>) {
  const text = JSON.stringify(record);
  return OBSERVATION_PLACEHOLDER_PATTERNS.some((pattern) => text.includes(pattern));
}

function observationValidationRecord(record: Record<string, unknown>, screenshotUrl: string) {
  const sanitized: Record<string, unknown> = { ...record, screenshot_url: screenshotUrl };
  for (const key of PACK_EVIDENCE_FILENAME_KEYS) {
    delete sanitized[key];
  }
  return sanitized;
}

function stringFromRecord(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === "string" ? value.trim() : "";
}

function numberFromRecord(record: Record<string, unknown>, key: string) {
  const value = record[key];
  const numberValue = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numberValue) && numberValue > 0 ? numberValue : undefined;
}

function stringListFromRecord(record: Record<string, unknown>, key: string) {
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

function firstReportTopic(reportJson: Record<string, unknown>) {
  const topics = Array.isArray(reportJson.next_content_topics)
    ? reportJson.next_content_topics.map((item) => String(item).trim()).filter(Boolean)
    : [];
  if (topics[0]) return topics[0];
  const questionGaps = Array.isArray(reportJson.question_gaps) ? reportJson.question_gaps : [];
  for (const item of questionGaps) {
    if (item && typeof item === "object" && "question_text" in item) {
      const value = String((item as Record<string, unknown>).question_text ?? "").trim();
      if (value) return value;
    }
  }
  const keywordGaps = Array.isArray(reportJson.keyword_gaps) ? reportJson.keyword_gaps : [];
  for (const item of keywordGaps) {
    if (item && typeof item === "object" && "keyword" in item) {
      const value = String((item as Record<string, unknown>).keyword ?? "").trim();
      if (value) return `${value}怎么做 GEO 优化`;
    }
  }
  return "";
}

function yuanquanPackDir() {
  return join(workspaceRoot(), "outputs", "yuanquan_browser_observation_pack_q1");
}

function shellQuote(value: string) {
  return value.includes(" ") ? `"${value.replaceAll('"', '\\"')}"` : value;
}

function observationPackCommand(script: "inspect" | "dry-run" | "import", packDir: string, projectId: string) {
  const inputPath = join(packDir, "observations.json");
  const evidenceDir = join(packDir, "raw-evidence");
  if (script === "inspect") {
    return `UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/inspect_browser_observation_collection_pack.py --pack-dir ${shellQuote(packDir)}`;
  }
  const flag = script === "dry-run" ? "--dry-run" : "--generate-draft";
  return `UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/import_browser_observations.py --project-id ${shellQuote(projectId)} --input ${shellQuote(
    inputPath
  )} --evidence-dir ${shellQuote(evidenceDir)} ${flag}`;
}

async function writeYuanquanObservationPack(projectId: string) {
  const project = await getProject(projectId);
  const [questions, keywords, providers, browserObservations] = await Promise.all([
    getTargetQuestions(projectId),
    getKeywords(projectId),
    getLLMProviders(),
    getBrowserObservations(projectId, 500).catch(() => [])
  ]);
  const platforms = ["豆包", "DeepSeek", "Kimi", "千问"];
  const browserProviders = providers.filter((provider) => provider.provider_type === "browser_observation" && provider.status === "active");
  const providerByPlatform = new Map(
    browserProviders.map((provider) => [String(provider.cost_rule?.platform_name ?? provider.name).trim(), provider])
  );
  const missingPlatforms = platforms.filter((platform) => !providerByPlatform.has(platform));
  if (missingPlatforms.length > 0) {
    throw new Error(`缺少网页观测 Provider：${missingPlatforms.join("、")}。请先运行 ensure:browser-observation-providers。`);
  }
  const coverage = new Set(
    browserObservations
      .filter((item) => String(item.status ?? "success") === "success")
      .flatMap((item) => {
        const platform = String(item.platform_name ?? "").trim();
        const keys: string[] = [];
        if (platform && item.target_question_id) keys.push(`question:${item.target_question_id}:${platform}`);
        if (platform && item.keyword_id) keys.push(`keyword:${item.keyword_id}:${platform}`);
        return keys;
      })
  );
  const activeQuestions = questions
    .filter((item) => item.status === "active")
    .sort((a, b) => a.priority - b.priority || a.id - b.id);
  const activeKeywords = keywords
    .filter((item) => item.status === "active")
    .sort((a, b) => a.priority - b.priority || a.id - b.id);
  const questionGap = activeQuestions
    .map((question) => ({
      kind: "question" as const,
      id: question.id,
      promptText: question.question_text,
      missingPlatforms: platforms.filter((platform) => !coverage.has(`question:${question.id}:${platform}`))
    }))
    .find((item) => item.missingPlatforms.length > 0);
  const keywordGap = questionGap
    ? null
    : activeKeywords
        .map((keyword) => ({
          kind: "keyword" as const,
          id: keyword.id,
          promptText: `${keyword.keyword} 相关服务商怎么选？`,
          missingPlatforms: platforms.filter((platform) => !coverage.has(`keyword:${keyword.id}:${platform}`))
        }))
        .find((item) => item.missingPlatforms.length > 0);
  const target = questionGap ?? keywordGap;
  if (!target) {
    throw new Error("当前项目目标问题和关键词的四平台网页观测都已覆盖，无需生成新的采集包。");
  }
  const packDir = yuanquanPackDir();
  const evidenceDir = join(packDir, "raw-evidence");
  await mkdir(evidenceDir, { recursive: true });
  const observations = target.missingPlatforms.map((platform) => {
    const provider = providerByPlatform.get(platform);
    return {
      platform_name: platform,
      provider_id: provider?.id,
      target_question_id: target.kind === "question" ? target.id : null,
      keyword_id: target.kind === "keyword" ? target.id : null,
      prompt_text: target.promptText,
      raw_answer: "待填：粘贴该平台网页端返回的完整真实答案，保留推荐对象、判断依据和可见信源。",
      answer_summary: "待填：一句话概括该平台回答。",
      source_urls: [],
      evidence_filename: `${platform}-${target.kind}-${target.id}.png`,
      screenshot_url: "",
      observation_url: provider?.api_base_url,
      observer_name: "外部浏览器采集",
      note: "网页端人工观测，含截图留证。"
    };
  });
  const template = {
    project: {
      id: project.id,
      name: project.name,
      target_industry: project.target_industry,
      target_audience: project.target_audience
    },
    created_at: new Date().toISOString(),
    target: {
      type: target.kind,
      id: target.id,
      prompt_text: target.promptText,
      missing_platforms: target.missingPlatforms
    },
    instructions: [
      "在外部浏览器打开 observation_url。",
      "复制 prompt_text 到对应平台提问。",
      "把完整答案填入 raw_answer。",
      "保存截图或录屏；推荐把文件放到 raw-evidence 目录，并在 evidence_filename 填文件名。",
      "如果不用 evidence_filename，也可以把本地 file:// 路径或共享链接填入 screenshot_url。",
      "填完后回项目页点击校验采集包，再导入并生成报告稿件。"
    ],
    observations
  };
  const inspectCommand = observationPackCommand("inspect", packDir, projectId);
  const dryRunCommand = observationPackCommand("dry-run", packDir, projectId);
  const importCommand = observationPackCommand("import", packDir, projectId);
  const workOrder = [
    `# ${project.name} 网页端 GEO 采集工单`,
    "",
    "## 执行目标",
    "",
    "在外部浏览器打开本批缺口平台，使用同一目标问题或关键词问法提问，复制完整答案，保存截图或录屏，并把结果填回 JSON 模板。",
    "",
    `- 本批类型：${target.kind === "question" ? "目标问题" : "关键词问法"}`,
    `- 本批 Prompt：${target.promptText}`,
    `- 待补平台：${target.missingPlatforms.join("、")}`,
    "",
    "## 采集任务",
    "",
    ...observations.flatMap((item, index) => [
      `### ${index + 1}. ${item.platform_name}`,
      "",
      `- 网页入口：${item.observation_url}`,
      `- 目标问题：${item.prompt_text}`,
      `- 截图文件名：\`${item.evidence_filename}\``,
      "- 操作步骤：",
      "  1. 打开网页入口。",
      "  2. 复制目标问题并提问。",
      "  3. 等待答案完整生成。",
      "  4. 复制完整答案到 JSON 的 `raw_answer`。",
      "  5. 截图或录屏，文件名保持为 JSON 中的 `evidence_filename`。",
      "  6. 如果页面展示来源，把 URL 填入 `source_urls`。",
      ""
    ]),
    "## 校验与导入",
    "",
    "```bash",
    dryRunCommand,
    "```",
    "",
    "```bash",
    importCommand,
    "```",
    ""
  ].join("\n");
  const readme = [
    "# 春秋元泉 GEO 四平台采集包",
    "",
    "## 文件",
    "",
    `- \`observations.json\`：需要填写的观测 JSON，本批共 ${observations.length} 条。`,
    "- `work-order.md`：给采集执行者看的逐平台操作工单。",
    "- `raw-evidence/`：把截图或录屏文件放在这里，文件名与 JSON 的 `evidence_filename` 保持一致。",
    "- `inspect.sh`：检查当前包还缺哪些答案或截图，不入库。",
    "- `dry-run.sh`：只校验不入库。",
    "- `import-and-generate.sh`：正式导入，并生成成熟度报告、首篇稿件和 AI 评分。",
    "",
    "## 需要放入 raw-evidence 的文件",
    "",
    ...observations.map((item) => `- \`${item.evidence_filename}\``),
    "",
    "## inspect",
    "",
    "```bash",
    inspectCommand,
    "```",
    "",
    "## dry-run",
    "",
    "```bash",
    dryRunCommand,
    "```",
    "",
    "## 正式导入并生成稿件",
    "",
    "```bash",
    importCommand,
    "```",
    ""
  ].join("\n");
  await Promise.all([
    writeFile(join(packDir, "observations.json"), JSON.stringify(template, null, 2), "utf-8"),
    writeFile(join(packDir, "work-order.md"), workOrder, "utf-8"),
    writeFile(join(packDir, "README.md"), readme, "utf-8"),
    writeFile(join(packDir, "inspect.sh"), `#!/usr/bin/env bash\nset -euo pipefail\n${inspectCommand}\n`, "utf-8"),
    writeFile(join(packDir, "dry-run.sh"), `#!/usr/bin/env bash\nset -euo pipefail\n${dryRunCommand}\n`, "utf-8"),
    writeFile(join(packDir, "import-and-generate.sh"), `#!/usr/bin/env bash\nset -euo pipefail\n${importCommand}\n`, "utf-8")
  ]);
  return { packDir, observationCount: observations.length };
}

async function prepareNextYuanquanObservationPack(projectId: string) {
  if (Number(projectId) !== 1) return null;
  try {
    return await writeYuanquanObservationPack(projectId);
  } catch {
    return null;
  }
}

async function generateBrowserObservationCompletionArtifacts(
  projectId: string,
  payload: {
    targetQuestionId?: number;
    keywordId?: number;
    promptText: string;
    resultId: number;
  }
) {
  if (!payload.targetQuestionId && !payload.keywordId) return null;
  const observations = await getBrowserObservations(projectId, 500).catch(() => []);
  const observedPlatforms = new Set(
    observations
      .filter((item) => {
        if (payload.targetQuestionId) return item.target_question_id === payload.targetQuestionId;
        return item.keyword_id === payload.keywordId;
      })
      .map((item) => String(item.platform_name ?? "").trim())
      .filter(Boolean)
  );
  const complete = REQUIRED_BROWSER_OBSERVATION_PLATFORMS.every((platform) => observedPlatforms.has(platform));
  if (!complete) {
    return {
      complete: false,
      observedPlatforms: Array.from(observedPlatforms),
      missingPlatforms: REQUIRED_BROWSER_OBSERVATION_PLATFORMS.filter((platform) => !observedPlatforms.has(platform))
    };
  }
  const report = await generateMaturityReport(projectId, {
    title: "网页端四平台观测后 GEO 成熟度报告",
    report_period: new Date().toISOString().slice(0, 10)
  });
  const topic = firstReportTopic(report.report_json ?? {}) || payload.promptText;
  const draft = await generateArticleDraft(projectId, topic || undefined, {
    source_context: {
      source_type: "maturity_report",
      source_report_id: report.id,
      source_report_title: report.title,
      topic_source: "browser_observation_single_completion",
      report_detail_action: "browser_observation_four_platform_completion_generate_report_draft",
      browser_observation_result_ids: [payload.resultId],
      browser_observation_platforms: REQUIRED_BROWSER_OBSERVATION_PLATFORMS
    }
  });
  const review = await createArticleReview(projectId, draft.id);
  return {
    complete: true,
    report,
    draft,
    review,
    observedPlatforms: Array.from(observedPlatforms),
    missingPlatforms: []
  };
}

function providerCostRule(formData: FormData) {
  const inputPer1k = Number(formData.get("input_per_1k"));
  const outputPer1k = Number(formData.get("output_per_1k"));
  const timeoutSeconds = Number(formData.get("timeout_seconds"));
  const monthlySearchLimit = Number(formData.get("monthly_search_limit"));
  const platformKey = String(formData.get("platform_key") ?? "").trim().toLowerCase();
  const currency = String(formData.get("currency") ?? "USD").trim() || "USD";
  const existingRule = parseJsonObject(String(formData.get("existing_cost_rule") ?? ""));
  const channelRole = String(formData.get("channel_role") ?? "").trim().toLowerCase();
  const rule: Record<string, unknown> = { ...existingRule, currency };
  if (platformKey) rule.platform_key = platformKey;
  if (channelRole) rule.channel_role = channelRole;
  if (Number.isFinite(inputPer1k) && inputPer1k >= 0) rule.input_per_1k = inputPer1k;
  if (Number.isFinite(outputPer1k) && outputPer1k >= 0) rule.output_per_1k = outputPer1k;
  if (Number.isFinite(timeoutSeconds) && timeoutSeconds > 0) rule.timeout_seconds = timeoutSeconds;
  if (Number.isFinite(monthlySearchLimit) && monthlySearchLimit > 0) rule.monthly_search_limit = Math.floor(monthlySearchLimit);
  if (checkboxValue(formData, "enable_search")) rule.enable_search = true;
  return rule;
}

export async function loginAction(formData: FormData) {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");
  const response = await loginUser({ email, password });
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE, response.access_token, sessionCookieOptions());
  redirect("/");
}

export async function registerDemoUserAction(formData: FormData) {
  const name = String(formData.get("name") ?? "Demo Admin");
  const email = String(formData.get("email") ?? "demo@geo.local");
  const password = String(formData.get("password") ?? "geo-demo-123");
  await registerUser({ name, email, password, role: "super_admin" }).catch(async () => {
    await registerUser({ name, email, password, role: "company_admin" }).catch(() => null);
  });
  const response = await loginUser({ email, password });
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE, response.access_token, sessionCookieOptions());
  redirect("/");
}

export async function logoutAction() {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE);
  redirect("/login");
}

export async function createProjectAction(formData: FormData) {
  const company = await createCompany({
    name: String(formData.get("company_name") ?? ""),
    industry: String(formData.get("industry") ?? ""),
    website_url: String(formData.get("website_url") ?? ""),
    description: String(formData.get("company_description") ?? "")
  });

  const project = await createProject({
    company_id: company.id,
    name: String(formData.get("project_name") ?? ""),
    description: String(formData.get("project_description") ?? ""),
    target_industry: String(formData.get("industry") ?? ""),
    target_audience: String(formData.get("target_audience") ?? "")
  });

  const questionLines = lines(formData.get("target_questions"));
  if (questionLines.length > 0) {
    await bulkCreateTargetQuestions(
      project.id,
      questionLines.map((question_text) => ({ question_text }))
    );
  }

  const keywordLines = lines(formData.get("keywords"));
  if (keywordLines.length > 0) {
    await bulkCreateKeywords(project.id, keywordLines.map((keyword) => ({ keyword })));
  }

  const competitorLines = lines(formData.get("competitors"));
  for (const name of competitorLines) {
    await createCompetitor(project.id, { name });
  }

  revalidatePath("/");
  revalidatePath("/projects");
  redirect(`/projects/${project.id}`);
}

export async function appendProjectConfigAction(projectId: string, formData: FormData) {
  const numericProjectId = Number(projectId);
  const returnTo = String(formData.get("return_to") ?? "");
  const questionLines = lines(formData.get("target_questions"));
  const keywordLines = lines(formData.get("keywords"));
  const competitorLines = lines(formData.get("competitors"));
  if (questionLines.length > 0) {
    await bulkCreateTargetQuestions(
      numericProjectId,
      questionLines.map((question_text) => ({ question_text }))
    );
  }
  if (keywordLines.length > 0) {
    await bulkCreateKeywords(numericProjectId, keywordLines.map((keyword) => ({ keyword })));
  }
  for (const name of competitorLines) {
    await createCompetitor(numericProjectId, { name });
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/config`);
  const addedCount = questionLines.length + keywordLines.length + competitorLines.length;
  if (returnTo === `/projects/${projectId}/config`) {
    redirect(asRoute(`/projects/${projectId}/config?config_added=${addedCount}`));
  }
  redirect(`/projects/${projectId}?config_added=${addedCount}#project-config`);
}

export async function seedMaturityConfigAction(projectId: string, formData?: FormData) {
  const returnTo = formData ? String(formData.get("return_to") ?? "") : "";
  const [project, questions, keywords] = await Promise.all([
    getProject(projectId),
    getTargetQuestions(projectId).catch(() => []),
    getKeywords(projectId).catch(() => [])
  ]);
  const industry = project.target_industry || project.name || "企业服务";
  const existingQuestions = questions.map((item) => item.question_text);
  const existingKeywords = keywords.map((item) => item.keyword);
  const questionTemplates = [
    `${industry}服务商怎么选？`,
    `${industry}哪家公司值得推荐？`,
    `${industry}解决方案有哪些核心能力？`,
    `${industry}项目落地需要关注哪些风险？`,
    `${industry}供应商评估标准是什么？`,
    `${industry}企业采购时应该看哪些案例和资质？`,
    `${industry}如何判断服务商是否可靠？`,
    `${industry}有哪些典型应用场景？`,
    `${industry}建设方案和实施流程是什么？`,
    `${industry}服务商排名或推荐名单有哪些？`,
    `${project.name}在${industry}领域有什么优势？`,
    `${project.name}和同类服务商相比有什么差异？`
  ];
  const keywordTemplates = [
    industry,
    `${industry}服务商`,
    `${industry}解决方案`,
    `${industry}公司推荐`,
    `${industry}供应商`,
    `${industry}案例`,
    `${industry}评估标准`,
    `${industry}建设方案`,
    `${industry}咨询服务`,
    `${industry}排名`,
    project.name,
    `${project.name} ${industry}`
  ];
  const questionAdditions = missingTemplates(existingQuestions, questionTemplates, 10);
  const keywordAdditions = missingTemplates(existingKeywords, keywordTemplates, 10);
  if (questionAdditions.length > 0) {
    await bulkCreateTargetQuestions(
      Number(projectId),
      questionAdditions.map((question_text, index) => ({ question_text, priority: questions.length + index + 1 }))
    );
  }
  if (keywordAdditions.length > 0) {
    await bulkCreateKeywords(
      Number(projectId),
      keywordAdditions.map((keyword, index) => ({ keyword, priority: keywords.length + index + 1 }))
    );
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/config`);
  const addedCount = questionAdditions.length + keywordAdditions.length;
  if (returnTo === `/projects/${projectId}/config`) {
    redirect(asRoute(`/projects/${projectId}/config?config_added=${addedCount}`));
  }
  redirect(`/projects/${projectId}?config_added=${addedCount}#project-config`);
}

export async function runCrawlAction(projectId: string, formData?: FormData) {
  const providerIds = formData ? numberList(formData.getAll("provider_ids")) : [];
  const targetQuestionIds = formData ? numberList(formData.getAll("target_question_ids")) : [];
  const keywordIds = formData ? numberList(formData.getAll("keyword_ids")) : [];
  const maxEstimatedCost = Number(formData?.get("max_estimated_cost"));
  const task = await runCrawlTask(projectId, {
    provider_ids: providerIds,
    target_question_ids: targetQuestionIds,
    keyword_ids: keywordIds,
    execute_now: true,
    max_estimated_cost: Number.isFinite(maxEstimatedCost) && maxEstimatedCost >= 0 ? maxEstimatedCost : undefined
  });
  revalidatePath(`/projects/${projectId}`);
  redirect(`/projects/${projectId}/tasks/${task.id}`);
}

export async function createCrawlScheduleAction(projectId: string, formData: FormData) {
  const intervalHours = Number(formData.get("interval_hours"));
  const sampleRunsPerPrompt = Number(formData.get("sample_runs_per_prompt"));
  const providerIds = numberList(formData.getAll("provider_ids"));
  const targetQuestionIds = numberList(formData.getAll("target_question_ids"));
  const keywordIds = numberList(formData.getAll("keyword_ids"));
  const executeNow = formData.get("execute_now") === "on";
  const schedule = await createCrawlSchedule(projectId, {
    name: String(formData.get("name") ?? "每小时 GEO 监测"),
    schedule_type: String(formData.get("schedule_type") ?? "hourly"),
    interval_hours: Number.isFinite(intervalHours) && intervalHours > 0 ? intervalHours : 1,
    provider_ids: providerIds,
    target_question_ids: targetQuestionIds,
    keyword_ids: keywordIds,
    sample_runs_per_prompt:
      Number.isFinite(sampleRunsPerPrompt) && sampleRunsPerPrompt >= 1 ? sampleRunsPerPrompt : 1,
    status: String(formData.get("status") ?? "active"),
    execute_now: executeNow
  });
  revalidatePath(`/projects/${projectId}`);
  if (executeNow && schedule.last_created_task_id) {
    redirect(`/projects/${projectId}/tasks/${schedule.last_created_task_id}`);
  }
}

export async function runCrawlScheduleAction(projectId: string, scheduleId: number) {
  const task = await runCrawlSchedule(projectId, scheduleId);
  revalidatePath(`/projects/${projectId}`);
  redirect(`/projects/${projectId}/tasks/${task.id}`);
}

export async function updateCrawlResultAnalysisAction(projectId: string, resultId: string, formData: FormData) {
  const confidence = Number(formData.get("confidence"));
  const rankValue = String(formData.get("company_rank") ?? "").trim();
  const rank = Number(rankValue);
  await updateCrawlResultAnalysis(projectId, resultId, {
    company_mentioned: checkboxValue(formData, "company_mentioned"),
    company_recommended: checkboxValue(formData, "company_recommended"),
    company_rank: rankValue && Number.isFinite(rank) ? rank : null,
    sentiment: String(formData.get("sentiment") ?? "neutral"),
    confidence: Number.isFinite(confidence) ? confidence : 70,
    correction_note: String(formData.get("correction_note") ?? "").trim() || null
  });
  revalidatePath(`/projects/${projectId}/answers/${resultId}`);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/reports`);
  redirect(`/projects/${projectId}/answers/${resultId}?corrected=1#analysis-correction`);
}

export async function runDueCrawlSchedulesAction(projectId: string) {
  const result = await runReadyQueueJobs(25, projectId);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/dashboard`);
  redirect(
    `/projects/${projectId}?ready_created=${result.created_task_ids.length}&ready_ran=${result.ran_job_count}&ready_success=${result.success_job_count}&ready_failed=${result.failed_job_count}&ready_pending=${result.pending_job_count}`
  );
}

export async function createBrowserObservationAction(projectId: string, formData: FormData) {
  const providerId = Number(formData.get("provider_id"));
  const reportId = Number(formData.get("report_id"));
  const targetQuestionId = Number(formData.get("target_question_id"));
  const keywordId = Number(formData.get("keyword_id"));
  const sourceUrls = lines(formData.get("source_urls"));
  const promptText = String(formData.get("prompt_text") ?? "");
  const autoGenerateOnCompletion = checkboxValue(formData, "auto_generate_on_completion");
  let result;
  try {
    const uploadedScreenshotUrl = await saveEvidenceUpload(projectId, formData.get("screenshot_file"));
    const screenshotUrl = uploadedScreenshotUrl || String(formData.get("screenshot_url") ?? "").trim() || undefined;
    result = await createBrowserObservation(projectId, {
      provider_id: Number.isFinite(providerId) && providerId > 0 ? providerId : undefined,
      report_id: Number.isFinite(reportId) && reportId > 0 ? reportId : undefined,
      target_question_id: Number.isFinite(targetQuestionId) && targetQuestionId > 0 ? targetQuestionId : undefined,
      keyword_id: Number.isFinite(keywordId) && keywordId > 0 ? keywordId : undefined,
      platform_name: String(formData.get("platform_name") ?? "") || undefined,
      prompt_text: promptText,
      raw_answer: String(formData.get("raw_answer") ?? ""),
      answer_summary: String(formData.get("answer_summary") ?? "") || undefined,
      source_urls: sourceUrls,
      screenshot_url: screenshotUrl,
      observation_url: String(formData.get("observation_url") ?? "") || undefined,
      observer_name: String(formData.get("observer_name") ?? "") || undefined,
      note: String(formData.get("note") ?? "") || undefined
    });
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, error));
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/sources`);
  const nextPack = await prepareNextYuanquanObservationPack(projectId);
  if (autoGenerateOnCompletion) {
    let completion;
    try {
      completion = await generateBrowserObservationCompletionArtifacts(projectId, {
        targetQuestionId: Number.isFinite(targetQuestionId) && targetQuestionId > 0 ? targetQuestionId : undefined,
        keywordId: Number.isFinite(keywordId) && keywordId > 0 ? keywordId : undefined,
        promptText,
        resultId: result.id
      });
    } catch (error) {
      redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, error));
    }
    if (completion?.complete && completion.draft && completion.review && completion.report) {
      revalidatePath(`/projects/${projectId}/reports`);
      revalidatePath(`/projects/${projectId}/drafts`);
      revalidatePath(`/projects/${projectId}/drafts/${completion.draft.id}`);
      revalidatePath("/reviews");
      redirect(
        `/projects/${projectId}/drafts/${completion.draft.id}?reviewed=${completion.review.id}&report_id=${
          completion.report.id
        }&observation_created=1&observation_result=${result.id}${
          nextPack ? `&next_pack_prepared=${nextPack.observationCount}` : ""
        }#reviews`
      );
    }
  }
  redirect(
    `/projects/${projectId}?observation_created=1&observation_result=${result.id}&observation_sources=${
      result.citation_sources.length
    }&observation_screenshots=${
      result.citation_sources.filter((item) => item.source_type === "screenshot").length
    }${nextPack ? `&next_pack_prepared=${nextPack.observationCount}` : ""}#browser-observation`
  );
}

export async function bulkCreateBrowserObservationsAction(projectId: string, formData: FormData) {
  const uploadedFile = formData.get("observations_file");
  let rawInput = String(formData.get("observations_json") ?? "").trim();
  if (
    uploadedFile &&
    typeof uploadedFile === "object" &&
    "size" in uploadedFile &&
    Number(uploadedFile.size) > 0 &&
    "text" in uploadedFile &&
    typeof uploadedFile.text === "function"
  ) {
    rawInput = String(await uploadedFile.text()).trim();
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawInput);
  } catch {
    redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, new Error("批量观测 JSON 格式不正确。")));
  }
  const parsedObservations =
    Array.isArray(parsed)
      ? parsed
      : parsed && typeof parsed === "object" && Array.isArray((parsed as Record<string, unknown>).observations)
        ? ((parsed as Record<string, unknown>).observations as unknown[])
        : [];
  if (parsedObservations.length === 0) {
    redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, new Error("请粘贴至少一条网页观测记录。")));
  }

  const providers = await getLLMProviders().catch(() => []);
  const browserProviders = providers.filter((provider) => provider.provider_type === "browser_observation");
  const providerByPlatform = new Map(
    browserProviders.map((provider) => [
      String(provider.cost_rule?.platform_name ?? provider.name).trim(),
      provider.id
    ])
  );
  const observations = [];
  const archiveEvidence = !checkboxValue(formData, "dry_run");
  try {
    for (const item of parsedObservations.slice(0, 20)) {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        throw new Error("批量观测记录必须是对象数组。");
      }
      const record = item as Record<string, unknown>;
      const platformName = stringFromRecord(record, "platform_name");
      const promptText = stringFromRecord(record, "prompt_text");
      const rawAnswer = stringFromRecord(record, "raw_answer");
      const screenshotUrl = await resolvePackEvidenceUrl(projectId, record, archiveEvidence);
      if (hasObservationPlaceholder(observationValidationRecord(record, screenshotUrl))) {
        throw new Error("观测记录里仍包含待填、example.com 或截图占位内容。请先填入真实网页答案、信源和截图证据。");
      }
      if (!platformName || !promptText || !rawAnswer) {
        throw new Error("每条记录都需要 platform_name、prompt_text、raw_answer。");
      }
      if (rawAnswer.length < 80) {
        throw new Error("每条网页端答案至少需要 80 个字符，避免把摘要或空结果当成真实观测入库。");
      }
      if (!screenshotUrl) {
        throw new Error("每条网页观测都需要 screenshot_url 或 evidence_filename 对应的截图/录屏文件。");
      }
      const providerId = numberFromRecord(record, "provider_id") ?? providerByPlatform.get(platformName);
      observations.push({
        provider_id: providerId,
        report_id: numberFromRecord(record, "report_id"),
        target_question_id: numberFromRecord(record, "target_question_id"),
        keyword_id: numberFromRecord(record, "keyword_id"),
        platform_name: platformName,
        prompt_text: promptText,
        raw_answer: rawAnswer,
        answer_summary: stringFromRecord(record, "answer_summary") || undefined,
        source_urls: stringListFromRecord(record, "source_urls"),
        screenshot_url: screenshotUrl,
        observation_url: stringFromRecord(record, "observation_url") || undefined,
        observer_name: stringFromRecord(record, "observer_name") || undefined,
        note: stringFromRecord(record, "note") || undefined
      });
    }
    const platformSet = new Set(observations.map((item) => item.platform_name));
    const missingPlatforms = REQUIRED_BROWSER_OBSERVATION_PLATFORMS.filter((platform) => !platformSet.has(platform));
    if (missingPlatforms.length > 0) {
      throw new Error(`批量观测至少需要覆盖豆包、DeepSeek、Kimi、千问四个平台。当前缺少：${missingPlatforms.join("、")}。`);
    }
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, error));
  }

  if (checkboxValue(formData, "dry_run")) {
    const platformCount = new Set(observations.map((item) => item.platform_name)).size;
    redirect(
      `/projects/${projectId}?observation_validated=${observations.length}&observation_validated_platforms=${platformCount}#browser-observation`
    );
  }

  let result;
  try {
    result = await bulkCreateBrowserObservations(projectId, observations);
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, error));
  }

  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/sources`);
  revalidatePath(`/projects/${projectId}/reports`);
  const nextPack = await prepareNextYuanquanObservationPack(projectId);
  if (checkboxValue(formData, "generate_report")) {
    let report;
    try {
      report = await generateMaturityReport(projectId, {
        title: "网页端四平台观测后 GEO 成熟度报告",
        report_period: new Date().toISOString().slice(0, 10)
      });
    } catch (error) {
      redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, error));
    }
    revalidatePath(`/projects/${projectId}/reports/${report.id}`);
    if (checkboxValue(formData, "generate_draft")) {
      let draft;
      let review;
      const topic = firstReportTopic(report.report_json ?? {});
      try {
        draft = await generateArticleDraft(projectId, topic || undefined, {
          source_context: {
            source_type: "maturity_report",
            source_report_id: report.id,
            source_report_title: report.title,
            topic_source: "browser_observation_batch_report",
            report_detail_action: "browser_observation_bulk_generate_report_draft",
            browser_observation_result_ids: result.result_ids,
            browser_observation_platforms: Array.from(new Set(observations.map((item) => item.platform_name)))
          }
        });
        review = await createArticleReview(projectId, draft.id);
      } catch (error) {
        redirect(actionErrorTarget(`/projects/${projectId}/reports/${report.id}`, error));
      }
      revalidatePath(`/projects/${projectId}/drafts`);
      revalidatePath(`/projects/${projectId}/drafts/${draft.id}`);
      revalidatePath("/reviews");
      redirect(
        `/projects/${projectId}/drafts/${draft.id}?reviewed=${review.id}&observation_bulk_created=${
          result.created_count
        }&report_id=${report.id}${nextPack ? `&next_pack_prepared=${nextPack.observationCount}` : ""}#reviews`
      );
    }
    redirect(
      `/projects/${projectId}/reports/${report.id}?observation_bulk_created=${result.created_count}&observation_bulk_sources=${
        result.source_count
      }&observation_bulk_screenshots=${result.screenshot_evidence_count}${
        nextPack ? `&next_pack_prepared=${nextPack.observationCount}` : ""
      }`
    );
  }
  redirect(
    `/projects/${projectId}?observation_bulk_created=${result.created_count}&observation_bulk_sources=${
      result.source_count
    }&observation_bulk_screenshots=${result.screenshot_evidence_count}${
      nextPack ? `&next_pack_prepared=${nextPack.observationCount}` : ""
    }#browser-observation`
  );
}

export async function validateBrowserObservationPackAction(projectId: string) {
  const formData = new FormData();
  formData.set("observations_json", await readYuanquanObservationPackJson());
  formData.set("dry_run", "on");
  await bulkCreateBrowserObservationsAction(projectId, formData);
}

export async function importBrowserObservationPackAction(projectId: string) {
  const formData = new FormData();
  formData.set("observations_json", await readYuanquanObservationPackJson());
  formData.set("generate_report", "on");
  formData.set("generate_draft", "on");
  await bulkCreateBrowserObservationsAction(projectId, formData);
}

export async function prepareBrowserObservationPackAction(projectId: string) {
  let result;
  try {
    result = await writeYuanquanObservationPack(projectId);
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}#browser-observation`, error));
  }
  revalidatePath(`/projects/${projectId}`);
  redirect(
    `/projects/${projectId}?pack_prepared=${result.observationCount}&pack_dir=${encodeURIComponent(
      result.packDir
    )}#browser-observation`
  );
}

export async function generateReportAction(projectId: string) {
  const report = await generateMaturityReport(projectId);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/reports`);
  revalidatePath(`/projects/${projectId}/reports/${report.id}`);
  redirect(`/projects/${projectId}/reports/${report.id}`);
}

export async function runDiagnosticAction(projectId: string, formData: FormData) {
  const providerIds = formData.getAll("provider_ids").map(Number).filter((value) => Number.isFinite(value) && value > 0);
  const targetQuestionIds = formData.getAll("target_question_ids").map(Number).filter((value) => Number.isFinite(value) && value > 0);
  const keywordIds = formData.getAll("keyword_ids").map(Number).filter((value) => Number.isFinite(value) && value > 0);
  const maxEstimatedCost = Number(formData.get("max_estimated_cost"));
  const result = await runDiagnostic(projectId, {
    provider_ids: providerIds,
    target_question_ids: targetQuestionIds,
    keyword_ids: keywordIds,
    execute_now: true,
    generate_report: true,
    create_action_goals: true,
    max_estimated_cost: Number.isFinite(maxEstimatedCost) && maxEstimatedCost >= 0 ? maxEstimatedCost : undefined,
    title: String(formData.get("title") ?? "") || undefined,
    report_period: String(formData.get("report_period") ?? "") || undefined
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/answers`);
  revalidatePath(`/projects/${projectId}/reports`);
  if (result.report_id) {
    revalidatePath(`/projects/${projectId}/reports/${result.report_id}`);
  }
  const params = new URLSearchParams({
    diagnostic_task: String(result.task_id),
    diagnostic_status: result.task_status,
    diagnostic_goals: String(result.action_goal_count),
    diagnostic_expected: String(result.expected_call_count),
    diagnostic_results: String(result.result_count),
    diagnostic_estimated_cost: String(result.estimated_cost),
    diagnostic_estimated_tokens: String(result.estimated_total_tokens)
  });
  if (result.report_id) {
    params.set("diagnostic_report", String(result.report_id));
  }
  if (result.blockers.length > 0) {
    params.set("diagnostic_blockers", result.blockers.join("；").slice(0, 400));
  }
  if (result.task_status !== "success") {
    redirect(`/projects/${projectId}/tasks/${result.task_id}?${params.toString()}`);
  }
  redirect(`/projects/${projectId}?${params.toString()}#stage-goals`);
}

export async function createReportActionGoalsAction(projectId: string, reportId: string) {
  const created = await createMaturityReportActionGoals(projectId, reportId);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/reports`);
  revalidatePath(`/projects/${projectId}/reports/${reportId}`);
  if (created.length === 0) {
    redirect(`/projects/${projectId}/reports/${reportId}?report_actions=existing#report-actions`);
  }
  redirect(`/projects/${projectId}/reports/${reportId}?report_actions=${created.length}#report-actions`);
}

export async function generateDraftAction(projectId: string, formData: FormData) {
  const customTopic = String(formData.get("topic") ?? "").trim();
  const suggestedTopic = String(formData.get("suggested_topic") ?? "").trim();
  const topic = customTopic || suggestedTopic;
  let draft;
  try {
    draft = await generateArticleDraft(projectId, topic || undefined);
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}#drafts`, error));
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/drafts`);
  revalidatePath(`/projects/${projectId}/drafts/${draft.id}`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/drafts/${draft.id}`);
}

export async function generateDraftAndReviewAction(projectId: string, formData: FormData) {
  const customTopic = String(formData.get("topic") ?? "").trim();
  const suggestedTopic = String(formData.get("suggested_topic") ?? "").trim();
  const topic = customTopic || suggestedTopic;
  let draft;
  let review;
  try {
    draft = await generateArticleDraft(projectId, topic || undefined);
    review = await createArticleReview(projectId, draft.id);
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}/drafts`, error));
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/drafts`);
  revalidatePath(`/projects/${projectId}/drafts/${draft.id}`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/drafts/${draft.id}?reviewed=${review.id}#reviews`);
}

export async function generateDraftFromReportTopicAction(projectId: string, reportId: string, formData: FormData) {
  const topic = String(formData.get("topic") ?? "").trim();
  let draft;
  let review;
  try {
    const report = await getMaturityReport(projectId, reportId);
    draft = await generateArticleDraft(projectId, topic || undefined, {
      source_context: {
        source_type: "maturity_report",
        source_report_id: report.id,
        source_report_title: report.title,
        topic_source: "maturity_report",
        report_detail_action: "single_topic_generate_review"
      }
    });
    review = await createArticleReview(projectId, draft.id);
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}/reports/${reportId}`, error));
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/reports/${reportId}`);
  revalidatePath(`/projects/${projectId}/drafts`);
  revalidatePath(`/projects/${projectId}/drafts/${draft.id}`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/drafts/${draft.id}?reviewed=${review.id}#reviews`);
}

export async function bulkGenerateDraftsFromReportTopicsAction(projectId: string, reportId: string, formData: FormData) {
  const report = await getMaturityReport(projectId, reportId);
  const topics = formData
    .getAll("topics")
    .map((value) => String(value).trim())
    .filter(Boolean)
    .filter((topic, index, list) => list.indexOf(topic) === index)
    .slice(0, 5);
  const created: Array<{ draftId: number; reviewId: number }> = [];
  for (const [index, topic] of topics.entries()) {
    const draft = await generateArticleDraft(projectId, topic, {
      source_context: {
        source_type: "maturity_report",
        source_report_id: report.id,
        source_report_title: report.title,
        topic_source: "maturity_report",
        report_detail_action: "bulk_topic_generate_review",
        bulk_topic_index: index + 1,
        bulk_topic_count: topics.length
      }
    });
    const review = await createArticleReview(projectId, draft.id);
    created.push({ draftId: draft.id, reviewId: review.id });
    revalidatePath(`/projects/${projectId}/drafts/${draft.id}`);
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/reports/${reportId}`);
  revalidatePath(`/projects/${projectId}/drafts`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/drafts?bulk_generated=${created.length}&bulk_reviewed=${created.length}`);
}

export async function createProjectStageGoalAction(projectId: string, formData: FormData) {
  const targetValue = Number(formData.get("target_value"));
  const baselineValue = Number(formData.get("baseline_value"));
  await createProjectStageGoal(projectId, {
    title: String(formData.get("title") ?? ""),
    metric_key: String(formData.get("metric_key") ?? "health_score"),
    target_value: Number.isFinite(targetValue) ? targetValue : 0,
    baseline_value: Number.isFinite(baselineValue) ? baselineValue : 0,
    due_at: String(formData.get("due_at") ?? "") || undefined,
    owner: String(formData.get("owner") ?? "") || undefined,
    status: String(formData.get("status") ?? "active"),
    note: String(formData.get("note") ?? "") || undefined
  });
  revalidatePath(`/projects/${projectId}`);
}

export async function updateProjectStageGoalStatusAction(projectId: string, goalId: number, status: string) {
  await updateProjectStageGoal(projectId, goalId, { status });
  revalidatePath(`/projects/${projectId}`);
}

export async function runProjectStageGoalRemindersAction(projectId: string) {
  await runProjectStageGoalReminders(projectId);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath("/admin/alerts");
}

export async function runProjectStageGoalActionAction(projectId: string, goalId: number, actionType: string) {
  await runProjectStageGoalAction(projectId, goalId, actionType);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/sources`);
  revalidatePath(`/projects/${projectId}/review-archive`);
  revalidatePath(`/projects/${projectId}/delivery-package`);
  revalidatePath("/admin/alerts");
  revalidatePath("/reviews");
}

export async function reviewDraftAction(projectId: string, draftId: number) {
  let review;
  try {
    review = await createArticleReview(projectId, draftId);
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}/drafts/${draftId}`, error));
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/drafts/${draftId}`);
  revalidatePath(`/projects/${projectId}/drafts`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/drafts/${draftId}?reviewed=${review.id}#reviews`);
}

export async function reviseDraftFromReviewAction(projectId: string, draftId: number) {
  let revised;
  let reviews;
  try {
    revised = await reviseArticleDraft(projectId, draftId);
    reviews = await getArticleReviews(projectId, revised.id).catch(() => []);
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}/drafts/${draftId}`, error));
  }
  const latestReview = reviews[0];
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/drafts/${draftId}`);
  revalidatePath(`/projects/${projectId}/drafts/${revised.id}`);
  revalidatePath(`/projects/${projectId}/drafts`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/drafts/${revised.id}${latestReview ? `?reviewed=${latestReview.id}#reviews` : ""}`);
}

export async function bulkReviewQueueAction() {
  const queue = await getReviewQueue();
  const targets = queue.filter((item) => item.latest_score == null).slice(0, 20);
  for (const item of targets) {
    const projectId = String(item.project_id);
    if (item.type === "draft") {
      await createArticleReview(projectId, item.id);
      revalidatePath(`/projects/${projectId}/drafts/${item.id}`);
    } else {
      await createContentAssetReview(projectId, item.id);
      revalidatePath(`/projects/${projectId}/assets`);
    }
    revalidatePath(`/projects/${projectId}`);
  }
  revalidatePath("/reviews");
  redirect(`/reviews?bulk_scored=${targets.length}`);
}

export async function bulkApproveHighScoreDraftsAction() {
  const queue = await getReviewQueue();
  const targets = queue
    .filter((item) => item.type === "draft")
    .filter((item) => item.status !== "approved")
    .filter((item) => Number(item.latest_score ?? 0) >= 85)
    .slice(0, 20);
  for (const item of targets) {
    const projectId = String(item.project_id);
    await decideArticleDraftReview(projectId, item.id, {
      decision: "approved",
      comment: `审核台批量通过：AI 评分 ${item.latest_score} ${item.latest_grade ?? ""}。`
    });
    revalidatePath(`/projects/${projectId}`);
    revalidatePath(`/projects/${projectId}/drafts/${item.id}`);
    revalidatePath(`/projects/${projectId}/drafts`);
  }
  const targetProjectIds = Array.from(new Set(targets.map((item) => item.project_id))).slice(0, 3);
  revalidatePath("/reviews");
  redirect(`/reviews?bulk_approved=${targets.length}&bulk_projects=${targetProjectIds.join(",")}`);
}

export async function decideDraftReviewAction(
  projectId: string,
  draftId: number,
  decision: "approved" | "rejected",
  formData: FormData
) {
  let review;
  try {
    review = await decideArticleDraftReview(projectId, draftId, {
      decision,
      comment: String(formData.get("comment") ?? "") || undefined
    });
  } catch (error) {
    redirect(actionErrorTarget(`/projects/${projectId}/drafts/${draftId}`, error));
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/drafts/${draftId}`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/drafts/${draftId}?decision=${review.status}#manual-review`);
}

export async function approveDraftAndCreatePlacementAction(projectId: string, draftId: number, formData: FormData) {
  const comment = String(formData.get("comment") ?? "").trim();
  const channel = String(formData.get("channel") ?? "").trim() || "报告承接稿件投放";
  const targetUrl = String(formData.get("target_url") ?? "").trim();
  const notes = String(formData.get("notes") ?? "").trim();
  await decideArticleDraftReview(projectId, draftId, {
    decision: "approved",
    comment: comment || "已人工确认，可进入 GEO 投放计划。"
  });
  const placement = await createPlacement(projectId, {
    article_draft_id: draftId,
    channel,
    target_url: targetUrl || undefined,
    status: "planned",
    notes: notes || "稿件已通过人工审核，加入 GEO 投放计划。"
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/drafts/${draftId}`);
  revalidatePath(`/projects/${projectId}/sources`);
  revalidatePath(`/projects/${projectId}/placements`);
  revalidatePath(`/projects/${projectId}/placements/${placement.id}/impact`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/placements/${placement.id}/impact`);
}

export async function createProviderAction(formData: FormData) {
  const apiKey = String(formData.get("api_key") ?? "").trim();
  await createLLMProvider({
    name: String(formData.get("name") ?? ""),
    provider_type: String(formData.get("provider_type") ?? "mock"),
    model_name: String(formData.get("model_name") ?? ""),
    api_base_url: String(formData.get("api_base_url") ?? "") || undefined,
    auth_config: apiKey ? { api_key: apiKey } : undefined,
    cost_rule: providerCostRule(formData),
    status: String(formData.get("status") ?? "active")
  });
  revalidatePath("/admin/providers");
}

export async function createProviderModelsAction(formData: FormData) {
  const apiKey = String(formData.get("api_key") ?? "").trim();
  const modelNames = formData.getAll("model_names").map(String).map((item) => item.trim()).filter(Boolean);
  const fallbackModel = String(formData.get("model_name") ?? "").trim();
  const selectedModels = modelNames.length ? modelNames : fallbackModel ? [fallbackModel] : [];
  const baseName = String(formData.get("name") ?? "模型渠道").trim() || "模型渠道";
  if (!selectedModels.length) throw new Error("请至少选择一个模型");
  for (const modelName of selectedModels) {
    await createLLMProvider({
      name: selectedModels.length > 1 ? `${baseName} · ${modelName}` : baseName,
      provider_type: String(formData.get("provider_type") ?? "mock"),
      model_name: modelName,
      api_base_url: String(formData.get("api_base_url") ?? "") || undefined,
      auth_config: apiKey ? { api_key: apiKey } : undefined,
      cost_rule: providerCostRule(formData),
      status: String(formData.get("status") ?? "active")
    });
  }
  revalidatePath("/admin/providers");
}

export async function saveOfficialProviderAction(formData: FormData) {
  const platformKey = String(formData.get("platform_key") ?? "").trim().toLowerCase() as ProviderCatalogKey;
  const catalog = PROVIDER_CATALOG.find((item) => item.key === platformKey);
  if (!catalog) throw new Error("没有找到当前模型的官方渠道定义");

  const apiKey = String(formData.get("api_key") ?? "").trim();
  const requestedReturnTo = String(formData.get("return_to") ?? "");
  const returnTo = requestedReturnTo.startsWith("/admin/providers")
    ? requestedReturnTo
    : `/admin/providers?model=${platformKey}`;
  const modelName = String(formData.get("model_name") ?? catalog.defaultModel).trim() || catalog.defaultModel;
  const workspaceId = String(formData.get("workspace_id") ?? "").trim();
  const providers = await getLLMProviders();
  const candidates = providers.filter((provider) =>
    providerMatchesCatalog(provider, platformKey) && isOfficialProvider(provider, platformKey)
  );
  const preferred = candidates.find((provider) => provider.provider_type === catalog.defaultProviderType && provider.status === "active")
    ?? candidates.find((provider) => provider.status === "active")
    ?? candidates[0];
  const costRule = {
    ...providerCostRule(formData),
    platform_key: platformKey,
    channel_role: "official",
    enable_search: true,
    ...(workspaceId ? { workspace_id: workspaceId } : {}),
  };
  const apiBaseUrl = platformKey === "qwen" && workspaceId
    ? `https://${workspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
    : catalog.defaultBaseUrl;
  const payload = {
    name: `${catalog.label} 官方渠道`,
    provider_type: catalog.defaultProviderType,
    model_name: modelName,
    api_base_url: apiBaseUrl,
    ...(apiKey ? { auth_config: { api_key: apiKey } } : {}),
    cost_rule: costRule,
    status: "active",
  };
  const saved = preferred
    ? await updateLLMProvider(String(preferred.id), payload)
    : await createLLMProvider(payload);

  for (const duplicate of candidates) {
    if (duplicate.id === saved.id) continue;
    await updateLLMProvider(String(duplicate.id), {
      status: "inactive",
      cost_rule: { ...duplicate.cost_rule, platform_key: platformKey, channel_role: "archived_duplicate" },
    });
  }
  revalidatePath("/admin/providers");
  revalidatePath(`/admin/providers/${saved.id}/test`);
  redirect(`${returnTo}${returnTo.includes("?") ? "&" : "?"}saved=1&provider=${saved.id}` as Route);
}

export async function createProviderFromTemplateAction(formData: FormData) {
  const returnTo = String(formData.get("return_to") ?? "");
  const provider = await createLLMProvider({
    name: String(formData.get("template_name") ?? ""),
    provider_type: String(formData.get("provider_type") ?? "mock"),
    model_name: String(formData.get("template_model_name") ?? ""),
    api_base_url: String(formData.get("template_base_url") ?? "") || undefined,
    cost_rule: providerCostRule(formData),
    status: "active"
  });
  revalidatePath("/admin/providers");
  const query = new URLSearchParams({ created: "template" });
  if (returnTo.startsWith("/")) query.set("return_to", returnTo);
  redirect(`/admin/providers/${provider.id}/test?${query.toString()}`);
}

export async function updateProviderAction(providerId: string, formData: FormData) {
  const apiKey = String(formData.get("api_key") ?? "").trim();
  const returnTo = String(formData.get("return_to") ?? "");
  const prompt = String(formData.get("prompt") ?? "");
  const payload: {
    name: string;
    provider_type: string;
    model_name: string;
    api_base_url: string | null;
    auth_config?: Record<string, unknown>;
    cost_rule?: Record<string, unknown>;
    status: string;
  } = {
    name: String(formData.get("name") ?? ""),
    provider_type: String(formData.get("provider_type") ?? "mock"),
    model_name: String(formData.get("model_name") ?? ""),
    api_base_url: String(formData.get("api_base_url") ?? "") || null,
    cost_rule: providerCostRule(formData),
    status: String(formData.get("status") ?? "active")
  };
  if (apiKey) {
    payload.auth_config = { api_key: apiKey };
  }
  await updateLLMProvider(providerId, payload);
  revalidatePath("/admin/providers");
  revalidatePath(`/admin/providers/${providerId}/test`);
  const query = new URLSearchParams({ updated: "1" });
  if (returnTo.startsWith("/")) {
    query.set("return_to", returnTo);
  }
  if (prompt) {
    query.set("prompt", prompt);
  }
  redirect(`/admin/providers/${providerId}/test?${query.toString()}`);
}

export async function createUserAction(formData: FormData) {
  const companyId = Number(formData.get("company_id"));
  await createUser({
    name: String(formData.get("name") ?? ""),
    email: String(formData.get("email") ?? ""),
    password: String(formData.get("password") ?? "geo-demo-123"),
    company_id: Number.isFinite(companyId) && companyId > 0 ? companyId : undefined,
    phone: String(formData.get("phone") ?? "") || undefined,
    role: String(formData.get("role") ?? "viewer"),
    status: String(formData.get("status") ?? "active")
  });
  revalidatePath("/admin/users");
}

export async function deactivateUserAction(userId: number) {
  await deactivateUser(userId);
  revalidatePath("/admin/users");
}

export async function testProviderAction(providerId: string, formData: FormData) {
  const returnTo = String(formData.get("return_to") ?? "");
  const result = await testLLMProvider(providerId, {
    prompt_text: String(formData.get("prompt_text") ?? "网络安全培训公司哪家好？"),
    company_name: String(formData.get("company_name") ?? "示例企业"),
    industry: String(formData.get("industry") ?? "网络安全")
  });
  const query = new URLSearchParams({
    ok: result.ok ? "1" : "0",
    prompt: result.prompt_text,
    summary: result.answer_summary ?? "",
    preview: result.raw_answer_preview ?? "",
    error: result.error_message ?? ""
  });
  if (returnTo.startsWith("/")) {
    query.set("return_to", returnTo);
  }
  redirect(`/admin/providers/${providerId}/test?${query.toString()}`);
}

export async function queueProviderTestAction(providerId: string, promptText: string) {
  return queueLLMProviderTest(providerId, {
    prompt_text: promptText || "企业级大模型治理平台怎么选？",
    company_name: "春秋元泉",
    industry: "网络安全",
  });
}

export async function getProviderTestJobAction(providerId: string, jobId: number) {
  return getLLMProviderTestJob(providerId, jobId);
}

export async function saveAndTestProviderAction(providerId: string, formData: FormData) {
  const apiKey = String(formData.get("api_key") ?? "").trim();
  const returnTo = String(formData.get("return_to") ?? "");
  const promptText = String(formData.get("prompt_text") ?? "企业级大模型治理平台怎么选？");
  const payload: {
    name: string;
    provider_type: string;
    model_name: string;
    api_base_url: string | null;
    auth_config?: Record<string, unknown>;
    cost_rule?: Record<string, unknown>;
    status: string;
  } = {
    name: String(formData.get("name") ?? ""),
    provider_type: String(formData.get("provider_type") ?? "mock"),
    model_name: String(formData.get("model_name") ?? ""),
    api_base_url: String(formData.get("api_base_url") ?? "") || null,
    cost_rule: providerCostRule(formData),
    status: String(formData.get("status") ?? "active")
  };
  if (apiKey) payload.auth_config = { api_key: apiKey };
  await updateLLMProvider(providerId, payload);
  revalidatePath("/admin/providers");
  revalidatePath(`/admin/providers/${providerId}/test`);

  let testResult;
  let errorMessage = "";
  try {
    testResult = await testLLMProvider(providerId, {
      prompt_text: promptText,
      company_name: "春秋元泉",
      industry: "企业 AI 安全与治理"
    });
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : "连接验证失败";
  }
  const query = new URLSearchParams({
    updated: "1",
    ok: testResult?.ok ? "1" : "0",
    prompt: testResult?.prompt_text ?? promptText,
    summary: testResult?.answer_summary ?? "",
    preview: testResult?.raw_answer_preview ?? "",
    error: errorMessage || testResult?.error_message || ""
  });
  if (returnTo.startsWith("/")) query.set("return_to", returnTo);
  redirect(`/admin/providers/${providerId}/test?${query.toString()}`);
}

export async function updateAlertAction(alertId: number, status: "acknowledged" | "resolved") {
  await updateAlert(alertId, status);
  revalidatePath("/admin/alerts");
}

export async function createAlertReportActionGoalsAction(alertId: number) {
  const result = await createAlertReportActionGoals(alertId);
  const projectId = Number(result.detail.project_id);
  revalidatePath("/admin/alerts");
  if (Number.isFinite(projectId) && projectId > 0) {
    revalidatePath(`/projects/${projectId}`);
    revalidatePath(`/projects/${projectId}/dashboard`);
  }
}

export async function runPlacementRemindersAction() {
  await runPlacementReminders();
  revalidatePath("/admin/alerts");
}

export async function runMonitoringAlertsAction() {
  await runMonitoringAlerts();
  revalidatePath("/admin/alerts");
}

export async function runNextQueueJobAction() {
  const result = await runNextQueueJob();
  revalidatePath("/admin/queue");
  revalidatePath("/admin/alerts");
  revalidatePath("/projects");
  const status = result.job?.status ?? "none";
  redirect(`/admin/queue?job_ran=${result.ran ? "1" : "0"}&job_status=${status}`);
}

export async function runReadyQueueJobsAction() {
  const result = await runReadyQueueJobs(25);
  revalidatePath("/admin/queue");
  revalidatePath("/admin/alerts");
  revalidatePath("/projects");
  redirect(
    `/admin/queue?ready_created=${result.created_task_ids.length}&ready_ran=${result.ran_job_count}&ready_success=${result.success_job_count}&ready_failed=${result.failed_job_count}&ready_pending=${result.pending_job_count}`
  );
}

export async function createReviewRuleAction(formData: FormData) {
  const maxScore = Number(formData.get("max_score"));
  const weight = Number(formData.get("weight"));
  const checks = parseJsonObject(String(formData.get("checks_json") ?? ""));
  await createReviewRule({
    rule_key: String(formData.get("rule_key") ?? "").trim(),
    name: String(formData.get("name") ?? "").trim(),
    description: String(formData.get("description") ?? "").trim() || null,
    applies_to: String(formData.get("applies_to") ?? "article"),
    max_score: Number.isFinite(maxScore) && maxScore > 0 ? maxScore : 10,
    weight: Number.isFinite(weight) && weight > 0 ? weight : 1,
    checks_json: checks,
    status: String(formData.get("status") ?? "active"),
    version: 1
  });
  revalidatePath("/admin/review-rules");
}

export async function createReportTemplateAction(formData: FormData) {
  const version = Number(formData.get("version"));
  await createReportTemplate({
    template_key: String(formData.get("template_key") ?? "").trim(),
    name: String(formData.get("name") ?? "").trim(),
    description: String(formData.get("description") ?? "").trim() || null,
    applies_to: String(formData.get("applies_to") ?? "maturity_report"),
    sections_json: parseJsonArray(String(formData.get("sections_json") ?? "")),
    scoring_json: parseJsonObject(String(formData.get("scoring_json") ?? "")),
    delivery_checks_json: parseJsonArray(String(formData.get("delivery_checks_json") ?? "")),
    status: String(formData.get("status") ?? "active"),
    version: Number.isFinite(version) && version > 0 ? version : 1
  });
  revalidatePath("/admin/report-templates");
}

export async function createContentAssetAction(projectId: string, companyId: number, formData: FormData) {
  await createContentAsset(projectId, {
    company_id: companyId,
    title: String(formData.get("title") ?? ""),
    content_type: String(formData.get("content_type") ?? "article"),
    source_url: String(formData.get("source_url") ?? "") || undefined,
    body_text: String(formData.get("body_text") ?? "") || undefined,
    publish_channel: String(formData.get("publish_channel") ?? "") || undefined,
    status: "draft"
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/assets`);
}

export async function createContentAssetFromDraftAction(projectId: string, companyId: number, draftId: number) {
  const draft = await getArticleDraft(projectId, String(draftId));
  const asset = await createContentAsset(projectId, {
    company_id: companyId,
    title: draft.title,
    content_type: draft.draft_type || "article",
    body_text: [draft.summary, draft.body_text].filter(Boolean).join("\n\n"),
    publish_channel: "AI 稿件入库",
    status: "approved"
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/assets`);
  revalidatePath(`/projects/${projectId}/drafts/${draftId}`);
  redirect(`/projects/${projectId}/assets?created_asset=${asset.id}`);
}

export async function reviewContentAssetAction(projectId: string, assetId: number) {
  await createContentAssetReview(projectId, assetId);
  revalidatePath(`/projects/${projectId}/assets`);
  revalidatePath("/reviews");
}

export async function bulkReviewContentAssetsAction(projectId: string) {
  const assets = await getContentAssets(projectId);
  const reviewedPairs = await Promise.all(
    assets.map(async (asset) => ({
      asset,
      reviews: await getContentAssetReviews(projectId, asset.id).catch(() => [])
    }))
  );
  const targets = reviewedPairs.filter((item) => item.reviews.length === 0).slice(0, 20);
  for (const item of targets) {
    await createContentAssetReview(projectId, item.asset.id);
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/assets`);
  revalidatePath("/reviews");
  redirect(`/projects/${projectId}/assets?bulk_scored=${targets.length}`);
}

export async function createContentAssetRemediationGoalsAction(projectId: string) {
  const goals = await createContentAssetRemediationGoals(projectId);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/assets`);
  redirect(`/projects/${projectId}/assets?remediation_goals=${goals.length}`);
}

export async function decideContentAssetReviewAction(
  projectId: string,
  assetId: number,
  decision: "approved" | "rejected",
  formData: FormData
) {
  await decideContentAssetReview(projectId, assetId, {
    decision,
    comment: String(formData.get("comment") ?? "") || undefined
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/assets`);
  revalidatePath("/reviews");
}

export async function bulkCreatePlacementsFromAssetsAction(projectId: string) {
  const assets = await getContentAssets(projectId);
  const reviewedPairs = await Promise.all(
    assets.map(async (asset) => ({
      asset,
      reviews: await getContentAssetReviews(projectId, asset.id).catch(() => [])
    }))
  );
  const targets = reviewedPairs
    .filter((item) => {
      const latestReview = item.reviews[0];
      return item.asset.status === "approved" || Number(latestReview?.total_score ?? 0) >= 85;
    })
    .slice(0, 20);
  for (const item of targets) {
    const latestReview = item.reviews[0];
    await createPlacement(projectId, {
      content_asset_id: item.asset.id,
      channel: item.asset.publish_channel || "内容资产投放",
      target_url: item.asset.source_url || undefined,
      status: "planned",
      notes: latestReview
        ? `内容资产评分 ${latestReview.total_score} ${latestReview.grade}，建议进入 GEO 投放计划。`
        : "已通过内容资产，建议进入 GEO 投放计划。"
    });
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/assets`);
  revalidatePath(`/projects/${projectId}/sources`);
  redirect(`/projects/${projectId}/sources?asset_placements=${targets.length}`);
}

export async function createPlacementAction(projectId: string, formData: FormData) {
  const contentAssetId = Number(formData.get("content_asset_id"));
  const articleDraftId = Number(formData.get("article_draft_id"));
  const placement = await createPlacement(projectId, {
    content_asset_id: Number.isFinite(contentAssetId) && contentAssetId > 0 ? contentAssetId : undefined,
    article_draft_id: Number.isFinite(articleDraftId) && articleDraftId > 0 ? articleDraftId : undefined,
    channel: String(formData.get("channel") ?? ""),
    target_url: String(formData.get("target_url") ?? "") || undefined,
    status: String(formData.get("status") ?? "planned"),
    notes: String(formData.get("notes") ?? "") || undefined
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/sources`);
  revalidatePath(`/projects/${projectId}/placements`);
  revalidatePath(`/projects/${projectId}/placements/${placement.id}/impact`);
  redirect(`/projects/${projectId}/placements/${placement.id}/impact`);
}

export async function updatePlacementStatusAction(projectId: string, placementId: number, status: string) {
  await updatePlacement(projectId, placementId, {
    status,
    published_at: status === "published" ? new Date().toISOString() : undefined,
    visibility: status === "published" ? "customer_visible" : "internal",
    delivery_status: status === "published" ? "ready" : "not_delivered"
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/sources`);
  revalidatePath(`/projects/${projectId}/placements`);
  revalidatePath(`/projects/${projectId}/calendar`);
  revalidatePath(`/projects/${projectId}/review-archive`);
  revalidatePath(`/projects/${projectId}/delivery-package`);
  revalidatePath(`/projects/${projectId}/placements/${placementId}/impact`);
  redirect(`/projects/${projectId}/placements/${placementId}/impact?placement_status=${status}#delivery-workflow`);
}

export async function updatePlacementArchiveAction(projectId: string, placementId: number, formData: FormData) {
  await updatePlacement(projectId, placementId, {
    archive_note: String(formData.get("archive_note") ?? "") || undefined,
    visibility: String(formData.get("visibility") ?? "internal"),
    delivery_status: String(formData.get("delivery_status") ?? "not_delivered")
  });
  revalidatePath(`/projects/${projectId}/review-archive`);
  revalidatePath(`/projects/${projectId}/placements/${placementId}/impact`);
  revalidatePath(`/projects/${projectId}/delivery-package`);
  redirect(`/projects/${projectId}/placements/${placementId}/impact?archive_saved=1#delivery-management`);
}

export async function generatePlacementReviewReportAction(projectId: string, placementId: number) {
  const impact = await getPlacementImpact(projectId, String(placementId));
  const date = new Date().toISOString().slice(0, 10);
  const report = await generateMaturityReport(projectId, {
    title: `投放复盘后 GEO 成熟度报告 - ${impact.placement.channel}`,
    report_period: `placement_review:${placementId}:${date}`
  });
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/reports/compare`);
  revalidatePath(`/projects/${projectId}/placements/${placementId}/impact`);
  redirect(`/projects/${projectId}/reports/compare?placement_report=${report.id}&placement_id=${placementId}`);
}

export async function createPlacementImpactActionGoalsAction(projectId: string, placementId: number) {
  const created = await createPlacementImpactActionGoals(projectId, String(placementId));
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/placements/${placementId}/impact`);
  if (created.length === 0) {
    redirect(`/projects/${projectId}/placements/${placementId}/impact?placement_impact_actions=existing#delivery-workflow`);
  }
  redirect(`/projects/${projectId}/placements/${placementId}/impact?placement_impact_actions=${created.length}#delivery-workflow`);
}

export async function createDeliveryShareAction(projectId: string, formData: FormData) {
  const share = await createDeliveryShare(projectId, {
    name: String(formData.get("name") ?? "客户交付包") || "客户交付包",
    expires_at: String(formData.get("expires_at") ?? "") || undefined
  });
  revalidatePath(`/projects/${projectId}/delivery-package`);
  redirect(`/projects/${projectId}/delivery-package?share=${share.token}`);
}

export async function revokeDeliveryShareAction(projectId: string, shareId: number) {
  await revokeDeliveryShare(projectId, shareId);
  revalidatePath(`/projects/${projectId}/delivery-package`);
  redirect(`/projects/${projectId}/delivery-package?revoked=${shareId}`);
}

export async function confirmPublicDeliveryAction(token: string, placementId: number, formData: FormData) {
  await confirmPublicDeliveryReport(token, placementId, {
    actor_name: String(formData.get("actor_name") ?? "") || undefined,
    comment: String(formData.get("comment") ?? "") || undefined
  });
  revalidatePath(`/share/delivery/${token}`);
  redirect(`/share/delivery/${token}?confirmed=${placementId}`);
}

export async function retryCrawlTaskAction(projectId: string, taskId: number) {
  await retryCrawlTask(projectId, taskId);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/tasks/${taskId}`);
  revalidatePath("/admin/queue");
  revalidatePath("/admin/alerts");
}
