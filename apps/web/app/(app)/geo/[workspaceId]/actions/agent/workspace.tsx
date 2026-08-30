"use client";

import { useEffect, useMemo, useState, useTransition } from "react";

import type {
	AgentRuntime,
	AgentRuntimeKey,
	AgentWorkspaceContext,
	AgentWorkspaceContextOptions,
	AgentWorkspaceConversation,
	AgentWorkspaceMessage,
	CodexReasoningEffort,
	WorkspaceMembership,
} from "@/lib/cleanroom-v1-api";
import {
	archiveAgentConversation,
	createAgentSuggestionAction,
	continueAgentConversation,
	loadAgentConversation,
	loadAgentConversations,
	loadAgentRuntimes,
	saveAgentConversationContext,
	startAgentConversation,
} from "./actions";
import styles from "./workspace.module.css";

type Props = {
	workspaceId: number;
	initialConversations: AgentWorkspaceConversation[];
	initialSelected: AgentWorkspaceConversation | null;
	contextOptions: AgentWorkspaceContextOptions;
	runtimes: AgentRuntime[];
	defaultContext: AgentWorkspaceContext;
	members: WorkspaceMembership[];
};

const CAPABILITIES = [
	["分析洞察", "分析当前范围中最重要的 GEO 机会，并说明证据。"],
	["生成行动方案", "根据当前证据给出可执行的优化行动方案。"],
	["准备内容", "为当前问题准备一份有证据约束的内容方案。"],
	["检查进度", "检查当前优化行动进度、阻塞点和下一步。"],
] as const;

function hasActiveMessage(conversation: AgentWorkspaceConversation | null) {
	return Boolean(conversation?.messages.some((message) => message.status === "queued" || message.status === "running"));
}

function timeLabel(value?: string | null) {
	if (!value) return "刚刚";
	return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function AgentWorkspace({ workspaceId, initialConversations, initialSelected, contextOptions, runtimes, defaultContext, members }: Props) {
	const [conversations, setConversations] = useState(initialConversations);
	const [runtimeCatalog, setRuntimeCatalog] = useState(runtimes);
	const [selected, setSelected] = useState(initialSelected);
	const [draftContext, setDraftContext] = useState<AgentWorkspaceContext>(initialSelected?.context ?? defaultContext);
	const [content, setContent] = useState("");
	const [runtimeKey, setRuntimeKey] = useState<AgentRuntimeKey | "auto">("auto");
	const [model, setModel] = useState<string | null>(null);
	const [effort, setEffort] = useState<CodexReasoningEffort | null>(null);
	const [contextOpen, setContextOpen] = useState(false);
	const [processMessage, setProcessMessage] = useState<AgentWorkspaceMessage | null>(null);
	const [error, setError] = useState("");
	const [isPending, startTransition] = useTransition();
	const activeRuntime = runtimeKey === "auto" ? null : runtimeCatalog.find((item) => item.runtime_key === runtimeKey) ?? null;
	const modelOptions = activeRuntime?.model_options ?? [];
	const busy = isPending || hasActiveMessage(selected);

	const grouped = useMemo(() => ({
		running: conversations.filter((item) => ["queued", "running"].includes(item.last_message_status ?? "")),
		needsUser: conversations.filter((item) => item.needs_user && !["queued", "running"].includes(item.last_message_status ?? "")),
		recent: conversations.filter((item) => !item.needs_user && !["queued", "running"].includes(item.last_message_status ?? "")),
	}), [conversations]);

	useEffect(() => {
		let cancelled = false;
		void loadAgentRuntimes(workspaceId).then((result) => {
			if (!cancelled && result.ok) setRuntimeCatalog(result.data);
		});
		return () => { cancelled = true; };
	}, [workspaceId]);

	useEffect(() => {
		if (!selected || !hasActiveMessage(selected)) return;
		let cancelled = false;
		const timer = window.setInterval(async () => {
			const result = await loadAgentConversation(workspaceId, selected.id);
			if (cancelled || !result.ok) return;
			setSelected(result.data);
			setProcessMessage((current) => current ? result.data.messages.find((item) => item.id === current.id) ?? current : null);
			const list = await loadAgentConversations(workspaceId);
			if (!cancelled && list.ok) setConversations(list.data);
		}, 1800);
		return () => { cancelled = true; window.clearInterval(timer); };
	}, [selected?.id, selected?.last_message_status, workspaceId]);

	const selectConversation = (conversationId: number) => startTransition(async () => {
		setError("");
		const result = await loadAgentConversation(workspaceId, conversationId);
		if (!result.ok) return setError(result.error);
		setSelected(result.data);
		setDraftContext(result.data.context);
	});

	const refreshList = async () => {
		const result = await loadAgentConversations(workspaceId);
		if (result.ok) setConversations(result.data);
	};

	const submit = () => {
		const prompt = content.trim();
		if (!prompt || busy) return;
		startTransition(async () => {
			setError("");
			const execution = { runtime_key: runtimeKey, model, reasoning_effort: effort };
			const result = selected
				? await continueAgentConversation(workspaceId, selected.id, prompt, execution)
				: await startAgentConversation(workspaceId, prompt, draftContext, execution);
			if (!result.ok) return setError(result.error);
			setSelected(result.data);
			setDraftContext(result.data.context);
			setContent("");
			await refreshList();
		});
	};

	const saveContext = () => {
		if (!selected) return setContextOpen(false);
		startTransition(async () => {
			const result = await saveAgentConversationContext(workspaceId, selected.id, draftContext);
			if (!result.ok) return setError(result.error);
			setSelected(result.data);
			setContextOpen(false);
		});
	};

	const archive = () => {
		if (!selected) return;
		startTransition(async () => {
			const result = await archiveAgentConversation(workspaceId, selected.id);
			if (!result.ok) return setError(result.error);
			setSelected(null);
			setDraftContext(defaultContext);
			await refreshList();
		});
	};

	const setContextNumber = (key: "batch_id" | "question_plan_id" | "action_id", value: string) => {
		setDraftContext((current) => ({ ...current, [key]: value ? Number(value) : null }));
	};

	return <main className={styles.page}>
		<aside className={styles.rail} aria-label="Agent 对话">
			<div className={styles.railTitle}><span>✦</span><b>Agent 工作台</b></div>
			<button className={styles.newButton} type="button" onClick={() => { setSelected(null); setDraftContext(defaultContext); setContent(""); }}>＋ 新建对话</button>
			{([["正在推进", grouped.running], ["需要我", grouped.needsUser], ["最近", grouped.recent]] as const).map(([label, items]) => items.length ? <section className={styles.conversationGroup} key={label}>
				<h2>{label}<span>{items.length}</span></h2>
				{items.map((item) => <button key={item.id} type="button" className={selected?.id === item.id ? styles.activeConversation : ""} onClick={() => selectConversation(item.id)}>
					<strong>{item.title}</strong><small>{timeLabel(item.last_message_at ?? item.updated_at)}</small>
				</button>)}
			</section> : null)}
			<div className={styles.railFooter}>分析和方案可以自由推进；正式执行仍进入优化行动审批链。</div>
		</aside>

		<section className={styles.workArea}>
			<header className={styles.topbar}>
				<div><p>Agent 工作台</p><h1>{selected?.title ?? "新的 GEO 对话"}</h1></div>
				<div className={styles.topActions}>{selected ? <button type="button" onClick={archive}>归档</button> : null}<button type="button" onClick={() => setContextOpen(true)}>＋ 添加上下文</button></div>
			</header>

			<div className={styles.contextBar}>
				<span>工作区 #{workspaceId}</span>
				{draftContext.batch_id ? <span>{contextOptions.batches.find((item) => item.id === draftContext.batch_id)?.label ?? `批次 #${draftContext.batch_id}`}</span> : null}
				{draftContext.question_plan_id ? <span className={styles.wideChip}>{contextOptions.questions.find((item) => item.id === draftContext.question_plan_id)?.label ?? `问题 #${draftContext.question_plan_id}`}</span> : null}
				{draftContext.action_id ? <span>{contextOptions.actions.find((item) => item.id === draftContext.action_id)?.label ?? `行动 #${draftContext.action_id}`}</span> : null}
				{draftContext.model_keys.map((item) => <span key={item}>{item}</span>)}
			</div>

			<div className={styles.chat}>
				{!selected?.messages.length ? <div className={styles.welcome}>
					<span>✦</span><h2>从一个真实 GEO 问题开始</h2><p>选择范围后直接说目标。Agent 会读取现有洞察与证据，给出判断、方案和可进入优化行动的建议。</p>
					<div>{CAPABILITIES.map(([label, prompt]) => <button type="button" key={label} onClick={() => setContent(prompt)}>{label}<small>→</small></button>)}</div>
				</div> : <div className={styles.messageList}>{selected.messages.map((message) => <article key={message.id} className={message.role === "user" ? styles.userMessage : styles.agentMessage}>
					<header><b>{message.role === "user" ? "你" : "GEO Agent"}</b>{message.runtime_key ? <span>{runtimeCatalog.find((item) => item.runtime_key === message.runtime_key)?.display_name ?? message.runtime_key}</span> : null}</header>
					{message.status === "queued" || message.status === "running" ? <div className={styles.running}><i />{message.status === "queued" ? "已进入队列" : "正在读取证据并生成方案"}</div> : null}
					{message.status === "failed" ? <div className={styles.failed}>{message.error_message || "本次处理失败"}</div> : null}
					{message.status === "completed" ? <MessageBody message={message} workspaceId={workspaceId} conversationId={selected.id} context={selected.context} contextOptions={contextOptions} members={members} /> : null}
					{message.role === "assistant" && message.events.length ? <button className={styles.processButton} type="button" onClick={() => setProcessMessage(message)}>查看过程 · {message.events.length} 步</button> : null}
				</article>)}</div>}
			</div>

			<div className={styles.composerWrap}>
				{error ? <div className={styles.error}>{error}</div> : null}
				<div className={styles.quickActions}>{CAPABILITIES.map(([label, prompt]) => <button type="button" key={label} onClick={() => setContent(prompt)}>{label}</button>)}</div>
				<div className={styles.composer}>
					<textarea aria-label="给 GEO Agent 的消息" value={content} onChange={(event) => setContent(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} placeholder="告诉 Agent 你想分析什么，或下一步要推进什么…" disabled={busy} />
					<div className={styles.composerFooter}>
						<div>
							<select aria-label="Agent 运行时" value={runtimeKey} onChange={(event) => { setRuntimeKey(event.target.value as AgentRuntimeKey | "auto"); setModel(null); setEffort(null); }}><option value="auto">自动选择</option>{runtimeCatalog.map((item) => <option value={item.runtime_key} key={item.runtime_key} disabled={!item.ready}>{item.display_name}{item.ready ? "" : "（未就绪）"}</option>)}</select>
							{activeRuntime && modelOptions.length > 1 ? <select aria-label="模型" value={model ?? activeRuntime.default_model ?? ""} onChange={(event) => setModel(event.target.value || null)}>{modelOptions.map((item) => <option value={item.id} key={item.id}>{item.display_name}</option>)}</select> : null}
						</div>
						<button type="button" className={styles.sendButton} onClick={submit} disabled={!content.trim() || busy}>{busy ? "处理中" : "发送"} <span>↑</span></button>
					</div>
				</div>
				<p className={styles.truthNote}>Agent 不会自动发布内容；建议进入优化行动后仍需负责人和审批证据。</p>
			</div>
		</section>

		{contextOpen ? <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) setContextOpen(false); }}><section className={styles.contextModal} role="dialog" aria-modal="true" aria-labelledby="context-title">
			<header><div><h2 id="context-title">添加 GEO 上下文</h2><p>Agent 只读取你选中的真实范围。</p></div><button type="button" aria-label="关闭" onClick={() => setContextOpen(false)}>×</button></header>
			<label>观测批次<select value={draftContext.batch_id ?? ""} onChange={(event) => setContextNumber("batch_id", event.target.value)}><option value="">不限定</option>{contextOptions.batches.map((item) => <option value={item.id} key={item.id}>{item.label} · {item.status}</option>)}</select></label>
			<label>问题<select value={draftContext.question_plan_id ?? ""} onChange={(event) => setContextNumber("question_plan_id", event.target.value)}><option value="">不限定</option>{contextOptions.questions.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
			<label>优化行动<select value={draftContext.action_id ?? ""} onChange={(event) => setContextNumber("action_id", event.target.value)}><option value="">不限定</option>{contextOptions.actions.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
			<footer><button type="button" onClick={() => setContextOpen(false)}>取消</button><button type="button" onClick={saveContext} disabled={isPending}>保存范围</button></footer>
		</section></div> : null}

		{processMessage ? <aside className={styles.processDrawer} aria-label="执行过程">
			<header><div><p>可回读过程</p><h2>本次执行</h2></div><button type="button" aria-label="关闭过程" onClick={() => setProcessMessage(null)}>×</button></header>
			<div className={styles.processMeta}><span>{runtimeCatalog.find((item) => item.runtime_key === processMessage.runtime_key)?.display_name ?? processMessage.runtime_key}</span><span>{processMessage.status}</span></div>
			<ol>{processMessage.events.map((event) => <li key={event.id} className={event.stage === "failed" ? styles.failedStep : ""}><i /><div><b>{event.message}</b><time>{timeLabel(event.created_at)}</time></div></li>)}</ol>
			<p>这里展示可验证的执行事件，不展示模型隐藏思维链。</p>
		</aside> : null}
	</main>;
}

function futureInput(days = 7) {
	const date = new Date(Date.now() + days * 86400000);
	date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
	return date.toISOString().slice(0, 16);
}

function MessageBody({ message, workspaceId, conversationId, context, contextOptions, members }: {
	message: AgentWorkspaceMessage;
	workspaceId: number;
	conversationId: number;
	context: AgentWorkspaceContext;
	contextOptions: AgentWorkspaceContextOptions;
	members: WorkspaceMembership[];
}) {
	const payload = message.structured_payload;
	const suggestion = payload.suggested_action;
	const availableMembers = members.filter((member) => member.status === "active" && member.role !== "viewer");
	const [expanded, setExpanded] = useState(false);
	const [drawerOpen, setDrawerOpen] = useState(false);
	const [title, setTitle] = useState(suggestion?.title ?? "");
	const [expectedGoal, setExpectedGoal] = useState(suggestion?.summary ?? "");
	const [assigneeId, setAssigneeId] = useState(availableMembers[0]?.user_id ?? 0);
	const [dueAt, setDueAt] = useState(futureInput());
	const [createError, setCreateError] = useState("");
	const [creating, startCreating] = useTransition();
	const sourceContext = payload.source_context?.scope ?? context;
	const batchLabel = sourceContext.batch_id ? contextOptions.batches.find((item) => item.id === sourceContext.batch_id)?.label ?? `批次 #${sourceContext.batch_id}` : "未限定批次";
	const questionLabel = sourceContext.question_plan_id ? contextOptions.questions.find((item) => item.id === sourceContext.question_plan_id)?.label ?? `问题 #${sourceContext.question_plan_id}` : "未限定问题";
	const modelKeys = sourceContext.model_keys ?? [];
	const evidenceLabel = payload.source_context?.evidence_count === undefined ? "创建时回读证据" : `${payload.source_context.evidence_count} 条证据`;

	const openAction = (actionId: number) => {
		const url = new URL(window.location.href);
		url.pathname = `/geo/${workspaceId}/actions`;
		url.searchParams.set("action_id", String(actionId));
		window.location.assign(url.toString());
	};

	const createAction = () => {
		if (!suggestion || !title.trim() || !expectedGoal.trim() || !assigneeId || !dueAt) return;
		startCreating(async () => {
			setCreateError("");
			const result = await createAgentSuggestionAction(workspaceId, conversationId, message.id, {
				title: title.trim(),
				expected_goal: expectedGoal.trim(),
				assignee_user_id: assigneeId,
				due_at: new Date(dueAt).toISOString(),
			});
			if (!result.ok) return setCreateError(result.error);
			openAction(result.data.action_id);
		});
	};

	return <div className={styles.answer}>
		<p>{message.content}</p>
		{payload.rationale_summary?.length ? <section><h3>判断依据</h3><ul>{payload.rationale_summary.map((item) => <li key={item}>{item}</li>)}</ul></section> : null}
		{payload.evidence_summary?.length ? <section><h3>证据摘要</h3><div className={styles.evidenceGrid}>{payload.evidence_summary.map((item) => <div key={`${item.label}-${item.detail}`}><b>{item.label}</b><span>{item.detail}</span></div>)}</div></section> : null}
		{payload.execution_plan?.length ? <section><h3>执行计划</h3><ol className={styles.plan}>{payload.execution_plan.map((item) => <li key={item.label}><i className={styles[item.status]} />{item.label}<span>{item.status === "ready" ? "可推进" : item.status === "needs_user" ? "需要你" : "受阻"}</span></li>)}</ol></section> : null}
		{suggestion ? <section className={`${styles.actionSuggestion} ${expanded ? styles.expandedSuggestion : ""}`}>
			<button type="button" className={styles.suggestionHeader} aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
				<span><small>优先行动建议</small><h3>{suggestion.title}</h3><p>{suggestion.summary}</p></span><i aria-hidden="true">{expanded ? "−" : "+"}</i>
			</button>
			{expanded ? <div className={styles.suggestionDetails}>
				<section><h4>建议依据</h4>{payload.rationale_summary?.length ? <ul>{payload.rationale_summary.map((item) => <li key={item}>{item}</li>)}</ul> : <p>{suggestion.summary}</p>}</section>
				<section><h4>关联范围</h4><div className={styles.scopeTags}><span>{batchLabel}</span><span>{questionLabel}</span>{modelKeys.map((item) => <span key={item}>{item}</span>)}<span>{evidenceLabel}</span></div></section>
				<section><h4>执行建议</h4>{payload.execution_plan?.length ? <ol>{payload.execution_plan.map((item) => <li key={item.label}>{item.label}</li>)}</ol> : <p>{suggestion.summary}</p>}</section>
				{payload.linked_action_id ? <button type="button" className={styles.createActionButton} onClick={() => openAction(payload.linked_action_id!)}>查看优化行动 #{payload.linked_action_id} →</button> : <button type="button" className={styles.createActionButton} onClick={() => setDrawerOpen(true)}>创建优化行动 →</button>}
			</div> : null}
		</section> : null}
		{drawerOpen && suggestion ? <div className={styles.actionDrawerBackdrop} role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) setDrawerOpen(false); }}><aside className={styles.actionDrawer} role="dialog" aria-modal="true" aria-labelledby={`create-action-${message.id}`}>
			<header><div><p>从 Agent 建议创建</p><h2 id={`create-action-${message.id}`}>确认优化行动</h2></div><button type="button" aria-label="关闭" onClick={() => setDrawerOpen(false)}>×</button></header>
			<div className={styles.actionDrawerBody}>
				<label>行动标题<input value={title} maxLength={255} onChange={(event) => setTitle(event.target.value)} /></label>
				<label>负责人<select value={assigneeId} onChange={(event) => setAssigneeId(Number(event.target.value))}><option value={0} disabled>请选择</option>{availableMembers.map((member) => <option value={member.user_id} key={member.id}>{member.user.name} · {member.role}</option>)}</select></label>
				<label>截止时间<input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label>
				<label>预期目标<textarea value={expectedGoal} maxLength={3000} onChange={(event) => setExpectedGoal(event.target.value)} /></label>
				<section className={styles.readonlySource}><h3>来源范围 · 不可篡改</h3><p>{batchLabel} · {questionLabel}</p><div>{modelKeys.map((item) => <span key={item}>{item}</span>)}<span>{evidenceLabel}</span></div></section>
				{!availableMembers.length ? <div className={styles.drawerError}>当前没有可承接行动的成员，请先到管理中添加。</div> : null}
				{createError ? <div className={styles.drawerError} role="alert">{createError}</div> : null}
			</div>
			<footer><button type="button" onClick={() => setDrawerOpen(false)}>取消</button><button type="button" disabled={creating || !title.trim() || !expectedGoal.trim() || !assigneeId || !dueAt} onClick={createAction}>{creating ? "创建中…" : "创建并打开"}</button></footer>
		</aside></div> : null}
	</div>;
}
