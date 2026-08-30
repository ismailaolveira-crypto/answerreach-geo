"use client";

import Link from "next/link";
import type { Route } from "next";
import * as Popover from "@radix-ui/react-popover";
import { useEffect, useMemo, useRef, useState, useTransition, type KeyboardEvent } from "react";

import type {
	GeoCollaborationActivity,
	GeoCollaborationCenter as CollaborationData,
	GeoCollaborationAttachmentRef,
	GeoCollaborationItem,
	GeoCollaborationMessage,
	GeoCollaborationMember,
	GeoCollaborationShareDraft,
} from "@/lib/cleanroom-v1-api";
import {
	loadCollaborationCenter,
	markCollaborationRead,
	saveCollaborationWorkInfo,
} from "./actions";
import { CollaborationContacts } from "./collaboration-contacts";
import styles from "./collaboration.module.css";

type Tab = "discussions" | "contacts";
type SendState = "idle" | "sending" | "retry";

async function fetchJsonWithTimeout<T>(url: string, init?: RequestInit, timeoutMs = 12_000): Promise<T> {
	const controller = new AbortController();
	const timer = window.setTimeout(() => controller.abort(), timeoutMs);
	try {
		const response = await fetch(url, { ...init, cache: "no-store", signal: controller.signal });
		const value = await response.json().catch(() => null) as (T & { detail?: string }) | null;
		if (!response.ok || !value) throw new Error(value?.detail || `请求失败（${response.status}）`);
		return value;
	} catch (error) {
		if (error instanceof DOMException && error.name === "AbortError") throw new Error("发送超时，未确认的消息可安全重试");
		throw error;
	} finally {
		window.clearTimeout(timer);
	}
}

const statusLabels: Record<string, string> = {
	proposed: "待确认",
	accepted: "已接收",
	in_progress: "进行中",
	awaiting_approval: "审核内容",
	executing: "执行中",
	partially_completed: "部分完成",
	completed: "已完成",
	blocked: "已阻塞",
	changes_requested: "待修改",
	cancelled: "已取消",
	selected: "待开始",
	brief_ready: "待审核",
	reviewing: "审核中",
	awaiting_readback: "待核验",
	open: "告警",
	resolved: "已处理",
	present: "品牌出现",
	absent: "品牌缺席",
	unknown: "待判断",
};

const eventLabels: Record<string, string> = {
	action_accepted: "行动已接收",
	action_assigned: "负责人已更新",
	action_rescheduled: "交付时间已更新",
	action_blocked: "行动被记录为阻塞",
	action_unblocked: "行动已解除阻塞",
	action_target_transitioned: "交付进度已更新",
	action_approval_requested: "已发起审批",
	action_approval_decided: "审批已处理",
	opportunity_selected: "优先机会已选入行动",
	action_self_approved: "已完成本人审批",
};
const roleLabels: Record<string, string> = { owner: "所有者", admin: "管理员", operator: "运营", reviewer: "审核", viewer: "只读" };
const moduleLabels: Record<string, string> = { decision: "决策地图", source: "信源地图", competitor: "竞品对比", question: "问题库", actions: "优化行动", content: "内容中心", results: "效果与 ROI", operations: "运营状态", alerts: "变化告警", settings: "工作区管理" };

function formatDate(value?: string | null, includeTime = false) {
	if (!value) return "未设置";
	return new Intl.DateTimeFormat("zh-CN", includeTime
		? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
		: { month: "long", day: "numeric" }).format(new Date(value));
}

function daysLeft(value?: string | null) {
	if (!value) return null;
	return Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
}

function dateInputValue(value?: string | null) {
	if (!value) return "";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "";
	return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function dateInputIso(value: string) {
	return value ? new Date(`${value}T12:00:00`).toISOString() : null;
}

function itemTone(item: GeoCollaborationItem) {
	if (item.context_type === "alert" || item.status === "blocked") return "orange";
	if (item.context_type === "evidence") return "cyan";
	if (item.pending_approvals > 0 || item.status === "awaiting_approval") return "purple";
	if (item.category.includes("官网")) return "cyan";
	return "blue";
}

function WorkIcon({ item }: { item: GeoCollaborationItem }) {
	return <span className={styles.workIcon} data-tone={itemTone(item)} aria-hidden="true">
		{item.context_type === "alert" ? "!" : item.context_type === "question" ? "?" : item.context_type === "evidence" ? "✦" : item.category.includes("官网") ? "◇" : item.category.includes("信源") ? "⊕" : "≡"}
	</span>;
}

function WorkRow({ item, active, onSelect }: { item: GeoCollaborationItem; active: boolean; onSelect: () => void }) {
	return <button type="button" className={active ? styles.selectedThread : ""} onClick={onSelect}>
		<WorkIcon item={item} /><span><strong>{item.title}</strong><em data-tone={itemTone(item)}>{item.attention_reason || (item.context_type === "question" ? "问题" : statusLabels[item.status] || item.status)}</em><small>{item.last_message_preview ? `${item.last_message_author_name || "团队"}：${item.last_message_preview}` : item.context_type === "question" ? "发送第一条消息开始讨论" : item.context_type === "evidence" ? `${item.model_keys.length} 个模型 · ${item.evidence_count} 个引用来源` : `${item.assignee_name || (item.context_type === "alert" ? "系统" : "待分配")} · ${item.progress}% 进度`}</small></span>{item.unread_count ? <b>{item.unread_count}</b> : <time>{formatDate(item.last_activity_at, true)}</time>}
	</button>;
}

function Avatar({ name, initial, small = false }: { name?: string | null; initial?: string; small?: boolean }) {
	return <span className={small ? styles.avatarSmall : styles.avatar} aria-label={name || "系统"}>
		{initial || (name || "系").slice(0, 1)}
	</span>;
}

function EmptyThread() {
	return <div className={styles.emptyThread}>
		<span aria-hidden="true">“</span>
		<strong>还没有团队讨论</strong>
		<p>需要确认判断、证据或下一步时，在下方 @ 一位同事开始。</p>
	</div>;
}

function ThreadTimeline({ data }: { data: CollaborationData }) {
	const detail = data.selected_detail;
	const entries = detail?.messages || [];
	if (!entries.length) return <EmptyThread />;
	return <div className={styles.timeline}>
		{entries.map((entry) => <MessageEntry key={`message-${entry.id}`} entry={entry} members={data.members} />)}
	</div>;
}

function ActivityDigest({ activity }: { activity: GeoCollaborationActivity[] }) {
	if (!activity.length) return null;
	return <details className={styles.activityDigest}>
		<summary>工作动态 <b>{activity.length}</b><span>展开</span></summary>
		<div>{activity.map((entry) => <ActivityEntry key={entry.id} entry={entry} />)}</div>
	</details>;
}

function MentionedBody({ body, mentionIds, members }: { body: string; mentionIds: number[]; members: GeoCollaborationMember[] }) {
	if (!body) return null;
	const names = members.filter((member) => mentionIds.includes(member.id)).map((member) => member.name).filter(Boolean);
	if (!names.length) return <p>{body}</p>;
	const pattern = new RegExp(`(@(?:${names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")}))`, "g");
	return <p>{body.split(pattern).map((part, index) => part.startsWith("@") && names.includes(part.slice(1)) ? <mark key={`${part}-${index}`}>{part}</mark> : part)}</p>;
}

function MessageAttachment({ attachment }: { attachment: GeoCollaborationAttachmentRef }) {
	if (attachment.kind === "geo_object" && attachment.href) return <Link className={styles.sharedCard} href={attachment.href as Route}>
		<span>{attachment.module_label?.slice(0, 1) || "G"}</span><div><small>{attachment.module_label || "GEO 工作项"}</small><b>{attachment.title || attachment.label}</b><em>{attachment.subtitle || "打开查看"}</em></div><i>›</i>
	</Link>;
	if (attachment.kind === "image" && attachment.url) return <figure className={styles.imageAttachment}>
		<a href={attachment.url} target="_blank" rel="noreferrer"><img src={attachment.url} alt={attachment.label} /></a><figcaption>{attachment.label}</figcaption>
	</figure>;
	if (attachment.kind === "video" && attachment.url) return <figure className={styles.videoAttachment}>
		<video src={attachment.url} controls preload="metadata" /><figcaption>{attachment.label}</figcaption>
	</figure>;
	return attachment.url
		? <a className={styles.fileAttachment} href={attachment.url} target="_blank" rel="noreferrer"><span>{attachment.kind === "file" ? "↓" : "↗"}</span><b>{attachment.label}</b><small>{attachment.kind === "evidence" ? "证据" : attachment.kind === "file" ? "文件" : "链接"}</small></a>
		: <span className={styles.fileAttachment}><b>{attachment.label}</b></span>;
}

function MessageEntry({ entry, members }: { entry: GeoCollaborationMessage; members: GeoCollaborationMember[] }) {
	return <article className={styles.messageEntry} data-delivery={entry.delivery_state || "sent"}>
		<Avatar name={entry.author?.name} initial={entry.author?.initial} />
		<div>
			<header><strong>{entry.author?.name || "系统"}</strong><time>{entry.delivery_state === "sending" ? "正在发送…" : entry.delivery_state === "failed" ? "发送失败" : formatDate(entry.created_at, true)}</time></header>
			<MentionedBody body={entry.body} mentionIds={entry.mention_user_ids} members={members} />
			{entry.attachment_refs.length ? <div className={styles.attachments}>{entry.attachment_refs.map((attachment, index) => <MessageAttachment key={`${attachment.kind}-${attachment.attachment_id || attachment.href || attachment.url || index}`} attachment={attachment} />)}</div> : null}
		</div>
	</article>;
}

function ActivityEntry({ entry }: { entry: GeoCollaborationActivity }) {
	return <article className={styles.systemEntry}>
		<span aria-hidden="true">◇</span>
		<p><strong>系统</strong> {eventLabels[entry.event_type] || entry.event_type.replaceAll("_", " ")}</p>
		<time>{formatDate(entry.created_at, true)}</time>
	</article>;
}

export function CollaborationCenter({ workspaceId, initialData, initialShare = null }: { workspaceId: number; initialData: CollaborationData; initialShare?: GeoCollaborationShareDraft | null }) {
	const [data, setData] = useState(initialData);
	const [tab, setTab] = useState<Tab>("discussions");
	const [query, setQuery] = useState("");
	const [starterQuery, setStarterQuery] = useState("");
	const [starterGroup, setStarterGroup] = useState<"work" | "insight">("work");
	const [starterKind, setStarterKind] = useState<"all" | "action" | "question" | "evidence">("all");
	const [showStarter, setShowStarter] = useState(false);
	const [showLink, setShowLink] = useState(false);
	const [linkUrl, setLinkUrl] = useState("");
	const [body, setBody] = useState("");
	const [mentionIds, setMentionIds] = useState<number[]>([]);
	const [showMentions, setShowMentions] = useState(false);
	const [mentionQuery, setMentionQuery] = useState("");
	const [activeMention, setActiveMention] = useState(0);
	const [attachments, setAttachments] = useState<GeoCollaborationAttachmentRef[]>([]);
	const [sharedObjects, setSharedObjects] = useState<GeoCollaborationShareDraft[]>(initialShare ? [initialShare] : []);
	const [uploading, setUploading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [sendState, setSendState] = useState<SendState>("idle");
	const [workSaving, setWorkSaving] = useState(false);
	const [showAssignee, setShowAssignee] = useState(false);
	const [showParticipants, setShowParticipants] = useState(false);
	const [, startTransition] = useTransition();
	const sendAttemptKeyRef = useRef<string | null>(null);
	const fileInputRef = useRef<HTMLInputElement>(null);
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const selected = data.selected;
	useEffect(() => {
		setShowMentions(false);
		setMentionQuery("");
	}, [selected?.key]);
	const mentionCandidates = useMemo(() => data.members.filter((member) => member.id !== data.current_user_id && `${member.name} ${member.email} ${roleLabels[member.role] || member.role}`.toLowerCase().includes(mentionQuery.toLowerCase())), [data.current_user_id, data.members, mentionQuery]);
	const visibleItems = useMemo(() => data.items.filter((item) => {
		if (!item.has_conversation && item.key !== selected?.key) return false;
		if (query && !`${item.title} ${item.category} ${item.assignee_name || ""}`.toLowerCase().includes(query.toLowerCase())) return false;
		return true;
	}), [data.items, query, selected?.key]);
	const startableItems = useMemo(() => data.items.filter((item) => {
		if (starterGroup === "work" && item.context_type !== "action" && item.context_type !== "question") return false;
		if (starterGroup === "insight" && item.context_type !== "evidence") return false;
		if (starterKind !== "all" && item.context_type !== starterKind) return false;
		return !starterQuery || `${item.title} ${item.category}`.toLowerCase().includes(starterQuery.toLowerCase());
	}).slice(0, 40), [data.items, starterGroup, starterKind, starterQuery]);

	const selectItem = (item: GeoCollaborationItem) => startTransition(async () => {
		setError(null);
		setSendState("idle");
		sendAttemptKeyRef.current = null;
		try {
			const next = await loadCollaborationCenter(workspaceId, item.context_type, item.context_id);
			setData(next);
			setShowStarter(false);
			window.history.replaceState(null, "", `/geo/${workspaceId}/collaboration?context=${item.context_type}&id=${item.context_id}`);
			if (next.selected?.thread_id) await markCollaborationRead(workspaceId, next.selected.thread_id);
		} catch (value) { setError(value instanceof Error ? value.message : "无法加载会话"); }
	});

	const submit = async () => {
		if (!selected || (!body.trim() && !attachments.length && !sharedObjects.length)) return;
		if (sendState === "sending") return;
		const draft = {
			body: body.trim(),
			mentionIds: [...mentionIds],
			attachments: [...attachments],
			sharedObjects: [...sharedObjects],
		};
		setSendState("sending");
		setError(null);
		const idempotencyKey = sendAttemptKeyRef.current || `web-${crypto.randomUUID()}`;
		sendAttemptKeyRef.current = idempotencyKey;
		const optimisticId = -Date.now();
		const currentMember = data.members.find((member) => member.id === data.current_user_id) || null;
		const optimisticMessage: GeoCollaborationMessage = {
			id: optimisticId,
			kind: "comment",
			body: draft.body,
			author: currentMember,
			mention_user_ids: draft.mentionIds,
			attachment_refs: draft.attachments,
			created_at: new Date().toISOString(),
			delivery_state: "sending",
		};
		setData((current) => ({
			...current,
			items: current.items.map((item) => item.key === selected.key ? {
				...item,
				has_conversation: true,
				message_count: item.message_count + 1,
				last_message_preview: draft.body || "[附件]",
				last_message_author_name: currentMember?.name || "我",
				last_activity_at: optimisticMessage.created_at,
			} : item),
			selected: current.selected ? {
				...current.selected,
				has_conversation: true,
				message_count: current.selected.message_count + 1,
				last_message_preview: draft.body || "[附件]",
				last_message_author_name: currentMember?.name || "我",
				last_activity_at: optimisticMessage.created_at,
			} : current.selected,
			selected_detail: current.selected_detail ? {
				...current.selected_detail,
				messages: [...current.selected_detail.messages, optimisticMessage],
			} : current.selected_detail,
		}));
		setBody(""); setMentionIds([]); setAttachments([]); setSharedObjects([]); setShowMentions(false); setMentionQuery("");
		try {
			const result = await fetchJsonWithTimeout<{ id: number; thread_id: number; created_at: string; message: GeoCollaborationMessage }>(
				`/api/geo/${workspaceId}/collaboration/messages`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
					context_type: selected.context_type,
					context_id: selected.context_id,
					body: draft.body,
					mention_user_ids: draft.mentionIds,
					attachment_refs: draft.attachments.filter((item) => !item.attachment_id).map((item) => ({ label: item.label, url: item.url, kind: item.kind as "link" | "evidence" | "file" })),
					attachment_ids: draft.attachments.flatMap((item) => item.attachment_id ? [item.attachment_id] : []),
					shared_objects: draft.sharedObjects,
					idempotency_key: idempotencyKey,
				}),
				},
			);
			setData((current) => ({
				...current,
				items: current.items.map((item) => item.key === selected.key ? { ...item, thread_id: result.thread_id } : item),
				selected: current.selected ? { ...current.selected, thread_id: result.thread_id } : current.selected,
				selected_detail: current.selected_detail ? {
					...current.selected_detail,
					messages: current.selected_detail.messages.map((message) => message.id === optimisticId ? result.message : message),
				} : current.selected_detail,
			}));
			sendAttemptKeyRef.current = null;
			setSendState("idle");
		} catch (value) {
			setData((current) => ({
				...current,
				items: current.items.map((item) => item.key === selected.key ? { ...item, message_count: Math.max(0, item.message_count - 1) } : item),
				selected: current.selected ? { ...current.selected, message_count: Math.max(0, current.selected.message_count - 1) } : current.selected,
				selected_detail: current.selected_detail ? { ...current.selected_detail, messages: current.selected_detail.messages.filter((message) => message.id !== optimisticId) } : current.selected_detail,
			}));
			setBody(draft.body); setMentionIds(draft.mentionIds); setAttachments(draft.attachments); setSharedObjects(draft.sharedObjects);
			setSendState("retry");
			setError(value instanceof Error ? value.message : "发送失败，可安全重试");
		}
	};

	const uploadFiles = async (files: FileList | null) => {
		if (!files?.length) return;
		setUploading(true); setError(null);
		try {
			const added: GeoCollaborationAttachmentRef[] = [];
			for (const file of Array.from(files).slice(0, Math.max(0, 12 - attachments.length))) {
				const response = await fetch(`/api/geo/${workspaceId}/collaboration/attachments`, {
					method: "POST",
					headers: { "Content-Type": file.type || "application/octet-stream", "X-File-Name": encodeURIComponent(file.name), "X-File-Size": String(file.size) },
					body: file,
				});
				const value = await response.json().catch(() => null) as (GeoCollaborationAttachmentRef & { detail?: string }) | null;
				if (!response.ok || !value) throw new Error(value?.detail || `无法上传 ${file.name}`);
				added.push(value);
			}
			setAttachments((current) => [...current, ...added]);
		} catch (value) { setError(value instanceof Error ? value.message : "附件上传失败"); }
		finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = ""; }
	};

	const removeAttachment = async (item: GeoCollaborationAttachmentRef) => {
		if (item.attachment_id) await fetch(`/api/geo/${workspaceId}/collaboration/attachments/${item.attachment_id}`, { method: "DELETE" });
		setAttachments((current) => current.filter((value) => value !== item));
	};

	const chooseMention = (member: GeoCollaborationMember) => {
		setMentionIds((current) => current.includes(member.id) ? current.filter((id) => id !== member.id) : [...current, member.id]);
		if (!body.includes(`@${member.name}`)) {
			const cursor = textareaRef.current?.selectionStart ?? body.length;
			const prefix = body.slice(0, cursor).replace(/@[\p{L}\p{N}_.-]*$/u, "");
			const next = `${prefix}@${member.name} ${body.slice(cursor)}`;
			setBody(next);
		}
		setMentionQuery("");
		textareaRef.current?.focus();
	};

	const mentionKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
		if (showMentions && mentionCandidates.length) {
			if (event.key === "ArrowDown" || event.key === "ArrowUp") {
				event.preventDefault();
				setActiveMention((current) => (current + (event.key === "ArrowDown" ? 1 : -1) + mentionCandidates.length) % mentionCandidates.length);
				return;
			}
			if (event.key === "Enter" && !(event.metaKey || event.ctrlKey)) { event.preventDefault(); chooseMention(mentionCandidates[activeMention]); return; }
			if (event.key === "Escape") { event.preventDefault(); setShowMentions(false); return; }
		}
		if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit();
	};

	const addLink = () => {
		if (!linkUrl.trim()) return;
		try {
			const parsed = new URL(linkUrl.trim());
			if (parsed.protocol !== "https:" && parsed.protocol !== "http:") throw new Error();
			setAttachments((current) => [...current, { label: parsed.hostname, url: parsed.toString(), kind: "link" }]);
			setLinkUrl("");
			setShowLink(false);
		} catch { setError("请输入有效的 HTTP/HTTPS 链接"); }
	};
	const updateWorkInfo = async (patch: Partial<Pick<GeoCollaborationItem, "assignee_user_id" | "start_at" | "due_at" | "participant_user_ids">>) => {
		if (!selected || workSaving) return;
		const nextParticipants = patch.participant_user_ids ?? selected.participant_user_ids ?? [];
		const nextAssignee = patch.assignee_user_id === undefined ? (selected.assignee_user_id ?? null) : patch.assignee_user_id;
		setWorkSaving(true);
		setError(null);
		try {
			const next = await saveCollaborationWorkInfo(workspaceId, selected.context_type, selected.context_id, {
				assignee_user_id: nextAssignee,
				start_at: patch.start_at === undefined ? (selected.start_at ?? null) : patch.start_at,
				due_at: patch.due_at === undefined ? (selected.due_at ?? null) : patch.due_at,
				participant_user_ids: Array.from(new Set([...nextParticipants, ...(nextAssignee ? [nextAssignee] : [])])),
			});
			setData(next);
			setShowAssignee(false);
		} catch (value) {
			setError(value instanceof Error ? value.message : "任务信息保存失败");
		} finally {
			setWorkSaving(false);
		}
	};
	const sharedObjectLabel = (item: GeoCollaborationShareDraft) => item.kind === "module"
		? moduleLabels[item.module_key || ""] || "GEO 页面"
		: item.kind === "action" ? `优化行动 #${item.object_id}`
		: item.kind === "alert" ? `变化告警 #${item.object_id}`
		: item.kind === "question" ? `问题 #${item.object_id}`
		: item.kind === "content_asset" ? `内容资产 #${item.object_id}`
		: `证据 #${item.object_id}`;
	const conversationCount = data.items.filter((item) => item.has_conversation).length;
	const selectedOutsideList = selected && !visibleItems.some((item) => item.key === selected.key) ? selected : null;
	const participants = useMemo(() => {
		const ids = new Set<number>(selected?.participant_user_ids || []);
		if (selected?.assignee_user_id) ids.add(selected.assignee_user_id);
		for (const message of data.selected_detail?.messages || []) {
			if (message.author?.id) ids.add(message.author.id);
			for (const id of message.mention_user_ids) ids.add(id);
		}
		return data.members.filter((member) => ids.has(member.id));
	}, [data.members, data.selected_detail?.messages, selected?.assignee_user_id, selected?.participant_user_ids]);
	const assignableMembers = data.members.filter((member) => member.role !== "viewer");
	const nextStepText = selected?.context_type === "action"
		? selected.blocked_note || (selected.pending_approvals ? "完成待处理审批并反馈修改意见" : "确认本项行动的下一步并同步执行结果")
		: selected?.context_type === "evidence"
			? "围绕这次模型回答确认判断、证据和后续行动"
			: "确认问题负责人，并把讨论结论转成下一步行动";
	const contextHref = selected?.context_type === "action"
		? `/geo/${workspaceId}/actions?action_id=${selected.context_id}`
		: selected?.context_type === "question"
			? `/geo/${workspaceId}/questions/${selected.context_id}`
			: selected?.context_type === "evidence"
				? `/geo/${workspaceId}/evidence/${selected.context_id}`
			: `/geo/${workspaceId}/alerts`;

	return <main className={styles.page}>
		<header className={styles.pageHeader}><h1>协作中心</h1><p>让每条消息都对应一项工作</p></header>
		<section className={styles.surface}>
			<nav className={styles.tabs} aria-label="协作中心分类">
				<button type="button" className={tab === "discussions" ? styles.activeTab : ""} onClick={() => setTab("discussions")}>工作讨论 <b>{conversationCount}</b></button>
				<button type="button" className={tab === "contacts" ? styles.activeTab : ""} onClick={() => setTab("contacts")}>通讯录</button>
			</nav>

			{tab === "contacts" ? <CollaborationContacts workspaceId={workspaceId} data={data} onData={setData} onOpenWork={(item) => { setTab("discussions"); void selectItem(item); }} />
			: <div className={styles.workspace}>
				<aside className={styles.threadRail}>
					<header className={styles.railHeader}><strong>团队讨论</strong><Popover.Root open={showStarter} onOpenChange={setShowStarter}><Popover.Trigger asChild><button type="button" className={styles.startDiscussion}>＋ 发起讨论</button></Popover.Trigger><Popover.Portal><Popover.Content className={styles.starterMenu} side="bottom" align="start" sideOffset={8} collisionPadding={12}><header><div><b>选择讨论对象</b><small>选择真实工作或某次观测洞察</small></div><Popover.Close aria-label="关闭">×</Popover.Close></header><div className={styles.starterGroups}><button type="button" data-active={starterGroup === "work"} onClick={() => { setStarterGroup("work"); setStarterKind("all"); }}>工作</button><button type="button" data-active={starterGroup === "insight"} onClick={() => { setStarterGroup("insight"); setStarterKind("all"); }}>洞察结果</button></div><label><span>⌕</span><input autoFocus value={starterQuery} onChange={(event) => setStarterQuery(event.target.value)} placeholder={starterGroup === "work" ? "搜索优化行动或问题" : "搜索问题、模型或观测结果"} /></label><nav>{(starterGroup === "work" ? ([['all','全部'],['action','优化行动'],['question','问题']] as const) : ([['all','全部观测'],['evidence','模型回答']] as const)).map(([value,label]) => <button key={value} type="button" data-active={starterKind === value} onClick={() => setStarterKind(value)}>{label}</button>)}</nav><div>{startableItems.length ? startableItems.map((item) => <WorkRow key={item.key} item={item} active={selected?.key === item.key} onSelect={() => selectItem(item)} />) : <p>没有找到对应结果</p>}</div></Popover.Content></Popover.Portal></Popover.Root></header>
					<div className={styles.searchBox}><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索讨论" /></div>
					{selectedOutsideList ? <div className={styles.pinnedContext}><small>当前打开</small><WorkRow item={selectedOutsideList} active={true} onSelect={() => selectItem(selectedOutsideList)} /></div> : null}
					<div className={styles.threadList}>{visibleItems.map((item) => <WorkRow key={item.key} item={item} active={selected?.key === item.key} onSelect={() => selectItem(item)} />)}</div>
					<footer>{visibleItems.length ? `当前显示 ${visibleItems.length} 项` : "没有符合条件的工作"}</footer>
				</aside>

				<section className={styles.conversation}>
					{selected ? <>
						<header className={styles.conversationHeader}><span>{selected.category}</span><div><h2>{selected.title}</h2><em data-tone={itemTone(selected)}>{selected.context_type === "question" ? "问题" : statusLabels[selected.status] || selected.status}</em></div><p>{selected.context_type === "action" ? <><span>负责人　{selected.assignee_name || "待分配"}</span><span>截止　{formatDate(selected.due_at)}</span></> : null}<span>{selected.message_count ? `${selected.message_count} 条讨论` : "尚未建立讨论"}</span></p></header>
						<ActivityDigest activity={data.selected_detail?.activity || []} />
						<ThreadTimeline data={data} />
						<div className={styles.composer}>
							{sharedObjects.length ? <div className={styles.composerShares}>{sharedObjects.map((item, index) => <div key={`${item.kind}-${item.object_id || item.module_key}`}><span>GEO</span><b>{sharedObjectLabel(item)}</b><button type="button" onClick={() => setSharedObjects((current) => current.filter((_, valueIndex) => valueIndex !== index))} aria-label="移除业务卡片">×</button></div>)}</div> : null}
							{attachments.length ? <div className={styles.composerAttachments}>{attachments.map((item) => <div key={`${item.attachment_id || item.url}`} data-kind={item.kind}>{item.kind === "image" && item.url ? <img src={item.url} alt="" /> : <span>{item.kind === "video" ? "▶" : item.kind === "file" ? "↓" : "↗"}</span>}<b>{item.label}</b><small>{item.byte_size ? `${Math.max(1, Math.round(item.byte_size / 1024))} KB` : item.kind}</small><button type="button" onClick={() => void removeAttachment(item)} aria-label={`移除 ${item.label}`}>×</button></div>)}</div> : null}
							{mentionIds.length ? <div className={styles.mentionChips}>{mentionIds.map((id) => { const member = data.members.find((value) => value.id === id); return <button key={id} type="button" onClick={() => setMentionIds((current) => current.filter((value) => value !== id))}>@{member?.name || id} ×</button>; })}</div> : null}
							<textarea ref={textareaRef} value={body} onChange={(event) => { const value = event.target.value; setBody(value); if (sendState === "retry") { setSendState("idle"); sendAttemptKeyRef.current = null; } const match = value.slice(0, event.target.selectionStart).match(/@([^\s@]*)$/); if (match) { setMentionQuery(match[1]); setShowMentions(true); setActiveMention(0); } }} onKeyDown={mentionKeyDown} placeholder="写下需要团队回应的事，输入 @ 提醒同事…" />
							<div className={styles.composerToolbar}><span><input ref={fileInputRef} type="file" multiple accept="image/*,video/*,.pdf,.docx,.xlsx,.pptx,.csv,.txt,.zip" onChange={(event) => void uploadFiles(event.target.files)} /><button type="button" onClick={() => fileInputRef.current?.click()} aria-label="添加图片、视频或文件" title="添加图片、视频或文件">＋</button><Popover.Root open={showLink} onOpenChange={(open) => { setShowLink(open); if (!open) setLinkUrl(""); }}><Popover.Trigger asChild><button type="button" className={showLink ? styles.activeComposerTool : ""} aria-label="添加链接" title="添加链接">↗</button></Popover.Trigger><Popover.Portal><Popover.Content className={styles.linkMenu} side="top" align="start" sideOffset={8} collisionPadding={12}><b>添加网页链接</b><form onSubmit={(event) => { event.preventDefault(); addLink(); }}><input autoFocus type="url" value={linkUrl} onChange={(event) => setLinkUrl(event.target.value)} placeholder="https://example.com" /><button type="submit" disabled={!linkUrl.trim()}>添加</button></form><Popover.Arrow className={styles.mentionArrow} /></Popover.Content></Popover.Portal></Popover.Root><Popover.Root open={showMentions} onOpenChange={(open) => { setShowMentions(open); if (open) { setMentionQuery(""); setActiveMention(0); } }}><Popover.Trigger asChild><button type="button" className={showMentions ? styles.activeComposerTool : ""} aria-label="@成员" title="@成员">@</button></Popover.Trigger><Popover.Portal><Popover.Content className={styles.mentionMenu} side="top" align="start" sideOffset={8} collisionPadding={12}><header><b>提醒成员</b><small>可多选</small></header><label><span>⌕</span><input autoFocus value={mentionQuery} onChange={(event) => { setMentionQuery(event.target.value); setActiveMention(0); }} placeholder="搜索姓名或角色" /></label><div>{mentionCandidates.length ? mentionCandidates.map((member, index) => <button key={member.id} type="button" data-active={index === activeMention} data-selected={mentionIds.includes(member.id)} onMouseEnter={() => setActiveMention(index)} onClick={() => chooseMention(member)}><Avatar name={member.name} initial={member.initial} small /><span><b>{member.name}</b><small>{roleLabels[member.role] || member.role} · {member.email}</small></span><i>{mentionIds.includes(member.id) ? "✓" : ""}</i></button>) : <p>没有找到成员</p>}</div><Popover.Arrow className={styles.mentionArrow} /></Popover.Content></Popover.Portal></Popover.Root><small>{uploading ? "正在上传…" : "⌘ Enter 发送"}</small></span><button type="button" className={styles.sendButton} data-retry={sendState === "retry"} disabled={sendState === "sending" || uploading || (!body.trim() && !attachments.length && !sharedObjects.length)} onClick={() => void submit()}>{sendState === "sending" ? "发送中…" : sendState === "retry" ? "安全重试" : "发送"}<i /></button></div>
						</div>
					</> : <EmptyThread />}
				</section>

				<aside className={styles.contextRail}>
					{selected ? <>
						<section className={styles.contextBlock}>
							<header className={styles.taskInfoHeader}><h3>任务信息</h3><small>{workSaving ? "保存中…" : "已同步"}</small></header>
							<dl className={styles.taskInfoList}>
								<div><dt>负责人</dt><dd><Popover.Root open={showAssignee} onOpenChange={setShowAssignee}><Popover.Trigger asChild><button type="button" className={styles.infoValueButton}><Avatar name={selected.assignee_name} small /><span>{selected.assignee_name || "选择负责人"}</span><b>⌄</b></button></Popover.Trigger><Popover.Portal><Popover.Content className={styles.workInfoMenu} side="left" align="start" sideOffset={10}><header>指派负责人</header>{assignableMembers.map((member) => <button type="button" key={member.id} data-active={selected.assignee_user_id === member.id} onClick={() => void updateWorkInfo({ assignee_user_id: member.id })}><Avatar name={member.name} initial={member.initial} small /><span><b>{member.name}</b><small>{roleLabels[member.role] || member.role}</small></span><i>{selected.assignee_user_id === member.id ? "✓" : ""}</i></button>)}</Popover.Content></Popover.Portal></Popover.Root></dd></div>
								<div><dt>开始日期</dt><dd className={styles.dateValue}><input aria-label="开始日期" type="date" value={dateInputValue(selected.start_at)} onChange={(event) => void updateWorkInfo({ start_at: dateInputIso(event.target.value) })} /></dd></div>
								<div><dt>截止日期</dt><dd className={styles.dateValue} data-warning={daysLeft(selected.due_at) != null && daysLeft(selected.due_at)! <= 3}><input aria-label="截止日期" type="date" value={dateInputValue(selected.due_at)} onChange={(event) => void updateWorkInfo({ due_at: dateInputIso(event.target.value) })} />{daysLeft(selected.due_at) != null ? <small>{daysLeft(selected.due_at)! >= 0 ? `剩余 ${daysLeft(selected.due_at)} 天` : `逾期 ${Math.abs(daysLeft(selected.due_at)!)} 天`}</small> : null}</dd></div>
								<div><dt>参与成员</dt><dd><Popover.Root open={showParticipants} onOpenChange={setShowParticipants}><Popover.Trigger asChild><button type="button" className={styles.participantStack} aria-label="管理参与成员">{participants.slice(0, 4).map((member) => <Avatar key={member.id} name={member.name} initial={member.initial} small />)}{participants.length > 4 ? <i>+{participants.length - 4}</i> : null}<b>管理</b></button></Popover.Trigger><Popover.Portal><Popover.Content className={styles.workInfoMenu} side="left" align="start" sideOffset={10}><header>参与成员</header>{data.members.map((member) => { const active = (selected.participant_user_ids || []).includes(member.id); return <button type="button" key={member.id} data-active={active} onClick={() => { const ids = new Set(selected.participant_user_ids || []); if (active) ids.delete(member.id); else ids.add(member.id); void updateWorkInfo({ participant_user_ids: Array.from(ids) }); }}><Avatar name={member.name} initial={member.initial} small /><span><b>{member.name}</b><small>{roleLabels[member.role] || member.role}</small></span><i>{active ? "✓" : ""}</i></button>; })}</Popover.Content></Popover.Portal></Popover.Root></dd></div>
								<div><dt>影响范围</dt><dd className={styles.scopeValue}>{selected.question_ids.length} 个问题 · {selected.model_keys.length} 个模型{selected.evidence_count ? ` · ${selected.evidence_count} 条证据` : ""}</dd></div>
							</dl>
							<Link className={styles.detailLink} href={contextHref as Route}>查看详情 <span>›</span></Link>
							<div className={styles.taskDivider} />
							<section className={styles.nextTask}><h3>下一步</h3><div><span aria-hidden="true">✓</span><p><strong>{nextStepText}</strong><small>{selected.context_type === "action" ? `${selected.progress}% 进度 · ${statusLabels[selected.status] || selected.status}` : "形成结论后可直接打开原工作继续处理"}</small></p></div><Link href={contextHref as Route}>打开原工作</Link></section>
						</section>
					</> : null}
				</aside>
			</div>}
		</section>
		{error ? <div className={styles.toast} role="alert">{error}</div> : null}
	</main>;
}
