import { revalidatePath } from "next/cache";
import {
	createCleanroomAction,
	createCleanroomContentBrief,
	discoverCleanroomActionOpportunities,
	getActionEvidenceSummary,
	getCleanroomActionOpportunities,
	getCleanroomActions,
	getQuestionLibrary,
	updateCleanroomAction,
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

	async function updateActionStatus(formData: FormData) {
		"use server";
		const actionId = Number(formData.get("action_id"));
		if (!Number.isInteger(actionId)) return;
		const brief = await createCleanroomContentBrief(workspaceId, actionId, {});
		if (brief.status !== "ready") await updateCleanroomAction(workspaceId, actionId, { status: "in_progress" });
		revalidatePath(`/geo/${workspaceId}/actions`);
	}

	return <PriorityActionsWorkbench workspaceId={workspaceId} opportunities={opportunities} actions={actions} createAction={createAction} updateActionStatus={updateActionStatus} discoverActions={discoverActions} />;
}
