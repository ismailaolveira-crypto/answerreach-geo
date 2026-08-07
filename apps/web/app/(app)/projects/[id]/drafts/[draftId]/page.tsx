import Link from "next/link";
import {
  approveDraftAndCreatePlacementAction,
  createContentAssetFromDraftAction,
  createPlacementAction,
  decideDraftReviewAction,
  reviseDraftFromReviewAction,
  reviewDraftAction
} from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getArticleDraft, getArticleReviews, getContentAssets, getPlacements, getProject } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string; draftId: string }>;
  searchParams: Promise<{
    reviewed?: string;
    decision?: string;
    action_error?: string;
    observation_bulk_created?: string;
    report_id?: string;
  }>;
};

export default async function DraftDetailPage({ params, searchParams }: PageProps) {
  const { id, draftId } = await params;
  const queryParams = await searchParams;
  const [projectResult, draftResult] = await Promise.allSettled([getProject(id), getArticleDraft(id, draftId)]);
  const project = projectResult.status === "fulfilled" ? projectResult.value : null;
  const draft = draftResult.status === "fulfilled" ? draftResult.value : null;

  if (!project || !draft) {
    const projectError =
      projectResult.status === "rejected"
        ? projectResult.reason instanceof Error
          ? projectResult.reason.message
          : String(projectResult.reason)
        : "";
    const draftError =
      draftResult.status === "rejected"
        ? draftResult.reason instanceof Error
          ? draftResult.reason.message
          : String(draftResult.reason)
        : "";
    const errorText = [projectError, draftError].filter(Boolean).join("；") || "稿件详情暂时无法加载。";
    return (
      <div className="stack">
        <div className="topbar">
          <div>
            <div className="eyebrow">稿件详情</div>
            <h1>稿件暂时打不开</h1>
            <p className="subtle">项目 #{id}｜稿件 #{draftId}</p>
          </div>
          <Link className="button secondary" href={`/projects/${id}`}>
            返回项目
          </Link>
          <Link className="button secondary" href={`/projects/${id}/drafts`}>
            返回稿件工作台
          </Link>
        </div>
        <div className="notice danger">
          {errorText.replace(/^API request failed:\s*/i, "")}
        </div>
      </div>
    );
  }
  const [reviewResult, assetResult, placementResult] = await Promise.allSettled([
    getArticleReviews(id, Number(draftId)),
    getContentAssets(id),
    getPlacements(id)
  ]);
  const reviews = reviewResult.status === "fulfilled" ? reviewResult.value : [];
  const assets = assetResult.status === "fulfilled" ? assetResult.value : [];
  const placements = placementResult.status === "fulfilled" ? placementResult.value : [];
  const auxiliaryLoadFailed =
    reviewResult.status === "rejected" ||
    assetResult.status === "rejected" ||
    placementResult.status === "rejected";
  const latestReview = reviews[0];
  const reviewRuleSnapshot = latestReview?.review_rule_snapshot;
  const reviewRules = Array.isArray(reviewRuleSnapshot?.rules) ? reviewRuleSnapshot.rules : [];
  const reportAlignment = reviewRuleSnapshot?.report_alignment;
  const reviewDraft = reviewDraftAction.bind(null, id, Number(draftId));
  const reviseDraft = reviseDraftFromReviewAction.bind(null, id, Number(draftId));
  const approveDraft = decideDraftReviewAction.bind(null, id, Number(draftId), "approved");
  const rejectDraft = decideDraftReviewAction.bind(null, id, Number(draftId), "rejected");
  const approveAndCreatePlacement = approveDraftAndCreatePlacementAction.bind(null, id, Number(draftId));
  const createPlacement = createPlacementAction.bind(null, id);
  const createAssetFromDraft = createContentAssetFromDraftAction.bind(null, id, project.company_id, Number(draftId));
  const placementSuggestion = latestReview?.suggestions_json.find((item) => item.type === "placement_source");
  const sourceContext = draft.source_context ?? {};
  const sourceReportId = typeof sourceContext.source_report_id === "number" ? sourceContext.source_report_id : null;
  const stageGoalId = typeof sourceContext.stage_goal_id === "number" ? sourceContext.stage_goal_id : null;
  const suggestedPlacementSources = Array.isArray(sourceContext.suggested_placement_sources)
    ? sourceContext.suggested_placement_sources.map((item) => String(item)).filter(Boolean)
    : [];
  const coveredQuestionGaps = Array.isArray(sourceContext.covered_question_gaps)
    ? sourceContext.covered_question_gaps.map((item) => String(item)).filter(Boolean)
    : [];
  const coveredKeywordGaps = Array.isArray(sourceContext.covered_keyword_gaps)
    ? sourceContext.covered_keyword_gaps.map((item) => String(item)).filter(Boolean)
    : [];
  const keywordPromptSamples = Array.isArray(sourceContext.keyword_prompt_samples)
    ? sourceContext.keyword_prompt_samples.map((item) => String(item)).filter(Boolean)
    : [];
  const geoNextSteps =
    typeof sourceContext.geo_next_steps === "object" && sourceContext.geo_next_steps !== null
      ? (sourceContext.geo_next_steps as Record<string, unknown>)
      : {};
  const geoQuestionGaps = Array.isArray(geoNextSteps.question_gaps)
    ? geoNextSteps.question_gaps.map((item) => String(item)).filter(Boolean)
    : [];
  const geoKeywordGaps = Array.isArray(geoNextSteps.keyword_gaps)
    ? geoNextSteps.keyword_gaps.map((item) => String(item)).filter(Boolean)
    : [];
  const geoPromptSamples = Array.isArray(geoNextSteps.keyword_prompt_samples)
    ? geoNextSteps.keyword_prompt_samples.map((item) => String(item)).filter(Boolean)
    : [];
  const geoSourceSuggestions = Array.isArray(geoNextSteps.source_suggestions)
    ? geoNextSteps.source_suggestions.map((item) => String(item)).filter(Boolean)
    : [];
  const geoEvidenceSuggestions = Array.isArray(geoNextSteps.evidence_suggestions)
    ? geoNextSteps.evidence_suggestions.map((item) => String(item)).filter(Boolean)
    : [];
  const coveredKeywordPrompts = Array.isArray(sourceContext.covered_keyword_prompts)
    ? sourceContext.covered_keyword_prompts.map((item) => String(item)).filter(Boolean)
    : [];
  const linkedAssets = assets.filter(
    (asset) =>
      asset.title === draft.title &&
      (asset.publish_channel === "AI 稿件入库" || draft.content_asset_id === asset.id)
  );
  const linkedPlacements = placements.filter((placement) => placement.article_draft_id === draft.id);
  const workflowSteps = [
    {
      title: "AI 审核评分",
      done: Boolean(latestReview),
      detail: latestReview ? `${latestReview.total_score} 分 ${latestReview.grade}` : "先生成审核评分"
    },
    {
      title: "人工审核",
      done: draft.status === "approved",
      detail: draft.status === "approved" ? "已通过" : draft.status === "rejected" ? "已退回" : "待人工确认"
    },
    {
      title: "内容资产入库",
      done: linkedAssets.length > 0,
      detail: linkedAssets.length > 0 ? `已入库 ${linkedAssets.length} 条` : "审核通过后可入库"
    },
    {
      title: "投放计划",
      done: linkedPlacements.length > 0,
      detail:
        linkedPlacements.length > 0
          ? `${linkedPlacements[0].status}｜${linkedPlacements[0].channel}`
          : "审核通过后可加入投放"
    }
  ];

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">稿件详情</div>
          <h1>{draft.title}</h1>
          <p className="subtle">{project.name}｜{draft.summary}</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
        <form action={reviewDraft}>
          <SubmitButton pendingText="审核中...">审核打分</SubmitButton>
        </form>
      </div>

      {queryParams.reviewed ? (
        <div className="notice success">
          已生成审核评分 #{queryParams.reviewed}，可继续人工审核、生成优化版或加入投放。
        </div>
      ) : null}

      {queryParams.observation_bulk_created ? (
        <div className="notice success">
          已完成 {queryParams.observation_bulk_created} 条网页端观测入库、生成报告
          {queryParams.report_id ? ` #${queryParams.report_id}` : ""}，并基于报告生成本稿件和 AI 评分。
        </div>
      ) : null}

      {queryParams.decision ? (
        <div className={queryParams.decision === "approved" ? "notice success" : "notice warning"}>
          人工审核已{queryParams.decision === "approved" ? "通过" : "退回"}，当前稿件状态为 {draft.status}。
        </div>
      ) : null}

      {queryParams.action_error ? (
        <div className="notice danger">
          操作没有完成：{queryParams.action_error}
        </div>
      ) : null}

      {auxiliaryLoadFailed ? (
        <div className="notice warning">
          稿件正文已打开，但审核记录、内容资产或投放记录有一部分暂时没有加载成功。可以先继续查看正文，稍后刷新重试。
        </div>
      ) : null}

      {latestReview ? (
        <section className="grid cols-3">
          <div className="panel metric">
            <span>审核总分</span>
            <strong>{latestReview.total_score}</strong>
          </div>
          <div className="panel metric">
            <span>评级</span>
            <strong>{latestReview.grade}</strong>
          </div>
          <div className="panel metric">
            <span>风险表达</span>
            <strong>{latestReview.risk_expressions.length}</strong>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>稿件闭环进度</h2>
            <p className="subtle">从报告选题生成稿件后，依次完成 AI 评分、人工审核、内容资产沉淀和投放计划。</p>
          </div>
          <span className={workflowSteps.every((step) => step.done) ? "tag active" : "tag"}>
            {workflowSteps.filter((step) => step.done).length}/{workflowSteps.length}
          </span>
        </div>
        <div className="grid cols-4">
          {workflowSteps.map((step) => (
            <div className="metric" key={step.title}>
              <span>{step.title}</span>
              <strong>{step.done ? "完成" : "待办"}</strong>
              <small>{step.detail}</small>
            </div>
          ))}
        </div>
        <div className="row-actions">
          {!latestReview ? (
            <form action={reviewDraft}>
              <SubmitButton className="button secondary" pendingText="评分中...">
                生成 AI 评分
              </SubmitButton>
            </form>
          ) : null}
          {latestReview ? (
            <form action={reviseDraft}>
              <SubmitButton className="button secondary" pendingText="生成优化版...">
                生成优化版并复评
              </SubmitButton>
            </form>
          ) : null}
          {latestReview && draft.status !== "approved" ? <span className="tag">下一步：人工审核</span> : null}
          {draft.status === "approved" && linkedAssets.length === 0 ? <span className="tag">下一步：内容入库</span> : null}
          {draft.status === "approved" && linkedPlacements.length === 0 ? <span className="tag">下一步：加入投放</span> : null}
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>来源与承接</h2>
            <p className="subtle">记录这篇稿件的报告来源和选题来源，正文与运营建议分开管理。</p>
          </div>
          <span className={sourceReportId || stageGoalId ? "tag active" : "tag"}>
            {String(sourceContext.source_type ?? "manual_or_project")}
          </span>
        </div>
        <div className="grid cols-4">
          <div className="metric">
            <span>选题来源</span>
            <strong>{String(sourceContext.topic_source ?? "project_keywords")}</strong>
            <small>{String(sourceContext.topic ?? draft.title)}</small>
          </div>
          <div className="metric">
            <span>成熟度报告</span>
            <strong>{sourceReportId ? `#${sourceReportId}` : "未绑定"}</strong>
            {sourceReportId ? (
              <Link href={`/projects/${id}/reports/${sourceReportId}`}>查看报告</Link>
            ) : (
              <small>普通稿件或项目关键词生成</small>
            )}
          </div>
          <div className="metric">
            <span>阶段目标</span>
            <strong>{stageGoalId ? `#${stageGoalId}` : "未绑定"}</strong>
            {stageGoalId ? (
              <Link href={`/projects/${id}#stage-goals`}>查看目标</Link>
            ) : (
              <small>{String(sourceContext.stage_goal_metric_name ?? "未从阶段目标触发")}</small>
            )}
          </div>
          <div className="metric">
            <span>缺口规模</span>
            <strong>
              {Number(sourceContext.question_gap_count ?? 0) + Number(sourceContext.keyword_gap_count ?? 0)}
            </strong>
            <small>
              问题 {String(sourceContext.question_gap_count ?? 0)}｜关键词 {String(sourceContext.keyword_gap_count ?? 0)}｜信源{" "}
              {String(sourceContext.source_gap_count ?? 0)}
            </small>
          </div>
          <div className="metric">
            <span>关键词语境</span>
            <strong>{Math.round(Number(sourceContext.keyword_prompt_coverage_rate ?? 0) * 100)}%</strong>
            <small>
              跑满 {String(sourceContext.keyword_prompt_full_coverage_count ?? 0)}｜
              待补 {String(sourceContext.keyword_prompt_gap_count ?? 0)}｜
              目标 {String(sourceContext.keyword_prompt_target_variant_count ?? 3)} 变体
            </small>
          </div>
        </div>
        <div className="grid cols-3">
          <div>
            <h3>正文覆盖的问题</h3>
            <p className="subtle">{coveredQuestionGaps.length > 0 ? coveredQuestionGaps.join("、") : "正文主要围绕当前标题展开，未额外塞入报告问题缺口。"}</p>
          </div>
          <div>
            <h3>正文覆盖的关键词</h3>
            <p className="subtle">{coveredKeywordGaps.length > 0 ? coveredKeywordGaps.join("、") : "正文没有硬塞关键词，优先保持可发布文章的自然表达。"}</p>
          </div>
          <div>
            <h3>关联投放信源</h3>
            <p className="subtle">{suggestedPlacementSources.length > 0 ? suggestedPlacementSources.join("、") : "暂无报告信源缺口，优先官网 FAQ、解决方案页和可索引媒体。"}</p>
          </div>
        </div>
        <div className="grid cols-2">
          <div>
            <h3>正文覆盖的搜索问法</h3>
            <p className="subtle">{coveredKeywordPrompts.length > 0 ? coveredKeywordPrompts.join("、") : "暂无直接命中，后续可另起 FAQ 稿件覆盖。"}</p>
          </div>
          <div>
            <h3>报告样例问法</h3>
            <p className="subtle">{keywordPromptSamples.length > 0 ? keywordPromptSamples.slice(0, 4).join("、") : "暂无关键词语境样本。"}</p>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>GEO 后续运营清单</h2>
            <p className="subtle">这些是投放、补证据和下一轮采集建议，不会写进正文。</p>
          </div>
          <span className="tag">ops</span>
        </div>
        <div className="grid cols-2">
          <div>
            <h3>待补目标问题</h3>
            <p className="subtle">{geoQuestionGaps.length > 0 ? geoQuestionGaps.join("、") : "暂无待补问题。"}</p>
          </div>
          <div>
            <h3>待补关键词</h3>
            <p className="subtle">{geoKeywordGaps.length > 0 ? geoKeywordGaps.join("、") : "暂无待补关键词。"}</p>
          </div>
          <div>
            <h3>可另做 FAQ 的问法</h3>
            <p className="subtle">{geoPromptSamples.length > 0 ? geoPromptSamples.slice(0, 5).join("、") : "暂无问法样本。"}</p>
          </div>
          <div>
            <h3>投放与存证位置</h3>
            <p className="subtle">{geoSourceSuggestions.length > 0 ? geoSourceSuggestions.join("、") : "官网解决方案页、官网 FAQ、白皮书下载页、可索引媒体文章。"}</p>
          </div>
        </div>
        <div>
          <h3>建议补充的证据</h3>
          <p className="subtle">{geoEvidenceSuggestions.length > 0 ? geoEvidenceSuggestions.join("、") : "功能截图、客户场景、调用日志、成本报表、权限审计记录。"}</p>
        </div>
      </section>

      <section className="grid cols-2" id="reviews">
        <div className="panel">
          <h2>正文</h2>
          <article className="content">{draft.body_text}</article>
        </div>
        <div className="panel">
          <h2>审核建议</h2>
          {latestReview ? (
            <div className="list">
              {Object.entries(latestReview.dimension_scores).map(([name, score]) => (
                <div className="row" key={name}>
                  <h3>{name}</h3>
                  <span className="tag">{score}</span>
                </div>
              ))}
              {latestReview.issues_json.map((item, index) => (
                <div className="row" key={`issue-${index}`}>
                  <div>
                    <h3>{String(item.type ?? "问题")}</h3>
                    <small>{String(item.message ?? "")}</small>
                  </div>
                  <span className="tag">issue</span>
                </div>
              ))}
              {latestReview.suggestions_json.map((item, index) => (
                <div className="row" key={`suggestion-${index}`}>
                  <div>
                    <h3>{String(item.type ?? "建议")}</h3>
                    <small>{String(item.message ?? "")}</small>
                  </div>
                  <span className="tag active">suggestion</span>
                </div>
              ))}
              {latestReview.risk_expressions.map((item, index) => (
                <div className="row" key={`risk-${index}`}>
                  <div>
                    <h3>{String(item.expression ?? "风险表达")}</h3>
                    <small>{String(item.message ?? "")}</small>
                  </div>
                  <span className="tag">risk</span>
                </div>
              ))}
              {reviewRuleSnapshot ? (
                <div className="notice">
                  <div className="section-head">
                    <div>
                      <h3>{reviewRuleSnapshot.standard ?? "审核标准快照"}</h3>
                      <small>
                        版本 {reviewRuleSnapshot.version ?? 1}｜规则 {reviewRules.length} 条｜基础满分{" "}
                        {reviewRuleSnapshot.total_max_score ?? "未记录"}
                      </small>
                    </div>
                    <span className="tag active">snapshot</span>
                  </div>
                  <div className="grid cols-2">
                    {reviewRules.slice(0, 6).map((rule, index) => (
                      <div className="metric" key={`${rule.rule_key ?? rule.name ?? index}`}>
                        <span>{rule.name ?? rule.rule_key ?? "未命名规则"}</span>
                        <strong>{rule.max_score ?? 0}</strong>
                        <small>
                          {rule.rule_key ?? "custom"}｜v{rule.version ?? 1}
                        </small>
                      </div>
                    ))}
                  </div>
                  {reviewRules.length > 6 ? <small>另有 {reviewRules.length - 6} 条规则参与本次评分。</small> : null}
                  {reportAlignment ? (
                    <p className="subtle">
                      报告承接度：{reportAlignment.score ?? 0}/{reportAlignment.max_score ?? 0}
                      {reportAlignment.source_report_id ? `，来源报告 #${reportAlignment.source_report_id}` : ""}
                    </p>
                  ) : null}
                </div>
              ) : null}
              <form action={reviseDraft}>
                <SubmitButton pendingText="生成优化版...">生成优化版并复评</SubmitButton>
              </form>
            </div>
          ) : (
            <p className="subtle">还没有审核结果。</p>
          )}
        </div>
      </section>

      <section className="panel" id="manual-review">
        <h2>人工审核</h2>
        <p className="subtle">当前状态：{draft.status}</p>
        <div className="grid cols-2">
          <form action={approveDraft} className="form">
            <div className="field">
              <label>审核备注</label>
              <textarea name="comment" placeholder="例如：已确认可进入投放计划。" />
            </div>
            <SubmitButton pendingText="提交审核中...">通过</SubmitButton>
          </form>
          <form action={rejectDraft} className="form">
            <div className="field">
              <label>退回原因</label>
              <textarea name="comment" placeholder="例如：案例证据不足，需补充来源。" />
            </div>
            <SubmitButton className="button secondary" pendingText="退回中...">
              退回修改
            </SubmitButton>
          </form>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>通过并投放</h2>
            <p className="subtle">适合评分通过的报告承接稿：一次完成人工通过和 planned 投放计划创建。</p>
          </div>
          <span className={latestReview ? "tag active" : "tag"}>{latestReview ? `${latestReview.total_score} 分` : "待评分"}</span>
        </div>
        <form action={approveAndCreatePlacement} className="form">
          <div className="grid cols-2">
            <div className="field">
              <label>投放渠道</label>
              <input name="channel" defaultValue="报告承接稿件投放" />
            </div>
            <div className="field">
              <label>目标 URL</label>
              <input name="target_url" placeholder="发布后补充 URL" />
            </div>
          </div>
          <div className="field">
            <label>审核和投放说明</label>
            <textarea
              name="comment"
              defaultValue={
                latestReview
                  ? `AI 评分 ${latestReview.total_score} ${latestReview.grade}，人工确认进入投放计划。`
                  : "人工确认进入投放计划。"
              }
            />
          </div>
          <input
            type="hidden"
            name="notes"
            value={
              placementSuggestion
                ? String(placementSuggestion.message ?? "")
                : latestReview
                  ? `AI 评分 ${latestReview.total_score} ${latestReview.grade}，建议进入 GEO 投放计划。`
                  : "稿件已通过人工审核，加入 GEO 投放计划。"
            }
          />
          <SubmitButton disabled={!latestReview || linkedPlacements.length > 0} pendingText="创建投放中...">
            通过并创建投放
          </SubmitButton>
          {linkedPlacements.length > 0 ? <small>该稿件已有投放计划。</small> : null}
        </form>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>内容资产沉淀</h2>
            <p className="subtle">人工审核通过后，可把稿件沉淀到内容资产库，用于历史稿件评分、成熟度诊断输入和后续投放。</p>
          </div>
          <form action={createAssetFromDraft}>
            <SubmitButton className="button secondary" disabled={draft.status !== "approved"} pendingText="入库中...">
              入库
            </SubmitButton>
          </form>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>进入投放</h2>
            <p className="subtle">人工审核通过后，可直接把这篇稿件加入 planned 投放计划。</p>
          </div>
          <span className={draft.status === "approved" ? "tag active" : "tag"}>{draft.status}</span>
        </div>
        <form action={createPlacement} className="form">
          <input name="article_draft_id" type="hidden" value={draft.id} />
          <input name="status" type="hidden" value="planned" />
          <div className="grid cols-2">
            <div className="field">
              <label>投放渠道</label>
              <input name="channel" defaultValue="报告承接稿件投放" />
            </div>
            <div className="field">
              <label>目标 URL</label>
              <input name="target_url" placeholder="发布后补充 URL" />
            </div>
          </div>
          <div className="field">
            <label>投放说明</label>
            <textarea
              name="notes"
              defaultValue={
                placementSuggestion
                  ? String(placementSuggestion.message ?? "")
                  : "稿件已通过审核，加入 GEO 投放计划。"
              }
            />
          </div>
          <SubmitButton disabled={draft.status !== "approved"} pendingText="创建投放中...">
            加入投放计划
          </SubmitButton>
        </form>
      </section>
    </div>
  );
}
