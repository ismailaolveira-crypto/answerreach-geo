import Link from "next/link";
import { notFound } from "next/navigation";
import { getProject, getSourceDetail } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ source_url?: string; source_domain?: string }>;
};

function readinessLabel(value: string) {
  const labels: Record<string, string> = {
    excellent: "优秀",
    good: "良好",
    needs_optimization: "待优化",
    poor: "较差",
    unknown: "未知"
  };
  return labels[value] ?? value;
}

export default async function SourceDetailPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const query = await searchParams;
  const [project, detail] = await Promise.all([
    getProject(id).catch(() => null),
    getSourceDetail(id, query).catch(() => null)
  ]);

  if (!project || !detail) {
    notFound();
  }

  const sourceName = detail.insight.source_domain ?? detail.insight.source_url ?? "未知来源";

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">信源详情</div>
          <h1>{sourceName}</h1>
          <p className="subtle">{project.name}｜出现 {detail.insight.appearances} 次</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}/sources`}>
          返回信源
        </Link>
      </div>

      <section className="grid cols-3">
        <div className="panel metric">
          <span>投放状态</span>
          <strong>{detail.insight.is_placed ? "已投放" : "未投放"}</strong>
          <small>{detail.insight.placement_frequency_label}</small>
        </div>
        <div className="panel metric">
          <span>投放次数</span>
          <strong>{detail.insight.placement_count}</strong>
          <small>已发布 {detail.insight.published_placement_count}</small>
        </div>
        <div className="panel metric">
          <span>AI 适配分</span>
          <strong>{detail.insight.ai_readiness_score}</strong>
          <small>{readinessLabel(detail.insight.ai_readiness_status)}</small>
        </div>
        <div className="panel metric">
          <span>内容资产</span>
          <strong>{detail.insight.has_content_asset ? "有" : "无"}</strong>
        </div>
        <div className="panel metric">
          <span>可抓取性</span>
          <strong>{detail.insight.crawlable_score}</strong>
          <small>{readinessLabel(detail.insight.crawlability_status)}</small>
        </div>
        <div className="panel metric">
          <span>最近投放</span>
          <strong>{detail.insight.latest_placement_at ? "有记录" : "暂无"}</strong>
          <small>{detail.insight.latest_placement_at ?? "-"}</small>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>优化建议</h2>
          <div className="list">
            {detail.recommendations.length === 0 ? (
              <p className="subtle">暂无建议。</p>
            ) : (
              detail.recommendations.map((item) => (
                <div className="row" key={item}>
                  <h3>{item}</h3>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="panel">
          <h2>匹配投放</h2>
          <div className="list">
            {detail.matching_placements.length === 0 ? (
              <p className="subtle">没有匹配投放记录。</p>
            ) : (
              detail.matching_placements.map((item) => (
                <div className="row" key={item.id}>
                  <div>
                    <h3>{item.channel}</h3>
                    <small>{item.target_url}</small>
                  </div>
                  <span className="tag">{item.status}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="grid cols-2">
        <div className="panel">
          <h2>匹配内容资产</h2>
          <div className="list">
            {detail.matching_content_assets.length === 0 ? (
              <p className="subtle">没有匹配内容资产。</p>
            ) : (
              detail.matching_content_assets.map((item) => (
                <div className="row" key={item.id}>
                  <div>
                    <h3>{item.title}</h3>
                    <small>{item.content_type}｜{item.source_url}</small>
                  </div>
                  <span className="tag">{item.status}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="panel">
          <h2>答案证据</h2>
          <div className="list">
            {detail.evidence_results.map((item) => (
              <Link className="row" href={`/projects/${id}/answers/${item.crawl_result_id}`} key={item.crawl_result_id}>
                <div>
                  <h3>{item.prompt_text}</h3>
                  <small>{item.answer_summary}</small>
                </div>
                <span className="tag">答案 #{item.crawl_result_id}</span>
              </Link>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
