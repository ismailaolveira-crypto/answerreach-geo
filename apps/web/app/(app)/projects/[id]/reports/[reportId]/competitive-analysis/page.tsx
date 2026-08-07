import Link from "next/link";
import { getMaturityReport, getMaturityReportMarkdownUrl } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string; reportId: string }>;
};

export default async function CompetitiveAnalysisPage({ params }: PageProps) {
  const { id, reportId } = await params;
  const report = await getMaturityReport(id, reportId);
  const doc = report.report_json.competitive_analysis_document;

  if (!doc) {
    return (
      <div className="stack">
        <section className="panel">
          <h1>竞品分析说明文档尚未生成</h1>
          <Link className="button secondary" href={`/projects/${id}/reports/${reportId}`}>
            返回报告
          </Link>
        </section>
      </div>
    );
  }

  const uniqueCompanyQuestions = new Set(doc.company_mentions.map((item) => item.question_id)).size;
  const companyRecommendations = doc.company_mentions.filter((item) => item.recommended).length;
  const competitorRecommendations = doc.competitors.reduce((sum, item) => sum + item.recommendation_count, 0);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">项目 1｜任务 #{doc.scope.task_id}｜正式说明文档</div>
          <h1>春秋元泉 Token 统一管控平台 GEO 竞品分析说明文档</h1>
          <p className="subtle">{doc.scope.evidence_type}｜25 个问题 × 每题 4 次｜严格排除历史任务与 Mock 数据</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}/reports/${reportId}`}>
          返回评分报告
        </Link>
        <a className="button" href={getMaturityReportMarkdownUrl(id, reportId)}>
          下载完整说明文档
        </a>
      </div>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>Executive Summary</h2>
            <p className="subtle">先看结论，再进入问题、样本、信源和内容动作的逐条证据。</p>
          </div>
          <span className="tag">生成于 {doc.generated_at.slice(0, 10)}</span>
        </div>
        <div className="list compact">
          {doc.executive_findings.map((finding) => (
            <div className="row" key={finding}>
              <strong>{finding}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="grid cols-4">
        <div className="panel metric"><span>春秋元泉提及</span><strong>{doc.company_mentions.length}</strong><small>集中在 {uniqueCompanyQuestions} 个问题</small></div>
        <div className="panel metric"><span>春秋元泉推荐</span><strong>{companyRecommendations}</strong><small>仅 Q19 样本 3</small></div>
        <div className="panel metric"><span>竞品推荐</span><strong>{competitorRecommendations}</strong><small>6 个重点竞品</small></div>
        <div className="panel metric"><span>网址线索</span><strong>{doc.source_summary.record_count}</strong><small>真实检索链路已验证 0</small></div>
      </section>

      <section className="panel">
        <div className="section-head"><div><h2>春秋元泉 17 次提及逐条明细</h2><p className="subtle">“仅提及”不等于推荐；每条均可回到任务 #8 的原始结果和样本序号。</p></div><span className="tag active">17/17 已列明</span></div>
        <div className="list">
          {doc.company_mentions.map((item) => (
            <div className="row review-row" key={item.result_id}>
              <div>
                <div className="meta-line"><span>Q{item.question_id}</span><span>样本 {item.sample_run}</span><span>结果 #{item.result_id}</span><span>{item.recommended ? `推荐第 ${item.rank} 位` : "仅提及"}</span></div>
                <h3>{item.question}</h3>
                <small>{item.context}</small>
              </div>
              <span className={item.recommended ? "tag active" : "tag"}>{item.recommended ? "推荐" : "提及"}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-head"><div><h2>5 个提及问题的判断</h2><p className="subtle">17 次提及集中于这些品牌词问题，不能直接解释为自然搜索可见度。</p></div></div>
        <div className="list">
          {doc.company_question_summary.map((item) => (
            <div className="row review-row" key={item.question_id}>
              <div><div className="meta-line"><span>Q{item.question_id}</span><span>提及样本 {item.sample_runs.join("、")}</span></div><h3>{item.question}</h3><small>{item.interpretation}</small></div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-head"><div><h2>网页观测与截图补证清单</h2><p className="subtle">可在豆包、DeepSeek、Kimi、千问网页端逐项补证；当前状态均为待人工执行，不能冒充已有截图。</p></div><span className="tag">10 题 × 4 平台</span></div>
        <div className="list">
          {doc.observation_plan.map((item) => (
            <div className="row review-row" key={item.question_id}>
              <div><div className="meta-line"><span>{item.priority}</span><span>Q{item.question_id}</span><span>{item.platforms.join("、")}</span></div><h3>{item.question}</h3><small>{item.reason}</small><small>截图要求：{item.required_evidence.join("、")}</small></div>
              <span className="tag">待观测</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-head"><div><h2>竞品问题级提及与推荐</h2><p className="subtle">按问题、样本、提及次数、推荐位和原回答语境展开。</p></div><span className="tag">竞品 {doc.competitors.length}</span></div>
        <div className="list">
          {doc.competitors.map((competitor) => (
            <details className="subpanel" key={competitor.name} open={competitor.name === "阿里云百炼"}>
              <summary><strong>{competitor.name}</strong>｜回答 {competitor.answer_mentions}｜提及 {competitor.mention_count}｜推荐 {competitor.recommendation_count}</summary>
              <div className="list compact">
                {competitor.samples.map((item) => (
                  <div className="row review-row" key={`${competitor.name}-${item.result_id}`}>
                    <div><div className="meta-line"><span>Q{item.question_id}</span><span>样本 {item.sample_run}</span><span>提及 {item.mention_count}</span><span>推荐位 {item.rank ?? "无"}</span></div><h3>{item.question}</h3><small>{item.context}</small><small>回答网址线索：{item.claimed_source_urls.join("、") || "无"}</small></div>
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-head"><div><h2>回答声称参考的网址线索</h2><p className="subtle">全部来自 Q6。仅 {doc.source_summary.answers_with_claimed_urls}/100 条回答带网址，{doc.source_summary.answers_without_claimed_urls}/100 条没有网址；HTTP 可访问只证明网址当前存在，不证明模型生成答案时真实检索，也不构成春秋元泉产品证据。</p></div><span className="tag">官方春秋元泉信源 0｜检索链路证明 0</span></div>
        <div className="list">
          {doc.source_leads.map((source) => (
            <div className="row review-row" key={source.url}>
              <div><div className="meta-line"><span>{source.domain}</span><span>Q{source.question_ids.join("、")}</span><span>出现 {source.occurrences}</span><span>HTTP {source.http_status || "不可达"}</span></div><h3><a href={source.url} target="_blank" rel="noreferrer">{source.url}</a></h3><small>{source.verification_note}</small><small>{source.lineage_status}</small></div>
              <span className={source.http_status === 200 ? "tag active" : "tag"}>{source.http_status === 200 ? "当前可访问" : "待修正"}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-head"><div><h2>下一阶段在哪些平台发布哪些文章</h2><p className="subtle">先补官网权威证据，再用微信、知乎和技术社区分发；外部平台文章不能替代一手产品资料。</p></div></div>
        <div className="list">
          {doc.article_plan.map((item) => (
            <div className="row review-row" key={`${item.platform}-${item.title}`}>
              <div><div className="meta-line"><span>{item.priority}</span><span>{item.platform}</span><span>目标 {item.target_questions.map((q) => `Q${q}`).join("、")}</span></div><h3>{item.title}</h3><small>依据：{item.basis}</small><small>必须包含：{item.must_include}</small></div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>边界与待确认事项</h2>
        <div className="list compact">{doc.caveats.map((item) => <div className="row" key={item}><span>{item}</span></div>)}</div>
      </section>
    </div>
  );
}
