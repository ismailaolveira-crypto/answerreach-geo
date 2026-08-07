import Link from "next/link";
import type { Route } from "next";
import {
  bulkGenerateDraftsFromReportTopicsAction,
  createReportActionGoalsAction,
  generateDraftFromReportTopicAction
} from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import {
  getBrowserObservations,
  getMaturityReport,
  getMaturityReportMarkdownUrl,
  getMaturityReportPdfUrl,
  getProject,
  getProjectStageGoals
} from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string; reportId: string }>;
  searchParams: Promise<{
    report_actions?: string;
    action_error?: string;
    observation_bulk_created?: string;
    observation_bulk_sources?: string;
    observation_bulk_screenshots?: string;
  }>;
};

function asRoute(value: string) {
  return value as Route;
}

export default async function ReportDetailPage({ params, searchParams }: PageProps) {
  const { id, reportId } = await params;
  const queryParams = await searchParams;
  const [project, report, browserObservations, stageGoals] = await Promise.all([
    getProject(id),
    getMaturityReport(id, reportId),
    getBrowserObservations(id, 50).catch(() => []),
    getProjectStageGoals(id).catch(() => [])
  ]);
  const recommendations = report.report_json.recommendations ?? [];
  const topics = report.report_json.next_content_topics ?? [];
  const metrics = report.report_json.metrics ?? {};
  const evidenceQuality = report.report_json.evidence_quality;
  const evidenceSourceMix = report.report_json.evidence_source_mix;
  const taskScope = report.report_json.scope;
  const browserObservationCount = Number(
    evidenceQuality?.browser_observation_count ?? evidenceSourceMix?.browser_observation_count ?? 0
  );
  const screenshotEvidenceCount = Number(evidenceQuality?.screenshot_evidence_count ?? 0);
  const apiSampleCount = Number(
    evidenceQuality?.api_sample_count ?? evidenceSourceMix?.api_sample_count ?? metrics.total_answers ?? 0
  );
  const mockSampleCount = Number(evidenceQuality?.mock_sample_count ?? evidenceSourceMix?.mock_sample_count ?? 0);
  const realApiSampleCount = Number(evidenceQuality?.real_api_sample_count ?? Math.max(0, apiSampleCount - mockSampleCount));
  const actualAnswerCount = Number(taskScope?.actual_answer_count ?? metrics.total_answers ?? apiSampleCount);
  const realSampleRate = actualAnswerCount > 0 ? realApiSampleCount / actualAnswerCount : 0;
  const evidenceNeedsWebProof = browserObservationCount === 0 || screenshotEvidenceCount === 0;
  const providers = report.report_json.provider_breakdown ?? (report.report_json.providers ?? []).map((item) => ({
    provider_id: item.id,
    provider_name: item.name,
    provider_type: item.provider_type,
    answer_count: item.answer_count
  }));
  const sources = report.report_json.top_sources ?? [];
  const sourceGaps = report.report_json.source_gaps ?? [];
  const questionGaps = report.report_json.question_gaps ?? [];
  const keywordGaps = report.report_json.keyword_gaps ?? [];
  const coverage = report.report_json.coverage;
  const keywordPromptCoverage = report.report_json.keyword_prompt_coverage;
  const keywordPromptCoverageItems = keywordPromptCoverage?.items ?? [];
  const brandMatrix = report.report_json.brand_visibility_matrix;
  const taskCompetitors = report.report_json.competitors ?? [];
  const fallbackBrandSummary = [
    {
      name: report.report_json.company ?? project.name,
      brand_type: "company",
      answer_mentions: Number(metrics.company_mentions ?? 0),
      mention_count: Number(metrics.company_mentions ?? 0),
      recommendation_count: Number(metrics.company_recommendations ?? 0),
      avg_rank: metrics.avg_company_rank,
      provider_count: Number(metrics.company_mentions ?? 0) > 0 ? providers.length : 0
    },
    ...taskCompetitors.map((item) => ({ ...item, brand_type: "competitor", provider_count: providers.length }))
  ];
  const brandSummary = brandMatrix?.summary ?? (taskCompetitors.length > 0 ? fallbackBrandSummary : []);
  const brandByProvider = brandMatrix?.by_provider ?? [];
  const deliveryReadiness = report.report_json.delivery_readiness;
  const deliveryChecks = deliveryReadiness?.checks ?? [];
  const templateSnapshot = report.report_json.report_template_snapshot;
  const templateScoringDimensions = templateSnapshot?.scoring?.dimensions ?? [];
  const templateScoreAlignment = report.report_json.template_score_alignment;
  const unmatchedTemplateDimensions = templateScoreAlignment?.unmatched_template_dimensions ?? [];
  const reportGoalMarkers = [`report_id=${reportId}`, `report_observation_id=${reportId}`, `report_delivery_readiness_id=${reportId}`];
  const reportActionGoals = stageGoals.filter((goal) =>
    reportGoalMarkers.some((marker) => (goal.note ?? "").includes(marker))
  );
  const reportObservationId = Number(reportId);
  const observationTasks = [
    ...questionGaps.map((gap) => {
      const observations = browserObservations.filter(
        (item) =>
          (item.report_id === reportObservationId && item.target_question_id === gap.target_question_id) ||
          (item.target_question_id === gap.target_question_id && item.keyword_id == null)
      );
      return {
        key: `question-${gap.target_question_id}`,
        kind: "问题",
        prompt: gap.question_text,
        href: `/projects/${id}?observe_report_id=${reportId}&observe_question_id=${gap.target_question_id}&observe_prompt=${encodeURIComponent(
          gap.question_text
        )}#browser-observation`,
        observations
      };
    }),
    ...keywordGaps.map((gap) => {
      const prompt = `${gap.keyword} 相关服务商怎么选？`;
      const observations = browserObservations.filter(
        (item) => (item.report_id === reportObservationId && item.keyword_id === gap.keyword_id) || item.keyword_id === gap.keyword_id
      );
      return {
        key: `keyword-${gap.keyword_id}`,
        kind: "关键词",
        prompt,
        href: `/projects/${id}?observe_report_id=${reportId}&observe_keyword_id=${gap.keyword_id}&observe_prompt=${encodeURIComponent(
          prompt
        )}#browser-observation`,
        observations
      };
    })
  ].slice(0, 8);
  const completedObservationTasks = observationTasks.filter((item) => item.observations.length > 0);
  const createActionGoals = createReportActionGoalsAction.bind(null, id, reportId);
  const generateDraftFromReportTopic = generateDraftFromReportTopicAction.bind(null, id, reportId);
  const bulkGenerateDraftsFromReportTopics = bulkGenerateDraftsFromReportTopicsAction.bind(null, id, reportId);
  const primaryTopic =
    topics[0] ??
    questionGaps[0]?.question_text ??
    (keywordGaps[0] ? `${keywordGaps[0].keyword}怎么做 GEO 优化` : "");
  const batchTopics = [
    ...topics,
    ...questionGaps.map((gap) => gap.question_text),
    ...keywordGaps.map((gap) => `${gap.keyword}怎么做 GEO 优化`)
  ]
    .filter((topic, index, list) => topic && list.indexOf(topic) === index)
    .slice(0, 5);
  const reportActionResult = queryParams.report_actions ?? "";
  const reportActionCreatedCount = Number(reportActionResult);
  const observationBulkCreated = Number(queryParams.observation_bulk_created ?? 0);
  const observationBulkSourceCount = Number(queryParams.observation_bulk_sources ?? 0);
  const observationBulkScreenshotCount = Number(queryParams.observation_bulk_screenshots ?? 0);
  const reportActionFeedback =
    reportActionResult === "existing"
      ? "这份报告的行动项已经存在，可直接进入阶段目标继续处理。"
      : Number.isFinite(reportActionCreatedCount) && reportActionCreatedCount > 0
        ? `已从这份报告生成 ${reportActionCreatedCount} 个阶段目标。`
        : "";

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">成熟度报告</div>
          <h1>{report.title}</h1>
          <p className="subtle">{project.name}｜{report.summary}</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
        <Link className="button secondary" href={`/projects/${id}/reports/compare`}>
          报告对比
        </Link>
        {report.report_json.competitive_analysis_document ? (
          <Link className="button" href={`/projects/${id}/reports/${reportId}/competitive-analysis`}>
            竞品分析说明文档
          </Link>
        ) : null}
        <form action={createActionGoals}>
          <SubmitButton pendingText="生成中...">生成行动项</SubmitButton>
        </form>
        {primaryTopic ? (
          <form action={generateDraftFromReportTopic}>
            <input type="hidden" name="topic" value={primaryTopic} />
            <SubmitButton pendingText="生成并评分中...">生成首篇稿件并评分</SubmitButton>
          </form>
        ) : null}
        {batchTopics.length > 1 ? (
          <form action={bulkGenerateDraftsFromReportTopics}>
            {batchTopics.map((topic) => (
              <input key={topic} type="hidden" name="topics" value={topic} />
            ))}
            <SubmitButton className="button secondary" pendingText="批量生成中...">
              批量生成 {batchTopics.length} 篇并评分
            </SubmitButton>
          </form>
        ) : null}
        <a className="button" href={getMaturityReportMarkdownUrl(id, reportId)}>
          导出 Markdown
        </a>
        <a className="button" href={getMaturityReportPdfUrl(id, reportId)}>
          导出 PDF
        </a>
      </div>

      {queryParams.action_error ? (
        <div className="notice danger">
          操作没有完成：{queryParams.action_error}
        </div>
      ) : null}

      {observationBulkCreated > 0 ? (
        <div className="notice success">
          已基于 {observationBulkCreated} 条网页端观测生成本报告，识别信源 {observationBulkSourceCount} 条，截图证据{" "}
          {observationBulkScreenshotCount} 条。下一步可直接生成稿件并评分。
        </div>
      ) : null}

      {evidenceNeedsWebProof ? (
        <div className="notice warning">
          证据提示：这份报告当前包含 {realApiSampleCount} 条真实 API 样本、{browserObservationCount} 条网页端观测、
          {screenshotEvidenceCount} 条截图证据。它可以用于内部诊断和选题，但还不能作为豆包、DeepSeek、Kimi、千问网页端真实存证报告对外使用。
        </div>
      ) : (
        <div className="notice success">
          证据提示：这份报告已包含网页端观测和截图证据，可用于人工复核和客户解释。
        </div>
      )}

      <section className="grid cols-3">
        <div className="panel metric">
          <span>总分</span>
          <strong>{report.total_score}</strong>
        </div>
        <div className="panel metric">
          <span>成熟度等级</span>
          <strong>{report.maturity_level.split(" ")[0]}</strong>
        </div>
        <div className="panel metric">
          <span>报告状态</span>
          <strong>{report.status}</strong>
        </div>
      </section>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>报告模板</span>
          <strong>{templateSnapshot?.name ?? "默认模板"}</strong>
          <small>{templateSnapshot?.template_key ?? "legacy"}｜v{templateSnapshot?.version ?? 1}</small>
        </div>
        <div className="panel metric">
          <span>模板章节</span>
          <strong>{templateSnapshot?.sections?.length ?? 0}</strong>
          <small>生成时已固化快照</small>
        </div>
        <div className="panel metric">
          <span>模板检查</span>
          <strong>{templateSnapshot?.delivery_checks?.length ?? 0}</strong>
          <small>用于交付质量门槛</small>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>模板评分对齐</h2>
            <p className="subtle">记录生成报告时的模板评分维度，并对照本次实际评分明细，便于解释标准和后续调整模板。</p>
          </div>
          <span className={unmatchedTemplateDimensions.length === 0 ? "tag active" : "tag"}>
            {templateScoreAlignment
              ? `${templateScoreAlignment.matched_dimension_count}/${templateScoreAlignment.template_dimension_count}`
              : "未记录"}
          </span>
        </div>
        <div className="grid cols-3">
          <div className="metric">
            <span>模板维度</span>
            <strong>{templateScoreAlignment?.template_dimension_count ?? templateScoringDimensions.length}</strong>
            <small>模板定义的评分项</small>
          </div>
          <div className="metric">
            <span>实际评分</span>
            <strong>{templateScoreAlignment?.actual_dimension_count ?? report.score_items.length}</strong>
            <small>本报告落库评分项</small>
          </div>
          <div className="metric">
            <span>未匹配模板项</span>
            <strong>{unmatchedTemplateDimensions.length}</strong>
            <small>{unmatchedTemplateDimensions.length === 0 ? "评分维度已覆盖模板" : "建议检查模板或评分算法"}</small>
          </div>
        </div>
        {templateScoringDimensions.length > 0 ? (
          <div className="list compact">
            {templateScoringDimensions.map((dimension, index) => (
              <div className="row" key={`${dimension.key ?? dimension.name ?? index}`}>
                <div>
                  <h3>{dimension.name ?? dimension.key ?? "未命名维度"}</h3>
                  <small>{dimension.key ?? "custom"}｜满分 {dimension.max_score ?? "-"}</small>
                </div>
                <span
                  className={
                    unmatchedTemplateDimensions.some((item) => item.name === dimension.name || item.key === dimension.key)
                      ? "tag"
                      : "tag active"
                  }
                >
                  {unmatchedTemplateDimensions.some((item) => item.name === dimension.name || item.key === dimension.key)
                    ? "待对齐"
                    : "已对齐"}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="subtle">当前报告没有模板评分维度快照。</p>
        )}
      </section>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>样本可信度</span>
          <strong>{evidenceQuality?.sample_confidence_score ?? 0}</strong>
          <small>{evidenceQuality?.risk_level ?? "unknown"}</small>
        </div>
        <div className="panel metric">
          <span>模型覆盖</span>
          <strong>{metrics.provider_count ?? 0}</strong>
          <small>{providers.map((item) => item.provider_name).join("、") || "暂无"}</small>
        </div>
        <div className="panel metric">
          <span>平均推荐位</span>
          <strong>{metrics.avg_company_rank ?? "-"}</strong>
          <small>正向答案率 {Math.round(Number(metrics.positive_rate ?? 0) * 100)}%</small>
        </div>
      </section>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>真实 API 样本</span>
          <strong>{realApiSampleCount}</strong>
          <small>真实 Provider {evidenceQuality?.real_provider_count ?? providers.length}</small>
        </div>
        <div className="panel metric">
          <span>真实样本占比</span>
          <strong>{Math.round(Number(evidenceQuality?.real_sample_rate ?? realSampleRate) * 100)}%</strong>
          <small>正式报告优先提升该比例</small>
        </div>
        <div className="panel metric">
          <span>API 样本</span>
          <strong>{apiSampleCount}</strong>
          <small>适合高频持续采集</small>
        </div>
        <div className="panel metric">
          <span>Mock 样本</span>
          <strong>{mockSampleCount}</strong>
          <small>系统闭环演示，不替代正式实采</small>
        </div>
      </section>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>网页观测</span>
          <strong>{evidenceQuality?.browser_observation_count ?? 0}</strong>
          <small>校验真实产品页面</small>
        </div>
        <div className="panel metric">
          <span>截图证据</span>
          <strong>{evidenceQuality?.screenshot_evidence_count ?? 0}</strong>
          <small>用于人工复核和客户解释</small>
        </div>
        <div className="panel metric">
          <span>观测占比</span>
          <strong>{Math.round(Number(evidenceQuality?.browser_observation_rate ?? 0) * 100)}%</strong>
          <small>API 与网页端互相校验</small>
        </div>
        <div className="panel metric">
          <span>人工校正</span>
          <strong>{evidenceQuality?.manual_correction_count ?? 0}</strong>
          <small>占比 {Math.round(Number(evidenceQuality?.manual_correction_rate ?? 0) * 100)}%</small>
        </div>
      </section>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>覆盖状态</span>
          <strong>{coverage?.coverage_status ?? "unknown"}</strong>
          <small>样本 {coverage?.sample_size ?? metrics.total_answers ?? 0}</small>
        </div>
        <div className="panel metric">
          <span>问题覆盖</span>
          <strong>{Math.round(Number(coverage?.question_coverage_rate ?? metrics.question_coverage_rate ?? 0) * 100)}%</strong>
          <small>
            {coverage?.covered_question_count ?? metrics.covered_question_count ?? 0}/
            {coverage?.target_question_count ?? metrics.target_question_count ?? 0}
          </small>
        </div>
        <div className="panel metric">
          <span>关键词覆盖</span>
          <strong>{Math.round(Number(coverage?.keyword_coverage_rate ?? metrics.keyword_coverage_rate ?? 0) * 100)}%</strong>
          <small>
            {coverage?.covered_keyword_count ?? metrics.covered_keyword_count ?? 0}/
            {coverage?.keyword_count ?? metrics.keyword_count ?? 0}
          </small>
        </div>
        <div className="panel metric">
          <span>关键词语境</span>
          <strong>{Math.round(Number(coverage?.keyword_prompt_coverage_rate ?? keywordPromptCoverage?.coverage_rate ?? 0) * 100)}%</strong>
          <small>
            {coverage?.keyword_full_prompt_coverage_count ?? keywordPromptCoverage?.full_coverage_count ?? 0}/
            {coverage?.keyword_count ?? keywordPromptCoverage?.keyword_count ?? 0} 跑满{" "}
            {coverage?.keyword_prompt_variant_target ?? keywordPromptCoverage?.target_variant_count ?? 3} 个变体
          </small>
        </div>
        <div className="panel metric">
          <span>模型渠道</span>
          <strong>{coverage?.provider_count ?? metrics.provider_count ?? 0}</strong>
          <small>覆盖越多，研判越稳</small>
        </div>
      </section>

      {reportActionFeedback ? (
        <section className="panel notice">
          <div className="section-head">
            <div>
              <h2>行动项已同步</h2>
              <p className="subtle">{reportActionFeedback}</p>
            </div>
            <div className="row-actions">
              <Link className="button secondary" href={`/projects/${id}#stage-goals`}>
                查看阶段目标
              </Link>
              {batchTopics.length > 1 ? (
                <form action={bulkGenerateDraftsFromReportTopics}>
                  {batchTopics.map((topic) => (
                    <input key={topic} type="hidden" name="topics" value={topic} />
                  ))}
                  <SubmitButton pendingText="批量生成中...">批量生成稿件并评分</SubmitButton>
                </form>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      <section className="panel" id="report-actions">
        <div className="section-head">
          <div>
            <h2>关键词语境覆盖</h2>
            <p className="subtle">每个关键词会扩展为多个采购、对比和服务商选择语境；跑满语境后，报告对关键词表现的判断更稳。</p>
          </div>
          <span className="tag">
            平均 {keywordPromptCoverage?.avg_prompt_variants_per_keyword ?? coverage?.avg_prompt_variants_per_keyword ?? 0} 个变体
          </span>
        </div>
        <div className="list">
          {keywordPromptCoverageItems.length === 0 ? (
            <p className="subtle">暂无关键词语境样本。先补跑关键词采集后再生成报告。</p>
          ) : (
            keywordPromptCoverageItems.slice(0, 8).map((item) => (
              <div className="row" key={item.keyword_id}>
                <div>
                  <h3>{item.keyword}</h3>
                  <small>
                    变体 {item.prompt_variant_count}/{item.target_variant_count}｜模型 {item.provider_count}｜结果 {item.result_count}
                  </small>
                  {item.sample_prompts.length > 0 ? (
                    <div className="mini-list">
                      {item.sample_prompts.slice(0, 3).map((prompt) => (
                        <small key={`${item.keyword_id}-${prompt}`}>- {prompt}</small>
                      ))}
                    </div>
                  ) : null}
                </div>
                <span className={item.coverage_status === "complete" ? "tag active" : "tag"}>
                  {item.coverage_status === "complete" ? "完整" : item.coverage_status === "partial" ? "部分" : "缺失"}
                </span>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>交付就绪度</h2>
            <p className="subtle">{deliveryReadiness?.summary ?? "暂无交付质量检查结果。"}</p>
          </div>
          <span className="tag">{deliveryReadiness?.status ?? "unknown"}</span>
        </div>
        <section className="grid cols-3">
          <div className="metric">
            <span>就绪得分</span>
            <strong>{deliveryReadiness?.score ?? 0}</strong>
            <small>满分 100</small>
          </div>
          <div className="metric">
            <span>阻塞项</span>
            <strong>{deliveryReadiness?.blocker_count ?? 0}</strong>
            <small>建议清零后发客户</small>
          </div>
          <div className="metric">
            <span>待补动作</span>
            <strong>{deliveryReadiness?.missing_actions?.length ?? 0}</strong>
            <small>可转为阶段目标或采集任务</small>
          </div>
        </section>
        <div className="list">
          {deliveryChecks.length === 0 ? (
            <p className="subtle">暂无质量检查项。</p>
          ) : (
            deliveryChecks.map((check) => (
              <div className="row" key={check.key}>
                <div>
                  <h3>{check.label}</h3>
                  <small>
                    当前 {check.current} / 要求 {check.required}｜权重 {check.weight}｜{check.fix}
                  </small>
                </div>
                <span className="tag">{check.ok ? "通过" : "待补"}</span>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>报告行动追踪</h2>
            <p className="subtle">展示这份报告已经转成哪些阶段目标，以及每个目标的执行进度、风险和下一步动作。</p>
          </div>
          <div className="row-actions">
            <span className={reportActionGoals.length > 0 ? "tag active" : "tag"}>
              {reportActionGoals.length > 0 ? `${reportActionGoals.length} 个目标` : "未生成"}
            </span>
            <Link className="button secondary" href={`/projects/${id}#stage-goals`}>
              查看阶段目标
            </Link>
          </div>
        </div>
        {reportActionGoals.length === 0 ? (
          <div className="row review-row">
            <div>
              <h3>尚未生成报告行动项</h3>
              <small>点击页面顶部“生成行动项”，系统会把推荐选题、采集缺口、网页观测和交付质量门槛转成可执行阶段目标。</small>
            </div>
            <form action={createActionGoals}>
              <SubmitButton pendingText="生成中...">生成行动项</SubmitButton>
            </form>
          </div>
        ) : (
          <div className="list">
            {reportActionGoals.map((goal) => (
              <div className="row review-row" key={goal.id}>
                <div>
                  <div className="meta-line">
                    <span>{goal.metric_key}</span>
                    <span>{goal.status}</span>
                    <span>{goal.risk_level}</span>
                    {goal.owner ? <span>{goal.owner}</span> : null}
                    {goal.due_at ? <span>截止 {goal.due_at.slice(0, 10)}</span> : null}
                  </div>
                  <h3>{goal.title}</h3>
                  <small>
                    当前 {goal.current_value} / 目标 {goal.target_value}，完成 {Math.round(goal.progress_rate * 100)}%，还差 {goal.remaining_value}
                  </small>
                  <div className="scorebar wide">
                    <span style={{ width: `${Math.round(goal.progress_rate * 100)}%` }} />
                  </div>
                  {goal.review_summary ? <small>{goal.review_summary}</small> : null}
                  {goal.suggested_actions.length > 0 ? (
                    <div className="mini-list">
                      <small>
                        <strong>下一步动作</strong>
                      </small>
                      {goal.suggested_actions.slice(0, 3).map((action) => (
                        <small key={`${goal.id}-${action.action_type}`}>
                          - {action.label || action.action_type}：{action.reason}
                        </small>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div className="row-actions">
                  <span className={goal.progress_rate >= 1 ? "tag active" : "tag"}>
                    {goal.progress_rate >= 1 ? "完成" : "推进中"}
                  </span>
                  <Link className="button secondary" href={`/projects/${id}#stage-goals`}>
                    处理
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>品牌推荐矩阵</h2>
            <p className="subtle">按答案解析和实体推荐位聚合，用来判断企业在不同模型中的客观可见度和竞品压力。</p>
          </div>
          <span className="tag">竞品 {brandMatrix?.competitor_count ?? taskCompetitors.length}</span>
        </div>
        <section className="grid cols-3">
          <div className="metric">
            <span>当前领先品牌</span>
            <strong>{brandMatrix?.leader_name ?? taskCompetitors[0]?.name ?? "暂无"}</strong>
            <small>按推荐、提及和推荐位综合排序</small>
          </div>
          <div className="metric">
            <span>企业位置</span>
            <strong>{brandMatrix?.company_position ? `第 ${brandMatrix.company_position}` : "暂无"}</strong>
            <small>{brandMatrix?.company_name ?? project.name}</small>
          </div>
          <div className="metric">
            <span>企业推荐</span>
            <strong>{brandMatrix?.company?.recommendation_count ?? metrics.company_recommendations ?? 0}</strong>
            <small>覆盖模型 {brandMatrix?.company?.provider_count ?? providers.length}</small>
          </div>
        </section>
        <div className="list">
          {brandSummary.length === 0 ? (
            <p className="subtle">暂无品牌矩阵数据。可先补充答案解析或采集样本。</p>
          ) : (
            brandSummary.slice(0, 8).map((brand) => (
              <div className="row" key={`${brand.brand_type}-${brand.name}`}>
                <div>
                  <h3>{brand.name}</h3>
                  <small>
                    提及 {brand.mention_count} 次｜推荐 {brand.recommendation_count} 次｜覆盖模型 {brand.provider_count}｜
                    平均推荐位 {brand.avg_rank ?? "暂无"}
                  </small>
                </div>
                <span className="tag">{brand.brand_type === "company" ? "本企业" : brand.brand_type === "competitor" ? "竞品" : "其他"}</span>
              </div>
            ))
          )}
        </div>
        {brandByProvider.length > 0 ? (
          <div className="grid cols-2">
            {brandByProvider.slice(0, 6).map((provider) => (
              <div className="subpanel" key={`${provider.provider_id}-${provider.provider_name}`}>
                <div className="section-head">
                  <div>
                    <h3>{provider.provider_name}</h3>
                    <small>
                      样本 {provider.answer_count}｜企业推荐率 {Math.round(provider.company_recommendation_rate * 100)}%｜
                      平均推荐位 {provider.company_avg_rank ?? "暂无"}
                    </small>
                  </div>
                  <span className="tag">{provider.provider_type ?? "unknown"}</span>
                </div>
                <div className="list compact">
                  {provider.top_entities.length === 0 ? (
                    <p className="subtle">暂无实体推荐数据。</p>
                  ) : (
                    provider.top_entities.slice(0, 4).map((entity) => (
                      <div className="row" key={`${provider.provider_id}-${entity.name}`}>
                        <div>
                          <h3>{entity.name}</h3>
                          <small>
                            提及 {entity.mention_count}｜推荐 {entity.recommendation_count}｜均位 {entity.avg_rank ?? "暂无"}
                          </small>
                        </div>
                        <span className="tag">{entity.brand_type}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="panel">
        <h2>评分明细</h2>
        <div className="list">
          {report.score_items.map((item) => (
            <div className="row" key={item.id}>
              <div>
                <h3>{item.dimension}</h3>
                <small>{item.explanation}</small>
              </div>
              <div className="scorebar" aria-label={`${item.score}/${item.max_score}`}>
                <span style={{ width: `${Math.round((item.score / item.max_score) * 100)}%` }} />
              </div>
              <span className="tag">
                {item.score}/{item.max_score}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>高频信源</h2>
          <div className="list">
            {sources.length === 0 ? (
              <p className="subtle">暂无信源数据。</p>
            ) : (
              sources.map((source) => (
                <div className="row" key={`${source.domain}-${source.url}`}>
                  <div>
                    <h3>{source.domain || source.url || "未知信源"}</h3>
                    <small>
                      出现 {source.mentions} 次｜AI 适配分 {source.ai_readiness_score}
                    </small>
                  </div>
                  <span className="tag">
                    {source.is_owned ? "自有" : source.is_placed ? "已投放" : "待建设"}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="panel">
          <h2>缺口清单</h2>
          <div className="list">
            {sourceGaps.length === 0 && questionGaps.length === 0 && keywordGaps.length === 0 ? (
              <p className="subtle">暂无明显缺口。</p>
            ) : (
              <>
                {sourceGaps.map((gap) => (
                  <div className="row" key={`${gap.domain}-${gap.url}`}>
                    <div>
                      <h3>{gap.domain || gap.url || "未知信源"}</h3>
                      <small>{gap.reason}</small>
                    </div>
                    <span className="tag">信源</span>
                  </div>
                ))}
                {questionGaps.map((gap) => (
                  <div className="row" key={gap.target_question_id}>
                    <div>
                      <h3>{gap.question_text}</h3>
                      <small>目标问题尚未形成采集样本。</small>
                    </div>
                    <span className="tag">问题</span>
                  </div>
                ))}
                {keywordGaps.map((gap) => (
                  <div className="row" key={gap.keyword_id}>
                    <div>
                      <h3>{gap.keyword}</h3>
                      <small>关键词尚未形成采集样本。</small>
                    </div>
                    <span className="tag">关键词</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>下一轮网页观测建议</h2>
            <p className="subtle">优先把未覆盖的问题和关键词拿到网页端大模型中抽样搜索；点击生成行动项会同步创建网页观测阶段目标。</p>
          </div>
          <span className="tag">
            已完成 {completedObservationTasks.length}/{observationTasks.length}
          </span>
          <Link className="button secondary" href={`/projects/${id}#browser-observation`}>
            回项目入库
          </Link>
        </div>
        {observationTasks.length > 0 ? (
          <div className="grid cols-3">
            <div className="metric">
              <span>观测任务</span>
              <strong>{observationTasks.length}</strong>
              <small>来自本报告缺口</small>
            </div>
            <div className="metric">
              <span>已入库</span>
              <strong>{completedObservationTasks.length}</strong>
              <small>按报告、问题或关键词匹配</small>
            </div>
            <div className="metric">
              <span>截图证据</span>
              <strong>
                {completedObservationTasks.reduce(
                  (sum, task) => sum + task.observations.reduce((inner, item) => inner + item.screenshot_evidence_count, 0),
                  0
                )}
              </strong>
              <small>用于人工核验</small>
            </div>
          </div>
        ) : null}
        <div className="list">
          {observationTasks.length === 0 ? (
            <p className="subtle">当前报告没有明显的问题或关键词缺口，可从高价值业务问题中抽样做网页端复核。</p>
          ) : (
            observationTasks.map((task) => (
              <div className="row" key={task.key}>
                <div>
                  <h3>{task.prompt}</h3>
                  <small>
                    {task.kind}缺口｜{task.observations.length > 0 ? `已入库 ${task.observations.length} 条观测` : "待观测"}｜
                    建议在豆包、DeepSeek、元宝、Kimi 等网页端抽样，并保留截图或录屏。
                  </small>
                </div>
                {task.observations.length > 0 ? (
                  <Link className="button secondary" href={`/projects/${id}/answers/${task.observations[0].id}`}>
                    查看证据
                  </Link>
                ) : (
                  <Link className="button secondary" href={asRoute(task.href)}>
                    去入库
                  </Link>
                )}
                <span className="tag">{task.observations.length > 0 ? "已留证" : "待观测"}</span>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>优化建议</h2>
          <div className="list">
            {recommendations.map((item) => (
              <div className="row" key={item}>
                <h3>{item}</h3>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <h2>推荐选题</h2>
          <div className="list">
            {topics.length === 0 ? (
              <p className="subtle">暂无推荐选题。可先补充采集样本或生成行动项。</p>
            ) : (
              topics.map((item) => (
                <div className="row" key={item}>
                  <div>
                    <h3>{item}</h3>
                    <small>基于报告缺口生成稿件，并立即进入 AI 审核评分。</small>
                  </div>
                  <form action={generateDraftFromReportTopic}>
                    <input type="hidden" name="topic" value={item} />
                    <SubmitButton className="button secondary" pendingText="生成并评分中...">生成并评分</SubmitButton>
                  </form>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
