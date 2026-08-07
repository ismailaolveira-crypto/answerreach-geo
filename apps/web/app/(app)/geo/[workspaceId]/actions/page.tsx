import { revalidatePath } from "next/cache";
import {
	createCleanroomAction,
	createCleanroomAgentRun,
	discoverCleanroomActionOpportunities,
	getActionAgentRuns,
	getAgentRunEvents,
	getAgentRuntime,
	getActionEvidenceSummary,
	getCleanroomActionOpportunities,
	getCleanroomActions,
	getQuestionLibrary,
	interruptCleanroomAgentRun,
	resumeCleanroomAgentRun,
} from "@/lib/cleanroom-v1-api";
import { PriorityActionsWorkbench } from "./priority-actions-workbench";
import { derivePriorityActionOpportunities, mapBackendPriorityActionOpportunities } from "./priority-action-opportunities";

export default async function ActionsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
	const { workspaceId } = await params;
	const [actions, library, persistedOpportunities] = await Promise.all([
		getCleanroomActions(workspaceId),
		getQuestionLibrary(workspaceId),
		getCleanroomActionOpportunities(workspaceId),
	]);
	const [agentRuntime, runGroups] = await Promise.all([
		getAgentRuntime(workspaceId).catch(() => null),
		Promise.all(actions.map((action) => getActionAgentRuns(workspaceId, action.id).catch(() => []))),
	]);
	const agentRuns = runGroups.flat();
	const opportunities = persistedOpportunities.length > 0
		? mapBackendPriorityActionOpportunities(persistedOpportunities, actions)
		: derivePriorityActionOpportunities({
			questions: library.questions,
			evidence: await getActionEvidenceSummary(workspaceId),
			actions,
		});

	async function discoverActions() {
		"use server";
		await discoverCleanroomActionOpportunities(workspaceId, { max_items: 50 });
		revalidatePath(`/geo/${workspaceId}/actions`);
	}

	async function createAction(formData: FormData) {
		"use server";
		const title = String(formData.get("title") ?? "").trim();
		const rationale = String(formData.get("rationale") ?? "").trim();
		if (!title || !rationale) return;
		const opportunityId = Number(formData.get("opportunity_id")) || null;
		if (opportunityId) {
			await (await import("@/lib/cleanroom-v1-api")).selectCleanroomActionOpportunity(workspaceId, opportunityId);
		} else await createCleanroomAction(workspaceId, {
			title,
			rationale,
			hypothesis: String(formData.get("hypothesis") ?? "").trim() || null,
			priority: String(formData.get("priority") ?? "medium") as "high" | "medium" | "low",
			question_plan_id: Number(formData.get("question_plan_id")) || null,
			source_evidence_id: Number(formData.get("source_evidence_id")) || null,
		});
		revalidatePath(`/geo/${workspaceId}/actions`);
	}

	async function startAgent(actionId: number, platforms: string[]) {
		"use server";
		const run = await createCleanroomAgentRun(workspaceId, actionId, { selected_platforms: platforms });
		revalidatePath(`/geo/${workspaceId}/actions`);
		return run;
	}

	async function interruptAgent(runId: number) {
		"use server";
		const run = await interruptCleanroomAgentRun(workspaceId, runId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return run;
	}

	async function resumeAgent(runId: number) {
		"use server";
		const run = await resumeCleanroomAgentRun(workspaceId, runId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return run;
	}

	async function readAgentProgress(actionId: number) {
		"use server";
		const runs = await getActionAgentRuns(workspaceId, actionId);
		const latest = runs[0];
		const events = latest ? await getAgentRunEvents(workspaceId, latest.id) : [];
		return { runs, events };
	}

	return <PriorityActionsWorkbench workspaceId={workspaceId} opportunities={opportunities} actions={actions} agentRuntime={agentRuntime} initialAgentRuns={agentRuns} createAction={createAction} startAgent={startAgent} interruptAgent={interruptAgent} resumeAgent={resumeAgent} readAgentProgress={readAgentProgress} discoverActions={discoverActions} />;
}
