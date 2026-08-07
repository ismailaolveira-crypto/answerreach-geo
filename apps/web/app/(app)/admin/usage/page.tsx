import Link from "next/link";
import type { Route } from "next";
import { getUsageRecords, getUsageSummary } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import { redirect } from "next/navigation";

function money(value: number, currency: string) {
  return `${currency} ${value.toFixed(6)}`;
}

function asRoute(value: string) {
  return value as Route;
}

export default async function UsagePage() {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin" && user?.role !== "company_admin") {
    redirect("/");
  }
  const [summary, records] = await Promise.all([
    getUsageSummary().catch(() => null),
    getUsageRecords(30).catch(() => [])
  ]);

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">管理员后台</div>
          <h1>用量统计</h1>
          <p className="subtle">汇总模型调用、搜索采集和渠道测试产生的 token 与估算成本。</p>
        </div>
      </div>

      <div className="notice warning">
        成本为估算值，依赖模型渠道里的输入/输出单价配置；未配置单价的 Provider 会按 0 成本统计。
      </div>

      {!summary ? (
        <section className="panel">
          <h2>暂无用量数据</h2>
          <p className="subtle">完成 Provider 测试或搜索采集后会自动产生用量记录。</p>
        </section>
      ) : (
        <>
          <section className="grid cols-3">
            <div className="panel metric">
              <span>调用记录</span>
              <strong>{summary.total_records}</strong>
            </div>
            <div className="panel metric">
              <span>总 Token</span>
              <strong>{summary.total_tokens}</strong>
            </div>
            <div className="panel metric">
              <span>估算成本</span>
              <strong>{money(summary.total_estimated_cost, summary.currency)}</strong>
            </div>
          </section>

          <section className="grid cols-2">
            <div className="panel">
              <h2>按动作</h2>
              <div className="list">
                {summary.by_action.length === 0 ? (
                  <p className="subtle">暂无动作数据。</p>
                ) : (
                  summary.by_action.map((item) => (
                    <div className="row" key={item.action}>
                      <div>
                        <h3>{item.action}</h3>
                        <small>
                          {item.records} 次｜{item.total_tokens} tokens
                        </small>
                      </div>
                      <span className="tag">{money(item.estimated_cost, summary.currency)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="panel">
              <h2>按渠道</h2>
              <div className="list">
                {summary.by_provider.length === 0 ? (
                  <p className="subtle">暂无渠道数据。</p>
                ) : (
                  summary.by_provider.map((item) => (
                    <div className="row" key={`${item.provider_id}-${item.provider_name}`}>
                      <div>
                        <h3>{item.provider_name}</h3>
                        <small>
                          {item.records} 次｜{item.total_tokens} tokens
                        </small>
                      </div>
                      <span className="tag">{money(item.estimated_cost, summary.currency)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="section-head">
              <div>
                <h2>最近用量记录</h2>
                <p className="subtle">用于追踪真实 Provider 测试、搜索采集和复盘任务的消耗来源。</p>
              </div>
              <span className="tag">最近 {records.length} 条</span>
            </div>
            <div className="list">
              {records.length === 0 ? (
                <p className="subtle">暂无最近用量记录。</p>
              ) : (
                records.map((record) => (
                  <div className="row" key={record.id}>
                    <div>
                      <h3>{record.action}</h3>
                      <small>
                        {record.created_at}｜Provider {record.provider_id ?? "-"}｜{record.prompt_tokens} /{" "}
                        {record.completion_tokens} tokens｜{money(record.estimated_cost, record.currency)}
                      </small>
                      <div className="mini-list">
                        {record.project_id ? (
                          <Link href={asRoute(`/projects/${record.project_id}`)}>项目 #{record.project_id}</Link>
                        ) : null}
                        {record.project_id && record.task_id ? (
                          <Link href={asRoute(`/projects/${record.project_id}/tasks/${record.task_id}`)}>
                            采集任务 #{record.task_id}
                          </Link>
                        ) : null}
                        {record.project_id && record.crawl_result_id ? (
                          <Link href={asRoute(`/projects/${record.project_id}/answers/${record.crawl_result_id}`)}>
                            答案 #{record.crawl_result_id}
                          </Link>
                        ) : null}
                        {record.provider_id && record.provider_test_run_id ? (
                          <Link href={asRoute(`/admin/providers/${record.provider_id}/test`)}>
                            Provider 测试 #{record.provider_test_run_id}
                          </Link>
                        ) : null}
                      </div>
                    </div>
                    <span className="tag">{record.total_tokens} tokens</span>
                  </div>
                ))
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
