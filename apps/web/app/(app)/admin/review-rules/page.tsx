import { createReviewRuleAction } from "@/app/actions";
import { getReviewRules } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    active: "启用",
    inactive: "停用",
    archived: "归档"
  };
  return labels[value] ?? value;
}

export default async function ReviewRulesPage() {
  const user = await getCurrentUser();
  const rules = await getReviewRules().catch(() => []);
  const activeRules = rules.filter((rule) => rule.status === "active");
  const totalMaxScore = activeRules.reduce((sum, rule) => sum + rule.max_score, 0);
  const canCreate = user?.role === "super_admin";

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">管理员后台</div>
          <h1>审核标准</h1>
          <p className="subtle">维护 GEO 稿件评分维度，AI 评分会把当时启用的规则快照写入审核记录。</p>
        </div>
      </div>

      <section className="grid cols-4">
        <div className="panel metric">
          <span>规则总数</span>
          <strong>{rules.length}</strong>
        </div>
        <div className="panel metric">
          <span>启用规则</span>
          <strong>{activeRules.length}</strong>
        </div>
        <div className="panel metric">
          <span>启用总分</span>
          <strong>{totalMaxScore}</strong>
        </div>
        <div className="panel metric">
          <span>最高版本</span>
          <strong>{Math.max(...rules.map((rule) => rule.version), 1)}</strong>
        </div>
      </section>

      {canCreate ? (
        <section className="panel">
          <div className="section-heading">
            <div>
              <h2>新增评分规则</h2>
              <p className="subtle">新增后会参与后续 AI 评分；历史审核记录保留原规则快照。</p>
            </div>
          </div>
          <form className="grid cols-2" action={createReviewRuleAction}>
            <label>
              规则 Key
              <input name="rule_key" placeholder="例如：source_coverage" required />
            </label>
            <label>
              规则名称
              <input name="name" placeholder="例如：信源覆盖度" required />
            </label>
            <label>
              适用对象
              <select name="applies_to" defaultValue="article">
                <option value="article">稿件与内容资产</option>
                <option value="all">全部</option>
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
              最高分
              <input name="max_score" type="number" min="1" max="100" defaultValue="10" />
            </label>
            <label>
              权重
              <input name="weight" type="number" min="1" max="10" defaultValue="1" />
            </label>
            <label className="span-2">
              说明
              <input name="description" placeholder="说明这条规则评估什么，以及为什么影响 GEO 表现。" />
            </label>
            <label className="span-2">
              检查配置 JSON
              <textarea name="checks_json" placeholder='{"positive_markers":["来源","案例","报告"]}' />
            </label>
            <div className="row-actions span-2">
              <button className="button" type="submit">
                新增规则
              </button>
            </div>
          </form>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>评分维度</h2>
            <p className="subtle">当前启用规则会进入新稿件和历史内容资产的 AI 评分。</p>
          </div>
        </div>
        <div className="table">
          {rules.map((rule) => (
            <div className="table-row" key={rule.id}>
              <div>
                <strong>{rule.name}</strong>
                <small>
                  {rule.rule_key}｜{statusLabel(rule.status)}｜v{rule.version}
                </small>
                <small>{rule.description ?? "暂无说明"}</small>
              </div>
              <div>
                <span className={rule.status === "active" ? "tag active" : "tag"}>{statusLabel(rule.status)}</span>
              </div>
              <div>
                <strong>{rule.max_score} 分</strong>
                <small>权重 {rule.weight}</small>
              </div>
              <div>
                <small>{JSON.stringify(rule.checks_json)}</small>
              </div>
            </div>
          ))}
          {rules.length === 0 ? <p className="subtle">暂无评分规则。</p> : null}
        </div>
      </section>
    </div>
  );
}
