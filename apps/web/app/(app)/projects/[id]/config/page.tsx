import Link from "next/link";
import type { Route } from "next";
import { appendProjectConfigAction, seedMaturityConfigAction } from "@/app/actions";
import { getCompetitors, getKeywords, getProject, getTargetQuestions } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ config_added?: string }>;
};

function asRoute(value: string) {
  return value as Route;
}

function readinessStatus(score?: number | null) {
  const value = score ?? 0;
  if (value >= 90) return "ready";
  if (value >= 60) return "partial";
  return "thin";
}

export default async function ProjectConfigPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const queryParams = await searchParams;
  const [project, questions, keywords, competitors] = await Promise.all([
    getProject(id),
    getTargetQuestions(id).catch(() => []),
    getKeywords(id).catch(() => []),
    getCompetitors(id).catch(() => [])
  ]);
  const appendProjectConfig = appendProjectConfigAction.bind(null, id);
  const seedMaturityConfig = seedMaturityConfigAction.bind(null, id);
  const configAddedCount = Number(queryParams.config_added ?? 0);
  const readiness = readinessStatus(project.diagnostic_readiness_score);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">项目配置</div>
          <h1>{project.name} 诊断输入</h1>
          <p className="subtle">集中维护目标问题、核心关键词和竞品，为搜索采集与成熟度报告提供稳定输入。</p>
        </div>
        <Link className="button secondary" href={asRoute(`/projects/${id}`)}>
          返回项目
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/dashboard`)}>
          交付驾驶舱
        </Link>
      </div>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>诊断输入完整度</h2>
            <p className="subtle">建议至少准备 10 个目标问题、10 个关键词、3 个竞品，以及可审核/可投放内容。</p>
          </div>
          <span className={readiness === "ready" ? "tag active" : "tag"}>{project.diagnostic_readiness_score ?? 0}%</span>
        </div>
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
        <div className="row-actions">
          <form action={seedMaturityConfig}>
            <input name="return_to" type="hidden" value={`/projects/${id}/config`} />
            <button className="button secondary" type="submit">
              自动补齐 10+10
            </button>
          </form>
          <Link className="button secondary" href={asRoute(`/projects/${id}/assets`)}>
            内容资产库
          </Link>
          <Link className="button secondary" href={asRoute(`/projects/${id}/placements`)}>
            投放计划
          </Link>
        </div>
      </section>

      {configAddedCount > 0 ? (
        <section className="panel">
          <h2>配置已更新</h2>
          <p className="subtle">本次已追加 {configAddedCount} 条目标问题、关键词或竞品。</p>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>批量追加</h2>
            <p className="subtle">按行追加，不覆盖现有配置。新增后会立即进入采集范围、报告覆盖统计和网页观测建议。</p>
          </div>
          <span className="tag">问题 {questions.length}｜关键词 {keywords.length}｜竞品 {competitors.length}</span>
        </div>
        <form action={appendProjectConfig} className="form">
          <input name="return_to" type="hidden" value={`/projects/${id}/config`} />
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

        <div className="panel">
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
        </div>
      </section>
    </div>
  );
}
