import Link from "next/link";
import type { Route } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { logoutAction } from "@/app/actions";
import { getCleanroomWorkspaces } from "@/lib/cleanroom-v1-api";
import { getCurrentUser } from "@/lib/session";
import { WorkspaceSettingsForm } from "./workspace-settings-form";
import { IntegrationSettingsForm } from "./integration-settings-form";
import { BrandFactsSettingsForm } from "./brand-facts-settings-form";
import { CollaborationSettings } from "./collaboration-settings";
import { SettingsSectionSwitcher } from "./settings-section-switcher";
import {
	readAgentRuntime,
	readBrandFacts,
	readLocalAgentNodes,
	readWorkspaceIntegrations,
	readWorkspaceInvitations,
	readWorkspaceMembers,
} from "./actions";
import styles from "./settings.module.css";

async function IntegrationSettingsSection({ workspaceId, readOnly }: { workspaceId: number; readOnly: boolean }) {
	const [integrations, agentRuntime] = await Promise.all([
		readWorkspaceIntegrations(workspaceId),
		readAgentRuntime(workspaceId),
	]);
	return <IntegrationSettingsForm workspaceId={workspaceId} initialSettings={integrations} initialRuntime={agentRuntime} readOnly={readOnly} />;
}

function IntegrationSettingsLoading() {
	return <section className={`${styles.integrationCard} ${styles.integrationLoading}`} aria-live="polite" aria-busy="true">
		<header className={styles.integrationHeader}><div><span className={styles.integrationEyebrow}>05 · Agent 与草稿交付</span><h2>本机 Codex 与文章同步</h2><p>品牌与事实设置已可使用；本机执行状态正在独立检查。</p></div><span className={styles.integrationPending}>正在检查</span></header>
		<div className={styles.integrationLoadingGrid} aria-hidden="true"><i /><i /></div>
		<p>正在核对本机 Agent 与同步配置，不会读取或显示密钥。</p>
	</section>;
}

export default async function GeoSettingsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
	const { workspaceId } = await params;
	const numericWorkspaceId = Number(workspaceId);
	if (!Number.isInteger(numericWorkspaceId) || numericWorkspaceId < 1) notFound();
	const [workspaces, brandFacts, members, invitations, localAgentNodes, currentUser] = await Promise.all([
		getCleanroomWorkspaces(),
		readBrandFacts(numericWorkspaceId),
		readWorkspaceMembers(numericWorkspaceId),
		readWorkspaceInvitations(numericWorkspaceId),
		readLocalAgentNodes(numericWorkspaceId),
		getCurrentUser(),
	]);
	const workspace = workspaces.find((item) => item.id === numericWorkspaceId);
	if (!workspace) notFound();
	const currentMembership = members.find((item) => item.user_id === currentUser?.id);
	const canManage = currentUser?.role === "super_admin" || currentMembership?.role === "owner" || currentMembership?.role === "admin";
	const canWrite = currentUser?.role === "super_admin" || Boolean(currentMembership && currentMembership.role !== "viewer");
	const roleLabel = currentMembership?.role === "owner" ? "工作区所有者" : currentMembership?.role === "admin" || currentUser?.role === "super_admin" ? "工作区管理员" : currentMembership?.role === "reviewer" ? "审核人员" : currentMembership?.role === "viewer" ? "只读成员" : "运营成员";
	const userInitial = (currentUser?.name || currentUser?.email || "U").trim().slice(0, 1).toUpperCase();
	return <main className={styles.page}>
		<header className={styles.header}>
			<div><h1>工作区设置</h1><span>管理当前工作区的品牌口径、成员权限、设备与交付设置。</span></div>
			<div className={styles.accountCard}>
				<span aria-hidden="true">{userInitial}</span>
				<div><strong>{currentUser?.name || currentUser?.email || "当前用户"}</strong><small>{roleLabel}</small></div>
				<form action={logoutAction}><button type="submit">退出登录</button></form>
			</div>
		</header>
		<SettingsSectionSwitcher
			basics={<div className={styles.basicsLayout}>
				<section className={`${styles.card} ${styles.brandIdentityCard}`}><header><div><h2>品牌识别</h2><p>指标、竞品对比和问题分析共用的品牌口径。</p></div></header><WorkspaceSettingsForm workspace={workspace} readOnly={!canWrite} /></section>
				<aside className={styles.basicsRail}>
					<section className={styles.routeGroup}><header><h2>模型与渠道</h2><p>平台管理员统一维护 API 与联网证据门禁。</p></header>{currentUser?.role === "super_admin" ? <Link className={styles.routeRow} href={`/admin/providers?workspace=${workspaceId}` as Route}><span aria-hidden="true">◇</span><div><b>管理模型与渠道</b><small>配置 API 连接和联网验证</small></div><strong>›</strong></Link> : <p className={styles.cardNote}>当前工作区仅使用已通过联网证据门禁的渠道。如需新增或更换 API，请联系平台管理员。</p>}</section>
					<section className={styles.routeGroup}><header><h2>真实运行</h2><p>查看采集任务、失败原因与证据归档。</p></header><div className={styles.routeStack}><Link className={styles.routeRow} href={`/geo/${workspaceId}/operations`}><span aria-hidden="true">⌁</span><div><b>运营状态</b><small>采集服务、队列与失败原因</small></div><strong>›</strong></Link><Link className={styles.routeRow} href={`/geo/${workspaceId}/questions`}><span aria-hidden="true">?</span><div><b>问题库</b><small>管理观测问题与跟踪范围</small></div><strong>›</strong></Link></div></section>
				</aside>
			</div>}
			collaboration={<CollaborationSettings workspaceId={workspace.id} initialMembers={members} initialInvitations={invitations} initialNodes={localAgentNodes} canManage={canManage} canEnrollAgent={canWrite} currentUserId={currentUser?.id ?? null} />}
			facts={<BrandFactsSettingsForm workspaceId={workspace.id} initialFacts={brandFacts} readOnly={!canWrite} />}
			agent={<Suspense fallback={<IntegrationSettingsLoading />}><IntegrationSettingsSection workspaceId={workspace.id} readOnly={!canWrite} /></Suspense>}
		/>
	</main>;
}
