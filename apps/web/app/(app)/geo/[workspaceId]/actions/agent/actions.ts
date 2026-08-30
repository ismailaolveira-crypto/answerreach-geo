"use server";

import {
	createAgentWorkspaceConversation,
	createAgentWorkspaceSuggestionAction,
	getAgentWorkspaceConversation,
	getAgentWorkspaceConversations,
	getAgentRuntimes,
	sendAgentWorkspaceMessage,
	updateAgentWorkspaceConversation,
	type AgentRuntimeKey,
	type AgentWorkspaceContext,
	type CodexReasoningEffort,
} from "@/lib/cleanroom-v1-api";

export type AgentWorkspaceActionResult<T> = { ok: true; data: T } | { ok: false; error: string };

async function run<T>(work: () => Promise<T>): Promise<AgentWorkspaceActionResult<T>> {
	try {
		return { ok: true, data: await work() };
	} catch (error) {
		return { ok: false, error: error instanceof Error ? error.message : "操作失败，请稍后重试" };
	}
}

export async function loadAgentConversation(workspaceId: number, conversationId: number) {
	return run(() => getAgentWorkspaceConversation(workspaceId, conversationId));
}

export async function loadAgentConversations(workspaceId: number) {
	return run(() => getAgentWorkspaceConversations(workspaceId));
}

export async function loadAgentRuntimes(workspaceId: number) {
	return run(() => getAgentRuntimes(workspaceId));
}

export async function startAgentConversation(
	workspaceId: number,
	content: string,
	context: AgentWorkspaceContext,
	execution: { runtime_key: AgentRuntimeKey | "auto"; model?: string | null; reasoning_effort?: CodexReasoningEffort | null },
) {
	return run(async () => {
		const conversation = await createAgentWorkspaceConversation(workspaceId, { context });
		return sendAgentWorkspaceMessage(workspaceId, conversation.id, { content, ...execution });
	});
}

export async function continueAgentConversation(
	workspaceId: number,
	conversationId: number,
	content: string,
	execution: { runtime_key: AgentRuntimeKey | "auto"; model?: string | null; reasoning_effort?: CodexReasoningEffort | null },
) {
	return run(() => sendAgentWorkspaceMessage(workspaceId, conversationId, { content, ...execution }));
}

export async function saveAgentConversationContext(
	workspaceId: number,
	conversationId: number,
	context: AgentWorkspaceContext,
) {
	return run(() => updateAgentWorkspaceConversation(workspaceId, conversationId, { context }));
}

export async function archiveAgentConversation(workspaceId: number, conversationId: number) {
	return run(() => updateAgentWorkspaceConversation(workspaceId, conversationId, { status: "archived" }));
}

export async function createAgentSuggestionAction(
	workspaceId: number,
	conversationId: number,
	messageId: number,
	payload: { title: string; expected_goal: string; assignee_user_id: number; due_at: string },
) {
	return run(() => createAgentWorkspaceSuggestionAction(workspaceId, conversationId, messageId, payload));
}
