"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type {
	LocalAgentNode,
	WorkspaceInvitation,
	WorkspaceMembership,
} from "@/lib/cleanroom-v1-api";
import {
	cancelWorkspaceInvitation,
	changeWorkspaceMemberRole,
	enrollLocalAgent,
	inviteWorkspaceMember,
	removeLocalAgent,
	removeWorkspaceMember,
} from "./actions";
import styles from "./settings.module.css";

const roleLabels: Record<WorkspaceMembership["role"], string> = {
	owner: "所有者",
	admin: "管理员",
	operator: "运营",
	reviewer: "审核",
	viewer: "只读",
};

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? value as Record<string, unknown>
		: {};
}

function statusText(node: LocalAgentNode) {
	const health = asRecord(node.health);
	const egolite = asRecord(health.egolite);
	const codex = asRecord(health.codex);
	const items = [
		node.online ? "在线" : "离线",
		egolite.running === true ? "EgoLite 运行中" : "EgoLite 未运行",
		codex.logged_in === true ? "Codex 已登录" : "Codex 未确认登录",
	];
	return items.join(" · ");
}

export function CollaborationSettings({
	workspaceId,
	initialMembers,
	initialInvitations,
	initialNodes,
	canManage,
	canEnrollAgent,
	currentUserId,
}: {
	workspaceId: number;
	initialMembers: WorkspaceMembership[];
	initialInvitations: WorkspaceInvitation[];
	initialNodes: LocalAgentNode[];
	canManage: boolean;
	canEnrollAgent: boolean;
	currentUserId: number | null;
}) {
	const router = useRouter();
	const [pending, startTransition] = useTransition();
	const [email, setEmail] = useState("");
	const [role, setRole] = useState<WorkspaceMembership["role"]>("operator");
	const [inviteUrl, setInviteUrl] = useState("");
	const [agentCommand, setAgentCommand] = useState("");
	const [message, setMessage] = useState("");

	function run(action: () => Promise<void>) {
		setMessage("");
		startTransition(async () => {
			try {
				await action();
				router.refresh();
			} catch (error) {
				setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
			}
		});
	}

	return <section className={styles.collaborationCard}>
		<header className={styles.collaborationHeader}>
			<div><span>04 · 工作区与设备</span><h2>团队成员和本地执行环境</h2><p>主机保存共享数据；EgoLite 登录态、浏览器 Cookie 与本机 Codex 身份始终留在成员电脑。</p></div>
			<b>{initialMembers.length} 位成员</b>
		</header>

		{message ? <p className={styles.collaborationMessage} role="status">{message}</p> : null}

		<div className={styles.collaborationGrid}>
			<div className={styles.teamPanel}>
				<div className={styles.panelTitle}><div><h3>工作区成员</h3><p>同一公司也不会自动获得这个工作区的数据。</p></div></div>
				<div className={styles.memberList}>
					{initialMembers.map((member) => <div className={styles.memberRow} key={member.id}>
						<div className={styles.memberAvatar}>{member.user.name.slice(0, 1).toUpperCase()}</div>
						<div className={styles.memberIdentity}><strong>{member.user.name}</strong><span>{member.user.email}</span></div>
						{canManage ? <select value={member.role} disabled={pending} onChange={(event) => run(async () => {
							await changeWorkspaceMemberRole(workspaceId, member.id, event.target.value as WorkspaceMembership["role"]);
						})} aria-label={`修改 ${member.user.name} 的角色`}>
							{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
						</select> : <em>{roleLabels[member.role]}</em>}
						{canManage && member.role !== "owner" ? <button type="button" disabled={pending} onClick={() => run(async () => removeWorkspaceMember(workspaceId, member.id))}>移除</button> : null}
					</div>)}
				</div>

				{canManage ? <form className={styles.inviteForm} onSubmit={(event) => {
					event.preventDefault();
					run(async () => {
						const invitation = await inviteWorkspaceMember(workspaceId, { email, role });
						setInviteUrl(`${window.location.origin}${invitation.invite_path}`);
						setEmail("");
					});
				}}>
					<label><span>邀请成员</span><input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" /></label>
					<label><span>权限</span><select value={role} onChange={(event) => setRole(event.target.value as WorkspaceMembership["role"])}><option value="admin">管理员</option><option value="operator">运营</option><option value="reviewer">审核</option><option value="viewer">只读</option></select></label>
					<button className={styles.primarySmall} type="submit" disabled={pending}>生成邀请链接</button>
				</form> : null}
				{inviteUrl ? <div className={styles.oneTimeSecret}><span>一次性邀请链接</span><code>{inviteUrl}</code><button type="button" onClick={() => navigator.clipboard.writeText(inviteUrl)}>复制</button></div> : null}
				{initialInvitations.some((item) => item.status === "pending") ? <div className={styles.pendingInvites}>{initialInvitations.filter((item) => item.status === "pending").map((item) => <div key={item.id}><span>{item.email} · {roleLabels[item.role]}</span>{canManage ? <button type="button" onClick={() => run(async () => cancelWorkspaceInvitation(workspaceId, item.id))}>撤销</button> : null}</div>)}</div> : null}
			</div>

			<div className={styles.agentPanel}>
				<div className={styles.panelTitle}><div><h3>Local Agent</h3><p>采用开源 Runner 的出站注册模式，不开放成员电脑的控制端口。</p></div><i>{initialNodes.some((node) => node.online) ? "有设备在线" : "暂无在线设备"}</i></div>
				<div className={styles.agentBoundary}><b>当前阶段：状态连接</b><span>节点在线不代表任务已执行。现有 Agent 任务仍由主机运行；本地节点暂不接受远程命令。</span></div>
				<div className={styles.agentList}>
					{initialNodes.length ? initialNodes.map((node) => <div className={styles.agentRow} key={node.id}><i className={node.online ? styles.onlineDot : styles.offlineDot} /><div><strong>{node.name}</strong><span>{node.hostname} · {node.platform}</span><small>{statusText(node)}</small></div>{node.status !== "active" ? <em>已停用</em> : canManage || node.owner_user_id === currentUserId ? <button type="button" disabled={pending} onClick={() => run(async () => removeLocalAgent(workspaceId, node.id))}>停用</button> : null}</div>) : <div className={styles.emptyAgent}>尚未连接成员电脑。本页仍可通过局域网使用，只是无法感知那台电脑的 EgoLite/Codex 状态。</div>}
				</div>
				{canEnrollAgent ? <button className={styles.agentEnrollButton} type="button" disabled={pending} onClick={() => run(async () => {
					const enrollment = await enrollLocalAgent(workspaceId);
					setAgentCommand(enrollment.command_hint);
				})}>生成 20 分钟设备接入码</button> : null}
				{agentCommand ? <div className={styles.oneTimeSecret}><span>在成员电脑的项目目录运行</span><code>{agentCommand}</code><button type="button" onClick={() => navigator.clipboard.writeText(agentCommand)}>复制</button></div> : null}
			</div>
		</div>
	</section>;
}
