"use client";

import { useMemo, useState, useTransition } from "react";

import type {
	GeoCollaborationCenter,
	GeoCollaborationChannel,
	GeoCollaborationEventType,
	GeoCollaborationItem,
	GeoCollaborationMember,
	GeoCollaborationNotificationPreview,
	GeoCollaborationProvider,
} from "@/lib/cleanroom-v1-api";
import {
	bindCollaborationMember,
	previewCollaborationNotification,
	saveCollaborationChannel,
	saveCollaborationNotificationPreferences,
	sendCollaborationNotification,
	verifyCollaborationChannel,
} from "./actions";
import type { CollaborationActionResult } from "./actions";
import styles from "./collaboration.module.css";

const providers: GeoCollaborationProvider[] = ["wecom", "feishu", "dingtalk"];
const providerNames: Record<GeoCollaborationProvider, string> = {
	wecom: "企业微信",
	feishu: "飞书",
	dingtalk: "钉钉",
};
const roleLabels: Record<string, string> = { owner: "所有者", admin: "管理员", operator: "运营", reviewer: "审核", viewer: "只读" };
const eventOptions: Array<{ key: GeoCollaborationEventType; label: string; detail: string }> = [
	{ key: "assigned", label: "任务分配", detail: "成为负责人时" },
	{ key: "due_soon", label: "即将到期", detail: "交付日期临近时" },
	{ key: "approval", label: "待审核", detail: "需要做出判断时" },
	{ key: "blocked", label: "工作阻塞", detail: "行动无法继续时" },
	{ key: "progress", label: "进度变化", detail: "关键节点更新时" },
	{ key: "manual_summary", label: "人工摘要", detail: "团队主动分享时" },
];

function ProviderLogo({ provider }: { provider: GeoCollaborationProvider }) {
	if (provider === "wecom") return <span className={styles.providerLogo} data-provider={provider}><img src="/brand/wechat.svg" alt="" /></span>;
	if (provider === "feishu") return <span className={styles.providerLogo} data-provider={provider} aria-hidden="true"><svg viewBox="0 0 32 32"><path fill="#3370ff" d="M15.8 4.2 9.5 10.5l6.3 6.3 6.3-6.3z"/><path fill="#00d6b9" d="m8.2 11.8-4 4 7.8 7.8 4-4z"/><path fill="#34c3ff" d="m22.8 11.8 5 5-8.8 8.8-5-5z"/><path fill="#ff5b71" d="m12.1 3.4 2.4 2.4-6.3 6.3-2.4-2.4z"/></svg></span>;
	return <span className={styles.providerLogo} data-provider={provider} aria-hidden="true"><svg viewBox="0 0 32 32"><path fill="currentColor" d="M25.9 5.3c-4.8 1.7-14.2 4-19.3 5.1-1.4.3-1.6 1.1-.2 1.7l5.5 2.2-2.7 2.3c-.8.7-.4 1.4.7 1.2l3.5-.6-2.2 7.6c-.3 1 .4 1.3 1.1.6l9.3-9.3-3.3-.2 7.9-9.4c.8-.9.6-1.6-.3-1.2Z"/></svg></span>;
}

function MemberAvatar({ member, large = false }: { member: GeoCollaborationMember; large?: boolean }) {
	return <span className={large ? styles.memberAvatarLarge : styles.memberAvatar}>{member.initial}</span>;
}

function channelState(channel: GeoCollaborationChannel) {
	if (channel.status === "connected") return "已连接";
	if (channel.status === "configured") return "待验证";
	if (channel.status === "error") return "连接异常";
	return "未连接";
}

function formatTime(value?: string | null) {
	if (!value) return "尚无记录";
	return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

type ConnectionDraft = {
	connection_mode: "webhook" | "app";
	webhook_url: string;
	corp_id: string;
	app_id: string;
	app_key: string;
	agent_id: string;
	app_secret: string;
	display_name: string;
	deep_link_base_url: string;
};

const emptyConnection: ConnectionDraft = {
	connection_mode: "webhook", webhook_url: "", corp_id: "", app_id: "", app_key: "", agent_id: "", app_secret: "", display_name: "", deep_link_base_url: "",
};

function actionData<T>(result: CollaborationActionResult<T>): T {
	if (!result.ok) throw new Error(result.error);
	return result.data;
}

function ConnectionManager({ workspaceId, data, onData, onClose }: { workspaceId: number; data: GeoCollaborationCenter; onData: (value: GeoCollaborationCenter) => void; onClose: () => void }) {
	const [provider, setProvider] = useState<GeoCollaborationProvider>("wecom");
	const channel = data.channels.find((item) => item.provider === provider)!;
	const [draft, setDraft] = useState<ConnectionDraft>({ ...emptyConnection, connection_mode: channel.connection_mode || "webhook", display_name: channel.display_name || "", deep_link_base_url: channel.deep_link_base_url || "" });
	const [error, setError] = useState<string | null>(null);
	const [busy, startTransition] = useTransition();
	const choose = (value: GeoCollaborationProvider) => {
		const next = data.channels.find((item) => item.provider === value)!;
		setProvider(value);
		setDraft({ ...emptyConnection, connection_mode: next.connection_mode || "webhook", display_name: next.display_name || "", deep_link_base_url: next.deep_link_base_url || "" });
		setError(null);
	};
	const update = (key: keyof ConnectionDraft, value: string) => setDraft((current) => ({ ...current, [key]: value }));
	const save = () => startTransition(async () => {
		setError(null);
		try {
			const next = actionData(await saveCollaborationChannel(workspaceId, provider, {
				connection_mode: draft.connection_mode,
				webhook_url: draft.webhook_url || null,
				corp_id: draft.corp_id || null,
				app_id: draft.app_id || null,
				app_key: draft.app_key || null,
				agent_id: draft.agent_id || null,
				app_secret: draft.app_secret || null,
				display_name: draft.display_name || null,
				deep_link_base_url: draft.deep_link_base_url || null,
			}));
			onData(next);
			setDraft((current) => ({ ...current, app_secret: "", webhook_url: "" }));
		} catch (value) { setError(value instanceof Error ? value.message : "保存失败"); }
	});
	const test = () => startTransition(async () => {
		setError(null);
		try { onData(actionData(await verifyCollaborationChannel(workspaceId, provider))); }
		catch (value) { setError(value instanceof Error ? value.message : "官方平台未确认连接"); }
	});
	return <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
		<section className={styles.connectionModal} role="dialog" aria-modal="true" aria-label="管理办公平台连接">
			<header><div><span>协作入口</span><h2>管理办公平台连接</h2><p>GEO 保留完整证据，办公平台只接收摘要和入口。</p></div><button type="button" onClick={onClose} aria-label="关闭">×</button></header>
			<div className={styles.connectionBody}>
				<nav>{providers.map((item) => { const value = data.channels.find((entry) => entry.provider === item)!; return <button type="button" key={item} data-active={item === provider} onClick={() => choose(item)}><ProviderLogo provider={item} /><span><b>{providerNames[item]}</b><small data-state={value.status}>{channelState(value)}</small></span><i>›</i></button>; })}</nav>
				<form onSubmit={(event) => { event.preventDefault(); save(); }}>
					<div className={styles.formHeading}><ProviderLogo provider={provider} /><div><h3>{providerNames[provider]}</h3><p>{channel.status === "connected" ? `最近验证 ${formatTime(channel.last_tested_at)}` : "保存后需再执行一次官方连接验证"}</p></div><em data-state={channel.status}>{channelState(channel)}</em></div>
					<div className={styles.modeSwitch}><button type="button" data-active={draft.connection_mode === "webhook"} onClick={() => update("connection_mode", "webhook")}>群机器人<small>快速广播</small></button><button type="button" data-active={draft.connection_mode === "app"} onClick={() => update("connection_mode", "app")}>企业自建应用<small>成员绑定与定向通知</small></button></div>
					{draft.connection_mode === "webhook" ? <label><span>Webhook 地址</span><input type="url" value={draft.webhook_url} onChange={(event) => update("webhook_url", event.target.value)} placeholder={channel.configured_fields.includes("webhook_url") ? "已安全保存；输入新地址可替换" : "粘贴官方机器人 HTTPS 地址"} required={!channel.configured_fields.includes("webhook_url")} /></label> : <div className={styles.credentialGrid}>
						{provider === "wecom" ? <label><span>Corp ID</span><input value={draft.corp_id} onChange={(event) => update("corp_id", event.target.value)} placeholder={channel.configured_fields.includes("corp_id") ? "已安全保存" : undefined} required={!channel.configured_fields.includes("corp_id")} /></label> : null}
						{provider === "feishu" ? <label><span>App ID</span><input value={draft.app_id} onChange={(event) => update("app_id", event.target.value)} placeholder={channel.configured_fields.includes("app_id") ? "已安全保存" : undefined} required={!channel.configured_fields.includes("app_id")} /></label> : null}
						{provider === "dingtalk" ? <label><span>App Key</span><input value={draft.app_key} onChange={(event) => update("app_key", event.target.value)} placeholder={channel.configured_fields.includes("app_key") ? "已安全保存" : undefined} required={!channel.configured_fields.includes("app_key")} /></label> : null}
						{provider !== "feishu" ? <label><span>Agent ID</span><input inputMode="numeric" value={draft.agent_id} onChange={(event) => update("agent_id", event.target.value)} placeholder={channel.configured_fields.includes("agent_id") ? "已安全保存" : undefined} required={!channel.configured_fields.includes("agent_id")} /></label> : null}
						<label><span>App Secret</span><input type="password" autoComplete="new-password" value={draft.app_secret} onChange={(event) => update("app_secret", event.target.value)} placeholder={channel.configured_fields.includes("app_secret") ? "已安全保存；输入新密钥可替换" : "仅加密保存，不会回显"} required={!channel.configured_fields.includes("app_secret")} /></label>
					</div>}
					<label><span>连接名称</span><input value={draft.display_name} onChange={(event) => update("display_name", event.target.value)} placeholder="例如：品牌增长组" /></label>
					<label><span>GEO 公网地址 <small>用于消息深链，可空</small></span><input type="url" value={draft.deep_link_base_url} onChange={(event) => update("deep_link_base_url", event.target.value)} placeholder="https://geo.example.com" /></label>
					<div className={styles.capabilityNote}><b>{draft.connection_mode === "app" ? "可定向到成员" : "发送到群聊"}</b><p>{draft.connection_mode === "app" ? "连接后仍需逐人核验平台用户 ID。" : "群机器人不代表工作区成员身份已绑定。"}</p></div>
					{error ? <p className={styles.formError} role="alert">{error}</p> : null}
					<footer><button type="button" onClick={test} disabled={busy || channel.status === "disconnected"}>{busy ? "请稍候…" : "验证官方连接"}</button><button type="submit" disabled={busy}>{busy ? "保存中…" : "保存配置"}</button></footer>
				</form>
			</div>
		</section>
	</div>;
}

function BindPanel({ workspaceId, member, channel, onData, onClose }: { workspaceId: number; member: GeoCollaborationMember; channel: GeoCollaborationChannel; onData: (value: GeoCollaborationCenter) => void; onClose: () => void }) {
	const [externalId, setExternalId] = useState("");
	const [idType, setIdType] = useState<"user_id" | "open_id" | "union_id">(channel.provider === "feishu" ? "open_id" : "user_id");
	const [error, setError] = useState<string | null>(null);
	const [busy, startTransition] = useTransition();
	const submit = () => startTransition(async () => {
		setError(null);
		try { onData(actionData(await bindCollaborationMember(workspaceId, member.id, channel.provider, externalId, idType))); onClose(); }
		catch (value) { setError(value instanceof Error ? value.message : "官方通讯录未确认该成员"); }
	});
	return <div className={styles.inlinePanel}><header><div><ProviderLogo provider={channel.provider} /><span><b>绑定{providerNames[channel.provider]}</b><small>{member.name} · 官方通讯录验证</small></span></div><button type="button" onClick={onClose}>×</button></header>
		{channel.connection_mode !== "app" || channel.status !== "connected" ? <p className={styles.blockedText}>请先在“管理连接”中用企业自建应用连接{providerNames[channel.provider]}。</p> : <form onSubmit={(event) => { event.preventDefault(); submit(); }}><label><span>平台用户 ID</span><input autoFocus value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder="请从企业管理后台复制" required /></label>{channel.provider === "feishu" ? <label><span>ID 类型</span><select value={idType} onChange={(event) => setIdType(event.target.value as typeof idType)}><option value="open_id">Open ID</option><option value="user_id">User ID</option><option value="union_id">Union ID</option></select></label> : null}<small>保存前会请求官方通讯录；只有查到该用户才会标记“已验证”。</small>{error ? <p className={styles.formError}>{error}</p> : null}<footer><button type="button" onClick={onClose}>取消</button><button type="submit" disabled={busy || !externalId.trim()}>{busy ? "验证中…" : "验证并绑定"}</button></footer></form>}
	</div>;
}

function SendPanel({ workspaceId, member, work, channels, onData, onClose }: { workspaceId: number; member: GeoCollaborationMember; work: GeoCollaborationItem[]; channels: GeoCollaborationChannel[]; onData: (value: GeoCollaborationCenter) => void; onClose: () => void }) {
	const [workKey, setWorkKey] = useState(work[0]?.key || "");
	const [selectedProviders, setSelectedProviders] = useState<GeoCollaborationProvider[]>(providers.filter((provider) => member.notification_preferences.provider_settings[provider]));
	const [note, setNote] = useState("");
	const [preview, setPreview] = useState<GeoCollaborationNotificationPreview | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [busy, startTransition] = useTransition();
	const selected = work.find((item) => item.key === workKey);
	const draft = selected ? { recipient_user_id: member.id, context_type: selected.context_type, context_id: selected.context_id, event_type: "manual_summary" as const, providers: selectedProviders, note } : null;
	const loadPreview = () => draft && startTransition(async () => { setError(null); try { setPreview(actionData(await previewCollaborationNotification(workspaceId, draft))); } catch (value) { setError(value instanceof Error ? value.message : "无法生成预览"); } });
	const send = () => draft && startTransition(async () => { setError(null); try { onData(actionData(await sendCollaborationNotification(workspaceId, { ...draft, idempotency_key: `office-${member.id}-${selected!.key}-${crypto.randomUUID()}` }))); onClose(); } catch (value) { setError(value instanceof Error ? value.message : "发送失败"); } });
	return <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className={styles.sendModal} role="dialog" aria-modal="true" aria-label="发送 GEO 进度摘要"><header><div><span>发送前确认</span><h2>把工作进度发给 {member.name}</h2></div><button type="button" onClick={onClose}>×</button></header>
		{!work.length ? <div className={styles.emptyState}><b>还没有相关工作</b><p>先将该成员设为负责人或参与人。</p></div> : <div className={styles.sendBody}><label><span>选择真实工作</span><select value={workKey} onChange={(event) => { setWorkKey(event.target.value); setPreview(null); }}>{work.map((item) => <option key={item.key} value={item.key}>{item.title}</option>)}</select></label><fieldset><legend>发送入口</legend>{channels.map((channel) => { const selectedValue = selectedProviders.includes(channel.provider); return <button type="button" key={channel.provider} data-selected={selectedValue} onClick={() => { setSelectedProviders((current) => selectedValue ? current.filter((item) => item !== channel.provider) : [...current, channel.provider]); setPreview(null); }}><ProviderLogo provider={channel.provider} /><span><b>{channel.label}</b><small>{channelState(channel)}</small></span><i>{selectedValue ? "✓" : ""}</i></button>; })}</fieldset><label><span>补充说明 <small>可空</small></span><textarea value={note} onChange={(event) => { setNote(event.target.value); setPreview(null); }} maxLength={500} placeholder="仅补充需要对方关注的事" /></label>
		{preview ? <section className={styles.previewCard}><header><b>发送预览</b><small>尚未写入任何外部平台</small></header><pre>{preview.message_preview}</pre><div>{preview.providers.map((item) => <p key={item.provider} data-ready={item.ready}><ProviderLogo provider={item.provider} /><span><b>{item.label}</b><small>{item.ready ? item.status_fact : item.reason}</small></span><em>{item.ready ? "可发送" : "不可发送"}</em></p>)}</div></section> : null}
		{error ? <p className={styles.formError}>{error}</p> : null}<footer><button type="button" onClick={onClose}>取消</button>{preview ? <button type="button" disabled={busy || preview.providers.some((item) => !item.ready)} onClick={send}>{busy ? "发送中…" : "确认发送"}</button> : <button type="button" disabled={busy || !selected || !selectedProviders.length} onClick={loadPreview}>{busy ? "生成中…" : "预览消息"}</button>}</footer></div>}
	</section></div>;
}

export function CollaborationContacts({ workspaceId, data, onData, onOpenWork }: { workspaceId: number; data: GeoCollaborationCenter; onData: (value: GeoCollaborationCenter) => void; onOpenWork: (item: GeoCollaborationItem) => void }) {
	const [query, setQuery] = useState("");
	const [filter, setFilter] = useState<"all" | "linked" | "unlinked">("all");
	const [selectedId, setSelectedId] = useState(data.members[0]?.id || 0);
	const [manageConnections, setManageConnections] = useState(false);
	const [bindingProvider, setBindingProvider] = useState<GeoCollaborationProvider | null>(null);
	const [showPreferences, setShowPreferences] = useState(false);
	const [showSend, setShowSend] = useState(false);
	const [prefSaving, startPrefTransition] = useTransition();
	const [notice, setNotice] = useState<string | null>(null);
	const members = useMemo(() => data.members.filter((member) => {
		const matches = `${member.name} ${member.email} ${roleLabels[member.role] || member.role}`.toLowerCase().includes(query.toLowerCase());
		const linked = member.bindings.some((item) => item.status === "verified");
		return matches && (filter === "all" || (filter === "linked" ? linked : !linked));
	}), [data.members, filter, query]);
	const member = members.find((item) => item.id === selectedId) || members[0] || data.members.find((item) => item.id === selectedId) || data.members[0];
	const relatedWork = useMemo(() => member ? data.items.filter((item) => item.assignee_user_id === member.id || item.participant_user_ids.includes(member.id)) : [], [data.items, member]);
	if (!member) return <section className={styles.contactsEmpty}><b>工作区还没有成员</b><p>请先在管理页邀请真实账号。</p></section>;
	const savePreferences = (providerSettings = member.notification_preferences.provider_settings, eventTypes = member.notification_preferences.event_types) => startPrefTransition(async () => {
		setNotice(null);
		try { onData(actionData(await saveCollaborationNotificationPreferences(workspaceId, member.id, providerSettings, eventTypes))); setNotice("通知偏好已保存并可回读。"); }
		catch (value) { setNotice(value instanceof Error ? value.message : "保存失败"); }
	});
	return <section className={styles.memberWorkspace}>
		<header className={styles.integrationStrip}><div><span>办公入口</span><b>让同事在熟悉的工具里看到 GEO 进度</b><small>详细证据仍保留在 GEO，不再造一个办公空间。</small></div><div>{data.channels.map((channel) => <button type="button" key={channel.provider} onClick={() => setManageConnections(true)}><ProviderLogo provider={channel.provider} /><span><b>{channel.label}</b><small data-state={channel.status}>{channelState(channel)}</small></span></button>)}</div><button type="button" onClick={() => setManageConnections(true)}>管理连接</button></header>
		<div className={styles.memberColumns}>
			<aside className={styles.memberList}><header><div><b>协作成员</b><small>{data.members.length} 位真实账号</small></div></header><label><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索姓名、邮箱或角色" /></label><nav><button type="button" data-active={filter === "all"} onClick={() => setFilter("all")}>全部</button><button type="button" data-active={filter === "linked"} onClick={() => setFilter("linked")}>已绑定</button><button type="button" data-active={filter === "unlinked"} onClick={() => setFilter("unlinked")}>待绑定</button></nav><div>{members.length ? members.map((item) => <button type="button" key={item.id} data-active={item.id === member.id} onClick={() => { setSelectedId(item.id); setBindingProvider(null); setShowPreferences(false); }}><MemberAvatar member={item} /><span><b>{item.name}{item.id === data.current_user_id ? "（我）" : ""}</b><small>{roleLabels[item.role] || item.role}</small></span><i>{item.bindings.length ? `${item.bindings.length} 个入口` : "待绑定"}</i></button>) : <p>没有符合条件的成员。</p>}</div><footer>只展示已加入当前工作区的真实账号</footer></aside>
			<main className={styles.memberDetail}><header><MemberAvatar member={member} large /><div><h2>{member.name}{member.id === data.current_user_id ? "（我）" : ""}</h2><p>{member.email}</p><span>{roleLabels[member.role] || member.role}</span></div><button type="button" onClick={() => setShowSend(true)}>发送进度摘要</button></header>
				<section className={styles.bindingSection}><header><div><h3>办公入口绑定</h3><p>每个平台独立验证，不共享“已登录”状态。</p></div></header><div>{data.channels.map((channel) => { const binding = member.bindings.find((item) => item.provider === channel.provider); return <article key={channel.provider}><ProviderLogo provider={channel.provider} /><div><b>{channel.label}</b><small>{binding ? `${binding.external_display_name || "平台账号"} · ${formatTime(binding.verified_at)} 验证` : channel.connection_mode === "webhook" ? "当前仅群机器人，不能绑定成员" : "尚未核验平台身份"}</small></div><em data-state={binding ? "connected" : "disconnected"}>{binding ? "已验证" : "未绑定"}</em><button type="button" onClick={() => setBindingProvider(channel.provider)}>{binding ? "重新验证" : "绑定"}</button></article>; })}</div>{bindingProvider ? <BindPanel workspaceId={workspaceId} member={member} channel={data.channels.find((item) => item.provider === bindingProvider)!} onData={onData} onClose={() => setBindingProvider(null)} /> : null}</section>
				<section className={styles.preferenceSummary}><header><div><h3>通知偏好</h3><p>只在必要时打扰成员。</p></div><button type="button" onClick={() => setShowPreferences((current) => !current)}>{showPreferences ? "收起" : "编辑"}</button></header><div className={styles.preferenceProviders}>{data.channels.map((channel) => <button type="button" key={channel.provider} data-enabled={Boolean(member.notification_preferences.provider_settings[channel.provider])} onClick={() => savePreferences({ ...member.notification_preferences.provider_settings, [channel.provider]: !member.notification_preferences.provider_settings[channel.provider] })} disabled={prefSaving}><ProviderLogo provider={channel.provider} /><span>{channel.label}</span><i /></button>)}</div>{showPreferences ? <div className={styles.eventPreferences}>{eventOptions.map((option) => { const active = member.notification_preferences.event_types.includes(option.key); return <label key={option.key}><input type="checkbox" checked={active} onChange={() => { const next = active ? member.notification_preferences.event_types.filter((item) => item !== option.key) : [...member.notification_preferences.event_types, option.key]; savePreferences(member.notification_preferences.provider_settings, next); }} /><span><b>{option.label}</b><small>{option.detail}</small></span></label>; })}</div> : null}{notice ? <p className={styles.savedNotice}>{notice}</p> : null}</section>
			</main>
			<aside className={styles.memberContext}><section><header><div><h3>相关工作</h3><small>{relatedWork.length} 项</small></div></header><div className={styles.relatedWork}>{relatedWork.slice(0, 8).map((item) => <button type="button" key={item.key} onClick={() => onOpenWork(item)}><span data-type={item.context_type}>{item.context_type === "action" ? "行" : item.context_type === "question" ? "问" : item.context_type === "alert" ? "!" : "观"}</span><div><b>{item.title}</b><small>{item.category} · {item.progress}%</small></div><i>›</i></button>)}{!relatedWork.length ? <p>尚未被指派或加入具体工作。</p> : null}</div></section><section><header><div><h3>最近外部通知</h3><small>可回读证据</small></div></header><div className={styles.deliveryList}>{member.recent_deliveries.map((delivery) => <article key={delivery.id}><ProviderLogo provider={delivery.provider} /><div><b>{providerNames[delivery.provider]}</b><small>{formatTime(delivery.attempted_at)}</small></div><em data-state={delivery.status}>{delivery.status === "provider_accepted" ? "平台已接受" : delivery.status === "failed" ? "发送失败" : "发送中"}</em></article>)}{!member.recent_deliveries.length ? <p>还没有对外发送记录。</p> : null}</div><small className={styles.truthNote}>“平台已接受”不等于成员已读。</small></section></aside>
		</div>
		{manageConnections ? <ConnectionManager workspaceId={workspaceId} data={data} onData={onData} onClose={() => setManageConnections(false)} /> : null}
		{showSend ? <SendPanel workspaceId={workspaceId} member={member} work={relatedWork} channels={data.channels} onData={onData} onClose={() => setShowSend(false)} /> : null}
	</section>;
}
