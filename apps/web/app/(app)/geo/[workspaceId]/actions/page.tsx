import { revalidatePath } from "next/cache";
import {
	createCleanroomAction,
	getCleanroomActions,
	getCleanroomEvidence,
	getQuestionLibrary,
	updateCleanroomAction,
} from "@/lib/cleanroom-v1-api";
import { PriorityActionsWorkbench } from "./priority-actions-workbench";
import { derivePriorityActionOpportunities } from "./priority-action-opportunities";

export default async function ActionsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
	const { workspaceId } = await params;
	const [actions, evidence, library] = await Promise.all([
		getCleanroomActions(workspaceId),
		getCleanroomEvidence(workspaceId),
		getQuestionLibrary(workspaceId),
	]);
	const opportunities = derivePriorityActionOpportunities({ questions: library.questions, evidence, actions });

	async function createAction(formData: FormData) {
		"use server";
		const title = String(formData.get("title") ?? "").trim();
		const rationale = String(formData.get("rationale") ?? "").trim();
		if (!title || !rationale) return;
		await createCleanroomAction(workspaceId, {
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
		await updateCleanroomAction(workspaceId, actionId, { status: "in_progress" });
		revalidatePath(`/geo/${workspaceId}/actions`);
	}

	return <PriorityActionsWorkbench workspaceId={workspaceId} opportunities={opportunities} actions={actions} createAction={createAction} updateActionStatus={updateActionStatus} />;
}
