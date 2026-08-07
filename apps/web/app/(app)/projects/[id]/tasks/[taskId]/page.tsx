import Link from "next/link";
import type { Route } from "next";
import { retryCrawlTaskAction } from "@/app/actions";
import {
  getCrawlResult,
  getCrawlResults,
  getCrawlTask,
  getCrawlTaskLogs,
  getKeywords,
  getLLMProviders,
  getProject,
  getTargetQuestions
} from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string; taskId: string }>;
};

function isProviderPreflightError(message?: string | null) {
  return Boolean(message?.includes("Provider preflight failed"));
}

function isBudgetGuardError(message?: string | null) {
  return Boolean(message?.includes("Budget guard blocked crawl"));
}

function numberDetail(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asRoute(value: string) {
  return value as Route;
}

export default async function CrawlTaskDetailPage({ params }: PageProps) {
  const { id, taskId } = await params;
  const [project, task, logs, providers, questions, keywords, results] = await Promise.all([
    getProject(id),
    getCrawlTask(id, taskId),
    getCrawlTaskLogs(id, taskId).catch(() => []),
    getLLMProviders().catch(() => []),
    getTargetQuestions(id).catch(() => []),
    getKeywords(id).catch(() => []),
    getCrawlResults(id, { taskId }).catch(() => [])
  ]);
  const resultDetails = await Promise.all(
    results.slice(0, 12).map((result) => getCrawlResult(id, String(result.id)).catch(() => null))
  );
  const validDetails = resultDetails.filter((result) => result !== null);
  const retryTask = retryCrawlTaskAction.bind(null, id, Number(taskId));
  const providerNameById = new Map(providers.map((provider) => [provider.id, provider.name]));
  const questionTextById = new Map(questions.map((question) => [question.id, question.question_text]));
  const keywordTextById = new Map(keywords.map((keyword) => [keyword.id, keyword.keyword]));
  const companyMentions = validDetails.filter((result) => result.analysis?.company_mentioned).length;
  const companyRecommendations = validDetails.filter((result) => result.analysis?.company_recommended).length;
  const citationSources = validDetails.flatMap((result) => result.citation_sources);
  const placedSources = citationSources.filter((source) => source.is_placed).length;
  const averageAiReadiness =
    citationSources.length > 0
      ? Math.round(citationSources.reduce((sum, source) => sum + source.ai_readiness_score, 0) / citationSources.length)
      : 0;
  const topSources = Array.from(
    citationSources.reduce((map, source) => {
      const key = source.source_domain || source.source_url || "unknown";
      const current = map.get(key) ?? { domain: key, count: 0, placed: 0, owned: 0 };
      current.count += 1;
      current.placed += source.is_placed ? 1 : 0;
      current.owned += source.is_owned ? 1 : 0;
      map.set(key, current);
      return map;
    }, new Map<string, { domain: string; count: number; placed: number; owned: number }>())
      .values()
  )
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);
  const providerPreflightError = isProviderPreflightError(task.error_message);
  const budgetGuardError = isBudgetGuardError(task.error_message);
  const budgetGuardLog = [...logs].reverse().find((log) => log.message === "Crawl blocked by budget guard");
  const budgetEstimatedCost = numberDetail(budgetGuardLog?.detail_json.estimated_cost);
  const budgetMaxCost = numberDetail(budgetGuardLog?.detail_json.max_estimated_cost);
  const budgetEstimatedTokens = numberDetail(budgetGuardLog?.detail_json.estimated_total_tokens);
  const budgetCallCount = numberDetail(budgetGuardLog?.detail_json.total_call_count);
  const budgetCurrency = String(budgetGuardLog?.detail_json.currency ?? "USD");
  const providerTestPrompt =
    task.target_question_ids.length > 0
      ? questionTextById.get(task.target_question_ids[0]) ?? "网络安全培训公司哪家好？"
      : task.keyword_ids.length > 0
        ? `${keywordTextById.get(task.keyword_ids[0]) ?? "GEO"} 相关服务商怎么选？`
        : questions[0]?.question_text ?? (keywords[0] ? `${keywords[0].keyword} 相关服务商怎么选？` : "网络安全培训公司哪家好？");
  const providerTestQuery = `prompt=${encodeURIComponent(providerTestPrompt)}&return_to=${encodeURIComponent(
    `/projects/${id}/tasks/${task.id}`
  )}`;
  const providerFixUrl =
    providerPreflightError && task.provider_ids.length === 1
      ? `/admin/providers/${task.provider_ids[0]}/test?${providerTestQuery}`
      : `/admin/providers`;
  const isPending = task.status === "pending";
  const workerCommand = "cd apps/api && UV_CACHE_DIR=/private/tmp/geo-uv-cache uv run python scripts/run_worker.py --once";

  return (
    <div className="stack">
      <div className="topbar" id="top">
        <div>
          <div className="eyebrow">采集任务</div>
          <h1>任务 #{task.id}</h1>
          <p className="subtle">{project.name}｜{task.task_type}｜{task.schedule_type}</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
        <form action={retryTask}>
          <button className="button" type="submit">
            重新执行
          </button>
        </form>
      </div>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>状态</span>
          <strong>{task.status}</strong>
        </div>
        <div className="panel metric">
          <span>模型数</span>
          <strong>{task.provider_ids.length}</strong>
        </div>
        <div className="panel metric">
          <span>错误</span>
          <strong>{task.error_message ? "有" : "无"}</strong>
        </div>
      </section>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>答案样本</span>
          <strong>{results.length}</strong>
        </div>
        <div className="panel metric">
          <span>企业提及</span>
          <strong>{companyMentions}</strong>
          <small>已解析 {validDetails.length} 条</small>
        </div>
        <div className="panel metric">
          <span>企业推荐</span>
          <strong>{companyRecommendations}</strong>
          <small>推荐率 {validDetails.length ? Math.round((companyRecommendations / validDetails.length) * 100) : 0}%</small>
        </div>
        <div className="panel metric">
          <span>信源健康</span>
          <strong>{averageAiReadiness || "-"}</strong>
          <small>已投放信源 {placedSources}</small>
        </div>
      </section>

      <section className="panel">
        <h2>采集范围</h2>
        <div className="grid cols-3">
          <div className="metric">
            <span>模型渠道</span>
            <strong>{task.provider_ids.length || "默认"}</strong>
            <small>
              {task.provider_ids.length > 0
                ? task.provider_ids.map((providerId) => providerNameById.get(providerId) ?? `#${providerId}`).join("、")
                : "后端默认渠道"}
            </small>
          </div>
          <div className="metric">
            <span>目标问题</span>
            <strong>{task.target_question_ids.length || "全部"}</strong>
            <small>
              {task.target_question_ids.length > 0
                ? task.target_question_ids.map((questionId) => questionTextById.get(questionId) ?? `#${questionId}`).join("、")
                : "全部目标问题"}
            </small>
          </div>
          <div className="metric">
            <span>关键词</span>
            <strong>{task.keyword_ids.length || "全部"}</strong>
            <small>
              {task.keyword_ids.length > 0
                ? task.keyword_ids.map((keywordId) => keywordTextById.get(keywordId) ?? `#${keywordId}`).join("、")
                : "全部关键词"}
            </small>
          </div>
        </div>
      </section>

      {isPending ? (
        <section className="panel">
          <div className="section-head">
            <div>
              <h2>任务已进入队列</h2>
              <p className="subtle">系统已经创建采集任务，正在等待 worker 拉取执行。执行后这里会显示答案样本、信源和日志。</p>
            </div>
            <Link className="button secondary" href={asRoute(`/projects/${id}/tasks/${task.id}`)}>
              刷新任务
            </Link>
          </div>
          <p className="subtle">本地开发环境可手动运行一次队列 worker：</p>
          <pre className="codeblock">{workerCommand}</pre>
        </section>
      ) : null}

      {task.error_message ? (
        <section className="panel">
          <div className="section-head">
            <div>
              <h2>{budgetGuardError ? "预算保护已生效" : "错误信息"}</h2>
              <p className="subtle">
                {budgetGuardError
                  ? "预计成本超过本次预算上限，系统已在真实模型调用前停止任务。"
                  : providerPreflightError
                    ? "模型渠道未通过预检，先补齐配置或测试通过后再重新执行。"
                    : "任务执行失败，请根据错误信息处理后重试。"}
              </p>
            </div>
            {providerPreflightError ? (
              <Link className="button" href={asRoute(providerFixUrl)}>
                {task.provider_ids.length === 1 ? "测试模型渠道" : "配置模型渠道"}
              </Link>
            ) : null}
            {budgetGuardError ? (
              <Link className="button secondary" href={asRoute(`/projects/${id}#top`)}>
                缩小范围或调高预算
              </Link>
            ) : null}
          </div>
          {budgetGuardError ? (
            <div className="notice warning">
              <strong>没有产生真实模型调用，也没有创建答案样本。</strong>
              <span>
                {budgetEstimatedCost !== null && budgetMaxCost !== null
                  ? `预计成本 ${budgetCurrency} ${budgetEstimatedCost}，预算上限 ${budgetCurrency} ${budgetMaxCost}。`
                  : "预算拦截发生在执行前。"}
              </span>
              {budgetEstimatedTokens !== null || budgetCallCount !== null ? (
                <span>
                  {budgetCallCount !== null ? `预计调用 ${budgetCallCount} 次` : ""}
                  {budgetCallCount !== null && budgetEstimatedTokens !== null ? "｜" : ""}
                  {budgetEstimatedTokens !== null ? `预计 ${budgetEstimatedTokens.toLocaleString("zh-CN")} tokens` : ""}
                </span>
              ) : null}
            </div>
          ) : null}
          <p className="subtle">{task.error_message}</p>
        </section>
      ) : null}

      <section className="grid cols-2">
        <div className="panel">
          <h2>本任务答案</h2>
          <div className="list">
            {results.length === 0 ? (
              <p className="subtle">这次任务还没有产出答案样本。</p>
            ) : (
              results.slice(0, 10).map((result) => (
                <Link className="row" href={`/projects/${id}/answers/${result.id}`} key={result.id}>
                  <div>
                    <h3>{result.prompt_text}</h3>
                    <small>{result.answer_summary ?? result.raw_answer.slice(0, 120)}</small>
                  </div>
                  <span className="tag">{result.status}</span>
                </Link>
              ))
            )}
          </div>
        </div>

        <div className="panel">
          <h2>本任务信源</h2>
          <div className="list">
            {topSources.length === 0 ? (
              <p className="subtle">暂未解析到信源。真实联网搜索或答案中包含 URL 时会在这里聚合。</p>
            ) : (
              topSources.map((source) => (
                <div className="row" key={source.domain}>
                  <div>
                    <h3>{source.domain}</h3>
                    <small>
                      出现 {source.count} 次｜已投放 {source.placed}｜自有 {source.owned}
                    </small>
                  </div>
                  <span className={source.placed > 0 ? "tag active" : "tag"}>{source.placed > 0 ? "placed" : "gap"}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>执行日志</h2>
        <div className="list">
          {logs.length === 0 ? (
            <p className="subtle">暂无日志。</p>
          ) : (
            logs.map((log) => (
              <div className="row" key={log.id}>
                <div>
                  <h3>{log.message}</h3>
                  <small>{log.created_at}</small>
                </div>
                <span className="tag">{log.level}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
