import { createUserAction, deactivateUserAction } from "@/app/actions";
import { getCompanies, getUsers } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import { redirect } from "next/navigation";

const roleOptions = [
  { value: "company_admin", label: "企业管理员" },
  { value: "content_operator", label: "内容运营" },
  { value: "reviewer", label: "审核人员" },
  { value: "viewer", label: "观察者" }
];

export default async function UsersPage() {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin" && user?.role !== "company_admin") {
    redirect("/");
  }
  const [users, companies] = await Promise.all([
    getUsers().catch(() => []),
    getCompanies().catch(() => [])
  ]);
  const canChooseCompany = user.role === "super_admin";
  const availableRoles =
    user.role === "super_admin" ? [{ value: "super_admin", label: "超级管理员" }, ...roleOptions] : roleOptions.slice(1);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">管理员后台</div>
          <h1>用户管理</h1>
          <p className="subtle">创建协作账号，按角色分配采集、撰稿、审核和观察权限。</p>
        </div>
      </div>

      <section className="grid cols-2">
        <div className="panel">
          <h2>新增用户</h2>
          <form action={createUserAction} className="form">
            <div className="field">
              <label>姓名</label>
              <input name="name" placeholder="例如：内容运营 A" required />
            </div>
            <div className="field">
              <label>邮箱</label>
              <input name="email" type="email" placeholder="user@example.com" required />
            </div>
            <div className="field">
              <label>初始密码</label>
              <input name="password" type="password" defaultValue="geo-demo-123" required />
            </div>
            {canChooseCompany ? (
              <div className="field">
                <label>所属企业</label>
                <select name="company_id" defaultValue="">
                  <option value="">不绑定企业</option>
                  {companies.map((company) => (
                    <option value={company.id} key={company.id}>
                      {company.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="field">
              <label>角色</label>
              <select name="role" defaultValue={user.role === "super_admin" ? "viewer" : "content_operator"}>
                {availableRoles.map((role) => (
                  <option value={role.value} key={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>
            <button className="button" type="submit">
              创建用户
            </button>
          </form>
        </div>

        <div className="panel">
          <h2>角色说明</h2>
          <div className="list">
            <div className="row">
              <div>
                <h3>内容运营</h3>
                <small>维护内容资产、投放记录、生成和编辑稿件。</small>
              </div>
            </div>
            <div className="row">
              <div>
                <h3>审核人员</h3>
                <small>对稿件和历史内容进行审核打分、批准或驳回。</small>
              </div>
            </div>
            <div className="row">
              <div>
                <h3>观察者</h3>
                <small>查看项目、报告和数据，不执行消耗模型额度的动作。</small>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>用户列表</h2>
        <div className="list">
          {users.length === 0 ? (
            <p className="subtle">暂无用户。</p>
          ) : (
            users.map((item) => {
              const deactivate = deactivateUserAction.bind(null, item.id);
              const company = companies.find((entry) => entry.id === item.company_id);
              return (
                <div className="row" key={item.id}>
                  <div>
                    <h3>{item.name}</h3>
                    <small>
                      {item.email}｜{item.role}｜{company?.name ?? "未绑定企业"}
                    </small>
                  </div>
                  <div className="row-actions">
                    <span className="tag">{item.status}</span>
                    {item.status === "active" && item.id !== user.id ? (
                      <form action={deactivate}>
                        <button className="button secondary" type="submit">
                          停用
                        </button>
                      </form>
                    ) : null}
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
