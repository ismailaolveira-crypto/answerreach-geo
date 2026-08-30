import { notFound } from "next/navigation";
import { cookies } from "next/headers";

import {
	getAgentWorkspaceContextOptions,
	getAgentWorkspaceConversation,
	getAgentWorkspaceConversations,
	getWorkspaceMembers,
	type AgentWorkspaceContext,
} from "@/lib/cleanroom-v1-api";
import { AgentWorkspace } from "./workspace";

type PageProps = {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined) {
	return Array.isArray(value) ? value[0] : value;
}

export default async function AgentWorkspacePage({ params, searchParams }: PageProps) {
	const [{ workspaceId }, query, cookieStore] = await Promise.all([params, searchParams, cookies()]);
	const numericWorkspaceId = Number(workspaceId);
	if (!Number.isInteger(numericWorkspaceId) || numericWorkspaceId < 1) notFound();
	const [conversations, contextOptions, members] = await Promise.all([
		getAgentWorkspaceConversations(numericWorkspaceId),
		getAgentWorkspaceContextOptions(numericWorkspaceId),
		getWorkspaceMembers(numericWorkspaceId),
	]);
	const requestedConversationId = Number(first(query.conversation));
	const selectedSummary = conversations.find((item) => item.id === requestedConversationId) ?? conversations[0];
	const selectedConversation = selectedSummary
		? await getAgentWorkspaceConversation(numericWorkspaceId, selectedSummary.id)
		: null;
	const numberOrNull = (value: string | undefined) => {
		const parsed = Number(value);
		return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
	};
	const defaultContext: AgentWorkspaceContext = {
		batch_id: numberOrNull(first(query.batch)),
		question_plan_id: numberOrNull(first(query.question)),
		action_id: numberOrNull(first(query.action_id)),
		model_keys: (Array.isArray(query.model) ? query.model : query.model ? [query.model] : []).filter((item) => item !== "all"),
	};
	return (
		<AgentWorkspace
			workspaceId={numericWorkspaceId}
			initialSidebarCollapsed={cookieStore.get("answerreach_agent_sidebar_collapsed")?.value === "1"}
			initialConversations={conversations}
			initialSelected={selectedConversation}
			contextOptions={contextOptions}
			runtimes={[]}
			defaultContext={defaultContext}
			members={members}
		/>
	);
}
