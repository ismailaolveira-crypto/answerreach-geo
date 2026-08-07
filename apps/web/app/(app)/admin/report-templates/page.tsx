import { createReportTemplateAction } from "@/app/actions";
import { getReportTemplates } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    active: "启用",
    inactive: "停用",
    archived: "归档"
  };
  return labels[value] ?? value;
}

function compactJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

export default async function ReportTemplatesPage() {
  const user = await getCurrentUser();
  const templates = await getReportTemplates().catch(() => []);
  const activeTemplates = templates.filter((template) => template.status === "active");
  const canCreate = user?.role === "super_admin";
  const latestVersion = Math.max(...templates.map((template) => template.version), 1);
  const defaultSections = [
    { key: "summary", title: "摘要", required: true },
    { key: "core_metrics", title: "核心指标", required: true },
    { key: "delivery_readiness", title: "交付就绪度", required: true },
    { key: "evidence_appendix", title: "证据样本附录", required: true }
  ];
  const defaultScoring = {
    total_score: 100,
    dimensions: [
      { key: "visibility", name: "AI 可见度", max_score: 20 },
      { key: "recommendation", name: "AI 推荐度", max_score: 20 },
      { key: "source_health", name: "信源健康度", max_score: 15 }
    ]
  };
  const defaultDeliveryChecks = [
    { key: "sample_size", label: "样本量", required: 20 },
    { key: "provider_coverage", label: "模型覆盖", required: 3 },
    { key: "traceable_evidence", label: "证据可追溯", required: 3 }
  ];

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">管理员后台</div>
          <h1>报告模板</h1>
          <p className="subtle">维护成熟度报告的章节、评分口径和交付质量门槛；新报告会固化当时启用的模板快照。</p>
        </div>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>模板总数</span>
          <strong>{templates.length}</strong>
        </div>
        <div className="panel metric">
          <span>启用模板</span>
          <strong>{activeTemplates.length}</strong>
        </div>
        <div className="panel metric">
          <span>最高版本</span>
          <strong>{latestVersion}</strong>
        </div>
        <div className="panel metric">
          <span>交付检查</span>
          <strong>{activeTemplates[0]?.delivery_checks_json.length ?? 0}</strong>
        </div>
      </section>

      {canCreate ? (
        <section className="panel">
          <div className="section-heading">
            <div>
              <h2>新增报告模板</h2>
              <p className="subtle">新增模板后会参与后续报告生成；历史报告保留原模板快照。</p>
            </div>
          </div>
          <form className="grid cols-2" action={createReportTemplateAction}>
            <label>
              模板 Key
              <input name="template_key" placeholder="例如：geo_maturity_enterprise_v2" required />
            </label>
            <label>
              模板名称
              <input name="name" placeholder="例如：企业服务 GEO 诊断模板" required />
            </label>
            <label>
              适用对象
              <select name="applies_to" defaultValue="maturity_report">
                <option value="maturity_report">成熟度报告</option>
                <option value="all">全部报告</option>
              </select>
            </label>
            <label>
              状态
              <select name="status" defaultValue="active">
                <option value="active">启用</option>
                <option value="inactive">停用</option>
              </select>
            </label>
            <label>
              版本
              <input name="version" type="number" min="1" defaultValue={latestVersion + 1} />
            </label>
            <label>
              说明
              <input name="description" placeholder="说明该模板适合的客户、行业或交付场景。" />
            </label>
            <label className="span-2">
              章节 JSON
              <textarea name="sections_json" defaultValue={compactJson(defaultSections)} />
            </label>
            <label className="span-2">
              评分口径 JSON
              <textarea name="scoring_json" defaultValue={compactJson(defaultScoring)} />
            </label>
            <label className="span-2">
              交付检查 JSON
              <textarea name="delivery_checks_json" defaultValue={compactJson(defaultDeliveryChecks)} />
            </label>
            <div className="row-actions span-2">
              <button className="button" type="submit">
                新增模板
              </button>
            </div>
          </form>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>模板列表</h2>
            <p className="subtle">生成成熟度报告时会优先采用当前启用模板，并写入报告 JSON、Markdown 和 PDF。</p>
          </div>
        </div>
        <div className="table">
          {templates.map((template) => (
            <div className="table-row" key={template.id}>
              <div>
                <strong>{template.name}</strong>
                <small>
                  {template.template_key}｜{statusLabel(template.status)}｜v{template.version}
                </small>
                <small>{template.description ?? "暂无说明"}</small>
              </div>
              <div>
                <span className={template.status === "active" ? "tag active" : "tag"}>{statusLabel(template.status)}</span>
              </div>
              <div>
                <strong>{template.sections_json.length} 个章节</strong>
                <small>{template.delivery_checks_json.length} 个交付检查</small>
              </div>
              <div>
                <small>{compactJson(template.scoring_json)}</small>
              </div>
            </div>
          ))}
          {templates.length === 0 ? <p className="subtle">暂无报告模板。</p> : null}
        </div>
      </section>
    </div>
  );
}
