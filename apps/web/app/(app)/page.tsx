import Link from "next/link";
import { redirect } from "next/navigation";
import { getCleanroomWorkspaces } from "@/lib/cleanroom-v1-api";

export default async function SpringYuanHome() {
  const workspaces = await getCleanroomWorkspaces().catch(() => []);
  if (workspaces[0]) redirect(`/geo/${workspaces[0].id}`);

  return <section className="cq-empty-home"><div><span>春秋元泉 GEO</span><h1>从一条可审计观测开始。</h1><p>当前账号还没有 GEO 工作区。完成品牌工作区初始化后，系统会把问题计划、原始回答、引用、截图与复测结论连接成一张决策地图。</p><Link className="cq-primary" href="/projects">打开历史资料</Link></div></section>;
}
