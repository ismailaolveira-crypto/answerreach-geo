import { getAuditLogs } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import { redirect } from "next/navigation";

export default async function AuditLogPage() {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin" && user?.role !== "company_admin") {
    redirect("/");
  }
  const logs = await getAuditLogs().catch(() => []);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">管理员后台</div>
          <h1>审计日志</h1>
          <p className="subtle">记录采集、报告、撰稿、审核、投放和模型渠道测试等关键动作。</p>
        </div>
      </div>

      <section className="panel">
        <h2>近期操作</h2>
        <div className="list">
          {logs.length === 0 ? (
            <p className="subtle">暂无审计日志。</p>
          ) : (
            logs.map((log) => (
              <div className="row" key={log.id}>
                <div>
                  <h3>{log.action}</h3>
                  <small>
                    {log.created_at}｜{log.actor_role ?? "unknown"}｜{log.resource_type}
                    {log.resource_id ? ` #${log.resource_id}` : ""}
                  </small>
                  <p className="subtle">{JSON.stringify(log.detail_json)}</p>
                </div>
                <span className="tag">{log.project_id ? `项目 ${log.project_id}` : "系统"}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
