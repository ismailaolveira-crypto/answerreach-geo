import Link from "next/link";
import type { Route } from "next";
import {
  getCrawlResult,
  getCrawlResults,
  getCrawlTasks,
  getKeywords,
  getLLMProviders,
  getProject,
  getSearchMetrics,
  getTargetQuestions
} from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
};

function asRoute(value: string) {
  return value as Route;
}

function pct(value?: number | null) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

export default async function ProjectAnswersPage({ params }: PageProps) {
  const { id } = await params;
  const [project, results, metrics, tasks, providers, questions, keywords] = await Promise.all([
    getProject(id),
    getCrawlResults(id).catch(() => []),
    getSearchMetrics(id).catch(() => null),
    getCrawlTasks(id).catch(() => []),
    getLLMProviders().catch(() => []),
    getTargetQuestions(id).catch(() => []),
    getKeywords(id).catch(() => [])
  ]);
  const detailItems = await Promise.all(
    results.slice(0, 30).map((result) => getCrawlResult(id, String(result.id)).catch(() => null))
  );
  const details = detailItems.filter((item) => item !== null);
  const providerNameById = new Map(providers.map((provider) => [provider.id, provider.name]));
  const questionTextById = new Map(questions.map((question) => [question.id, question.question_text]));
  const keywordTextById = new Map(keywords.map((keyword) => [keyword.id, keyword.keyword]));
  const taskById = new Map(tasks.map((task) => [task.id, task]));
  const mentionedCount = details.filter((item) => item.analysis?.company_mentioned).length;
  const recommendedCount = details.filter((item) => item.analysis?.company_recommended).length;
  const sourceCount = details.reduce((sum, item) => sum + item.citation_sources.length, 0);
  const placedSourceCount = details.reduce(
    (sum, item) => sum + item.citation_sources.filter((source) => source.is_placed).length,
    0
  );
  const latestTask = tasks[0];

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">搜索监测结果</div>
          <h1>{project.name} AI 答案</h1>
          <p className="subtle">集中查看不同模型下的答案样本、企业提及推荐、采集任务和信源线索。</p>
        </div>
        <Link className="button secondary" href={asRoute(`/projects/${id}`)}>
          返回项目
        </Link>
        {latestTask ? (
          <Link className="button secondary" href={asRoute(`/projects/${id}/tasks/${latestTask.id}`)}>
            最新任务
          </Link>
        ) : null}
        <Link className="button secondary" href={asRoute(`/projects/${id}/sources`)}>
          信源分析
        </Link>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>答案样本</span>
          <strong>{metrics?.total_answers ?? results.length}</strong>
        </div>
        <div className="panel metric">
          <span>企业提及率</span>
          <strong>{pct(metrics?.company_mention_rate)}</strong>
          <small>近 {details.length} 条明细命中 {mentionedCount}</small>
        </div>
        <div className="panel metric">
          <span>企业推荐率</span>
          <strong>{pct(metrics?.company_recommendation_rate)}</strong>
          <small>近 {details.length} 条明细推荐 {recommendedCount}</small>
        </div>
        <div className="panel metric">
          <span>信源线索</span>
          <strong>{sourceCount}</strong>
          <small>已投放 {placedSourceCount}</small>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>答案样本</h2>
            <p className="subtle">展示最近 30 条结果的解析状态。进入详情可人工校正提及、推荐、推荐位和置信度。</p>
          </div>
          <span className="tag">{results.length} 条</span>
        </div>
        <div className="list">
          {details.length === 0 ? (
            <p className="subtle">暂无答案样本。先发起搜索采集或执行到期监测计划。</p>
          ) : (
            details.map((result) => {
              const task = taskById.get(result.task_id);
              const linkedSource =
                (result.target_question_id ? `目标问题：${questionTextById.get(result.target_question_id) ?? result.target_question_id}` : null) ??
                (result.keyword_id ? `关键词：${keywordTextById.get(result.keyword_id) ?? result.keyword_id}` : null) ??
                "未关联配置";
              return (
                <div className="row" key={result.id}>
                  <div>
                    <div className="meta-line">
                      <span className={result.analysis?.company_mentioned ? "tag active" : "tag"}>
                        {result.analysis?.company_mentioned ? "提及企业" : "未提及"}
                      </span>
                      <span className={result.analysis?.company_recommended ? "tag active" : "tag"}>
                        {result.analysis?.company_recommended ? "推荐企业" : "未推荐"}
                      </span>
                      <span>{providerNameById.get(result.provider_id ?? 0) ?? `Provider #${result.provider_id ?? "-"}`}</span>
                      <span>{result.collected_at ? result.collected_at.slice(0, 10) : "未记录时间"}</span>
                    </div>
                    <Link href={asRoute(`/projects/${id}/answers/${result.id}`)}>
                      <h3>{result.prompt_text}</h3>
                    </Link>
                    <small>
                      {linkedSource}｜
                      任务 #{result.task_id}
                      {task ? `｜${task.task_type}｜${task.status}` : ""}｜
                      信源 {result.citation_sources.length}｜
                      实体 {result.mentioned_entities.length}｜
                      置信度 {Math.round(result.analysis?.confidence ?? 0)}%
                    </small>
                    <small>{result.answer_summary ?? result.raw_answer.slice(0, 120)}</small>
                  </div>
                  <div className="row-actions">
                    <Link className="button secondary" href={asRoute(`/projects/${id}/answers/${result.id}`)}>
                      详情校正
                    </Link>
                    <Link className="button secondary" href={asRoute(`/projects/${id}/tasks/${result.task_id}`)}>
                      任务
                    </Link>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
