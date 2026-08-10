import { LoginShowcaseCarousel } from "@/app/login/login-showcase-carousel";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type InvitePreview = {
	workspace_id: number;
	workspace_name: string;
	email_hint: string;
	role: "owner" | "admin" | "operator" | "reviewer" | "viewer";
	expires_at: string;
	status: string;
};

const roleLabels: Record<InvitePreview["role"], string> = {
	owner: "所有者",
	admin: "管理员",
	operator: "运营",
	reviewer: "审核",
	viewer: "只读",
};

export default async function InvitePage({
	params,
	searchParams,
}: {
	params: Promise<{ token: string }>;
	searchParams: Promise<{ error?: string }>;
}) {
	const { token } = await params;
	const query = await searchParams;
	const response = await fetch(`${API_BASE_URL}/api/auth/invitations/${encodeURIComponent(token)}`, { cache: "no-store" });
	const invitation = response.ok ? await response.json() as InvitePreview : null;
	return <main className="cq-auth-page">
		<section className="cq-auth-intro"><div className="cq-auth-grain" aria-hidden="true" /><div className="cq-auth-carousel-stage"><LoginShowcaseCarousel /></div></section>
		<section className="cq-auth-panel-wrap"><div className="cq-auth-card"><div className="cq-auth-card-heading"><div className="cq-auth-panel-brand"><i aria-hidden="true"><b /><b /><b /><b /></i><span>春秋元泉</span></div><h2>{invitation ? `加入 ${invitation.workspace_name}` : "邀请不可用"}</h2><p>{invitation ? `${invitation.email_hint} 将以“${roleLabels[invitation.role]}”身份加入。已有账号请填写原密码；新成员将直接创建本地工作账号。` : "这个邀请可能已过期、被撤销或已经使用。请联系工作区管理员重新生成。"}</p></div>
			{query.error === "unavailable" ? <div className="cq-login-notice" role="status">账号服务暂时无法连接，请稍后重试。</div> : query.error ? <div className="cq-login-notice" role="status">无法接受邀请，请确认密码正确且账号属于同一组织。</div> : null}
			{invitation ? <form action="/api/session/invite" method="post" className="cq-login-form"><input type="hidden" name="token" value={token} /><div><label htmlFor="invite-name">姓名</label><input id="invite-name" name="name" autoComplete="name" required /></div><div><label htmlFor="invite-password">账号密码</label><input id="invite-password" name="password" type="password" autoComplete="current-password" minLength={12} required /></div><button className="cq-primary" type="submit"><span>加入工作区</span><b aria-hidden="true">↗</b></button></form> : null}
		</div></section>
	</main>;
}
