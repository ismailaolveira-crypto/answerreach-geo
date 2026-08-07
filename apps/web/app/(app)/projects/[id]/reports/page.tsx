import Link from "next/link";
import type { Route } from "next";
import { createReportActionGoalsAction, generateReportAction } from "@/app/actions";
import { SubmitButton } from "@/app/(app)/submit-button";
import {
  getMaturityReportMarkdownUrl,
  getMaturityReportPdfUrl,
  getMaturityReports,
  getProject
} from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
};

function asRoute(value: string) {
  return value as Route;
}

function readinessLabel(status?: string | null) {
  const labels: Record<string, string> = {
    ready: "可交付",
    needs_review: "需复核",
    not_ready: "待补强"
  };
  return labels[status ?? ""] ?? status ?? "未评估";
}

function readinessClass(status?: string | null) {
  return status === "ready" ? "tag active" : "tag";
}

export default async function ProjectReportsPage({ params }: PageProps) {
  const { id } = await params;
  const [project, reports] = await Promise.all([
    getProject(id),
    getMaturityReports(id).catch(() => [])
  ]);
  const generateReport = generateReportAction.bind(null, id);
  const latestReport = reports[0];
  const readyCount = reports.filter((report) => report.report_json.delivery_readiness?.status === "ready").length;
  const averageScore =
    reports.length > 0 ? Math.round(reports.reduce((sum, report) => sum + report.total_score, 0) / reports.length) : 0;

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">成熟度报告</div>
          <h1>{project.name} 报告中心</h1>
          <p className="subtle">集中查看历史 GEO 成熟度报告、交付就绪度、导出和报告行动项。</p>
        </div>
        <Link className="button secondary" href={asRoute(`/projects/${id}`)}>
          返回项目
        </Link>
        <Link className="button secondary" href={asRoute(`/projects/${id}/reports/compare`)}>
          报告对比
        </Link>
        <form action={generateReport}>
          <SubmitButton pendingText="生成中...">生成新报告</SubmitButton>
        </form>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>报告总数</span>
          <strong>{reports.length}</strong>
        </div>
        <div className="panel metric">
          <span>最新总分</span>
          <strong>{latestReport?.total_score ?? 0}</strong>
          <small>{latestReport?.maturity_level ?? "暂无报告"}</small>
        </div>
        <div className="panel metric">
          <span>平均分</span>
          <strong>{averageScore}</strong>
        </div>
        <div className="panel metric">
          <span>可交付</span>
          <strong>{readyCount}</strong>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <h2>报告列表</h2>
            <p className="subtle">按生成时间倒序排列。每份报告都可继续生成整改目标、导出客户材料或进入详情追踪行动项。</p>
          </div>
          <span className="tag">{reports.length} 份</span>
        </div>
        <div className="list">
          {reports.length === 0 ? (
            <div className="empty-state">
              <p className="subtle">暂无成熟度报告。完成搜索采集后可生成第一份企业 GEO 成熟度诊断报告。</p>
              <form action={generateReport}>
                <SubmitButton pendingText="生成中...">生成第一份报告</SubmitButton>
              </form>
            </div>
          ) : (
            reports.map((report) => {
              const readiness = report.report_json.delivery_readiness;
              const template = report.report_json.report_template_snapshot;
              const createActionGoals = createReportActionGoalsAction.bind(null, id, String(report.id));
              return (
                <div className="row" key={report.id}>
                  <div>
                    <div className="meta-line">
                      <span className="tag">{report.maturity_level}</span>
                      <span className={readinessClass(readiness?.status)}>{readinessLabel(readiness?.status)}</span>
                      <span>{report.generated_at ? report.generated_at.slice(0, 10) : "未记录时间"}</span>
                    </div>
                    <Link href={asRoute(`/projects/${id}/reports/${report.id}`)}>
                      <h3>{report.title}</h3>
                    </Link>
                    <small>
                      总分 {report.total_score}｜
                      样本 {report.report_json.coverage?.sample_size ?? report.report_json.evidence_quality?.sample_size ?? 0}｜
                      建议 {report.report_json.recommendations?.length ?? 0}｜
                      模板 {template?.name ?? template?.template_key ?? "默认"}
                    </small>
                    <small>{readiness?.summary ?? report.summary ?? "暂无摘要"}</small>
                  </div>
                  <div className="row-actions">
                    <Link className="button secondary" href={asRoute(`/projects/${id}/reports/${report.id}`)}>
                      详情
                    </Link>
                    <form action={createActionGoals}>
                      <SubmitButton className="button secondary" pendingText="生成中...">生成行动项</SubmitButton>
                    </form>
                    <a className="button secondary" href={getMaturityReportMarkdownUrl(id, String(report.id))}>
                      Markdown
                    </a>
                    <a className="button secondary" href={getMaturityReportPdfUrl(id, String(report.id))}>
                      PDF
                    </a>
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
