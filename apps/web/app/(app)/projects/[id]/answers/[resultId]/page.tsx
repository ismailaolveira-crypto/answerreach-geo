import Link from "next/link";
import { notFound } from "next/navigation";
import { updateCrawlResultAnalysisAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import { getCrawlResult, getProject } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string; resultId: string }>;
  searchParams: Promise<{ corrected?: string }>;
};

export default async function AnswerDetailPage({ params, searchParams }: PageProps) {
  const { id, resultId } = await params;
  const queryParams = await searchParams;
  const [project, result] = await Promise.all([
    getProject(id).catch(() => null),
    getCrawlResult(id, resultId).catch(() => null),
  ]);
  if (!project || !result) {
    notFound();
  }
  const observation =
    result.analysis?.analysis_json && typeof result.analysis.analysis_json === "object"
      ? (result.analysis.analysis_json.browser_observation as
          | {
              observation_url?: string | null;
              screenshot_url?: string | null;
              observer_name?: string | null;
              note?: string | null;
            }
          | undefined)
      : undefined;
  const updateAnalysis = updateCrawlResultAnalysisAction.bind(null, id, resultId);
  const manualCorrection =
    result.analysis?.analysis_json && typeof result.analysis.analysis_json === "object"
      ? (result.analysis.analysis_json.manual_correction as
          | {
              corrected_by_email?: string | null;
              corrected_at?: string | null;
              note?: string | null;
            }
          | undefined)
      : undefined;

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">AI 答案证据</div>
          <h1>{result.prompt_text}</h1>
          <p className="subtle">{project.name}｜采集状态 {result.status}</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
      </div>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>企业提及</span>
          <strong>{result.analysis?.company_mentioned ? "是" : "否"}</strong>
        </div>
        <div className="panel metric">
          <span>企业推荐</span>
          <strong>{result.analysis?.company_recommended ? "是" : "否"}</strong>
        </div>
        <div className="panel metric">
          <span>置信度</span>
          <strong>{result.analysis?.confidence ?? 0}</strong>
        </div>
      </section>

      <section className="panel" id="analysis-correction">
        <div className="section-head">
          <div>
            <h2>人工校正解析</h2>
            <p className="subtle">校正企业提及、推荐和置信度后，后续指标与成熟度报告会使用新的解析结果。</p>
          </div>
          {manualCorrection ? <span className="tag active">已校正</span> : <span className="tag">自动解析</span>}
        </div>
        {manualCorrection ? (
          <p className="subtle">
            最近校正：{manualCorrection.corrected_by_email ?? "unknown"}｜{manualCorrection.corrected_at ?? "-"}
            {manualCorrection.note ? `｜${manualCorrection.note}` : ""}
          </p>
        ) : null}
        {queryParams.corrected === "1" ? (
          <div className="notice success">人工校正已保存，后续指标、成熟度报告和内容建议会使用新的解析结果。</div>
        ) : null}
        <form className="grid cols-3" action={updateAnalysis}>
          <label className="checkline">
            <input
              name="company_mentioned"
              type="checkbox"
              defaultChecked={Boolean(result.analysis?.company_mentioned)}
            />
            企业被提及
          </label>
          <label className="checkline">
            <input
              name="company_recommended"
              type="checkbox"
              defaultChecked={Boolean(result.analysis?.company_recommended)}
            />
            企业被推荐
          </label>
          <label>
            推荐位
            <input name="company_rank" type="number" min="1" max="100" defaultValue={result.analysis?.company_rank ?? ""} />
          </label>
          <label>
            情感
            <select name="sentiment" defaultValue={result.analysis?.sentiment ?? "neutral"}>
              <option value="positive">正向</option>
              <option value="neutral">中性</option>
              <option value="negative">负向</option>
            </select>
          </label>
          <label>
            置信度
            <input name="confidence" type="number" min="0" max="100" defaultValue={result.analysis?.confidence ?? 70} />
          </label>
          <label>
            校正备注
            <input name="correction_note" placeholder="例如：人工复核答案中明确列为推荐对象" />
          </label>
          <div className="row-actions">
            <SubmitButton pendingText="保存中...">保存校正</SubmitButton>
          </div>
        </form>
      </section>

      {observation ? (
        <section className="panel">
          <div className="section-head">
            <div>
              <h2>网页端观测证据</h2>
              <p className="subtle">该样本来自人工网页端观测，可用于校验 API 采集结果与真实产品页面表现。</p>
            </div>
            <span className="tag">browser observation</span>
          </div>
          <div className="grid cols-2">
            <div className="metric">
              <span>网页入口</span>
              <strong>{observation.observation_url ? "已记录" : "未记录"}</strong>
              {observation.observation_url ? <small>{observation.observation_url}</small> : null}
            </div>
            <div className="metric">
              <span>截图证据</span>
              <strong>{observation.screenshot_url ? "已记录" : "未记录"}</strong>
              {observation.screenshot_url ? <small>{observation.screenshot_url}</small> : null}
            </div>
          </div>
          <div className="meta-line">
            {observation.observer_name ? <span>观察员 {observation.observer_name}</span> : null}
            {observation.note ? <span>{observation.note}</span> : null}
          </div>
        </section>
      ) : null}

      <section className="grid cols-2">
        <div className="panel">
          <h2>原始答案</h2>
          <article className="content">{result.raw_answer}</article>
        </div>
        <div className="panel">
          <h2>提及实体</h2>
          <div className="list">
            {result.mentioned_entities.length === 0 ? (
              <p className="subtle">没有识别到实体。</p>
            ) : (
              result.mentioned_entities.map((item) => (
                <div className="row" key={`${item.entity_name}-${item.entity_type}`}>
                  <div>
                    <h3>{item.entity_name}</h3>
                    <small>{item.entity_type}｜提及 {item.mention_count} 次</small>
                  </div>
                  <span className="tag">{item.is_competitor ? "竞品" : item.is_company ? "本企业" : "实体"}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>信源线索</h2>
        <div className="list">
          {result.citation_sources.length === 0 ? (
            <p className="subtle">当前答案没有识别到明确 URL 信源。后续真实联网 Provider 会补充更完整的来源证据。</p>
          ) : (
            result.citation_sources.map((item, index) => (
              <div className="row" key={`${item.source_url}-${index}`}>
                <div>
                  <h3>{item.source_title ?? item.source_domain ?? "未命名信源"}</h3>
                  <small>{item.source_url}</small>
                </div>
                <span className="tag">AI 适配 {item.ai_readiness_score}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
