import Link from "next/link";
import { getMaturityReportCompare, getProject } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ placement_report?: string; placement_id?: string }>;
};

function formatDelta(value: number) {
  if (value > 0) return `+${value}`;
  return String(value);
}

export default async function ReportComparePage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const queryParams = await searchParams;
  const project = await getProject(id);
  const compare = await getMaturityReportCompare(id).catch(() => null);
  const placementReportId = Number(queryParams.placement_report ?? 0);
  const placementId = Number(queryParams.placement_id ?? 0);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">报告对比</div>
          <h1>{project.name}</h1>
          <p className="subtle">对比最近两次 GEO 成熟度报告，查看分数、指标和维度变化。</p>
        </div>
        <Link className="button secondary" href={`/projects/${id}`}>
          返回项目
        </Link>
      </div>

      {placementReportId > 0 ? (
        <section className="panel">
          <h2>复盘报告已生成</h2>
          <p className="subtle">已基于投放复盘生成成熟度报告 #{placementReportId}，可在这里对比前后变化并继续生成下一轮优化动作。</p>
          <div className="row-actions">
            <Link className="button" href={`/projects/${id}/reports/${placementReportId}`}>
              查看新报告
            </Link>
            {placementId > 0 ? (
              <Link className="button secondary" href={`/projects/${id}/placements/${placementId}/impact`}>
                返回投放复盘
              </Link>
            ) : null}
            <Link className="button secondary" href={`/projects/${id}#stage-goals`}>
              查看阶段目标
            </Link>
          </div>
        </section>
      ) : null}

      {!compare ? (
        <section className="panel">
          <h2>需要至少两份报告</h2>
          <p className="subtle">当前项目报告数量不足。请先完成两轮采集并生成两份成熟度报告。</p>
        </section>
      ) : (
        <>
          <section className="grid cols-3">
            <div className="panel metric">
              <span>基准报告</span>
              <strong>{compare.base_report.total_score}</strong>
              <small>{compare.base_report.maturity_level}</small>
            </div>
            <div className="panel metric">
              <span>目标报告</span>
              <strong>{compare.target_report.total_score}</strong>
              <small>{compare.target_report.maturity_level}</small>
            </div>
            <div className="panel metric">
              <span>总分变化</span>
              <strong>{formatDelta(compare.total_score_delta)}</strong>
              <small>{compare.maturity_level_changed ? "等级发生变化" : "等级保持稳定"}</small>
            </div>
          </section>

          <section className="panel">
            <h2>结论</h2>
            <p className="subtle">{compare.summary}</p>
          </section>

          <section className="grid cols-2">
            <div className="panel">
              <h2>核心指标变化</h2>
              <div className="list">
                {Object.entries(compare.metric_deltas).map(([key, value]) => (
                  <div className="row" key={key}>
                    <div>
                      <h3>{key}</h3>
                      <small>
                        {value.base} {"->"} {value.target}
                      </small>
                    </div>
                    <span className="tag">{formatDelta(value.delta)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="panel">
              <h2>评分维度变化</h2>
              <div className="list">
                {compare.dimension_deltas.map((item) => (
                  <div className="row" key={item.dimension}>
                    <div>
                      <h3>{item.dimension}</h3>
                      <small>
                        {item.base_score}/{item.max_score} {"->"} {item.target_score}/{item.max_score}
                      </small>
                    </div>
                    <span className="tag">{formatDelta(item.delta)}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="panel">
            <h2>复盘建议</h2>
            <div className="list">
              {compare.recommendations.map((item) => (
                <div className="row" key={item}>
                  <h3>{item}</h3>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
