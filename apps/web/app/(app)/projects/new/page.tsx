import { createProjectAction } from "@/app/actions";

export default function NewProjectPage() {
  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">新建项目</div>
          <h1>创建第一个 GEO 诊断项目</h1>
          <p className="subtle">录入基础信息后，会同步创建企业、项目、目标问题、关键词和竞品。</p>
        </div>
      </div>

      <section className="panel">
        <form action={createProjectAction} className="form">
          <div className="field">
            <label>企业名称</label>
            <input name="company_name" placeholder="例如：某某科技有限公司" required />
          </div>
          <div className="field">
            <label>官网地址</label>
            <input name="website_url" placeholder="https://example.com" />
          </div>
          <div className="field">
            <label>项目名称</label>
            <input name="project_name" placeholder="例如：网络安全培训 GEO 优化" required />
          </div>
          <div className="field">
            <label>目标行业</label>
            <input name="industry" placeholder="例如：网络安全 / 数据安全 / 企业服务" />
          </div>
          <div className="field">
            <label>目标客户</label>
            <input name="target_audience" placeholder="例如：企业安全负责人 / 市场负责人" />
          </div>
          <div className="field">
            <label>项目说明</label>
            <textarea name="project_description" placeholder="说明这次 GEO 优化希望解决的问题。" />
          </div>
          <div className="field">
            <label>目标问题，每行一个</label>
            <textarea
              name="target_questions"
              placeholder={"网络安全培训公司哪家好？\n企业如何选择攻防演练服务商？"}
            />
          </div>
          <div className="field">
            <label>关键词，每行一个</label>
            <textarea name="keywords" placeholder={"网络安全培训\n攻防演练\n数据安全治理"} />
          </div>
          <div className="field">
            <label>竞品，每行一个</label>
            <textarea name="competitors" placeholder={"竞品公司 A\n竞品公司 B"} />
          </div>
          <button className="button" type="submit">
            保存项目
          </button>
        </form>
      </section>
    </div>
  );
}
