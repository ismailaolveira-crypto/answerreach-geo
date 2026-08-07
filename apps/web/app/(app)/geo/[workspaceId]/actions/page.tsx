import { revalidatePath } from "next/cache";
import {
	createCleanroomAction,
	createCleanroomAgentRun,
	createCleanroomDistributionRun,
	decideCleanroomContentReview,
	discoverCleanroomActionOpportunities,
	getActionAgentRuns,
	getAgentRunEvents,
	getAgentRuntime,
	getCleanroomContentReviewPackage,
	getCleanroomDistributionRuns,
	getActionEvidenceSummary,
	getCleanroomActionOpportunities,
	getCleanroomActions,
	getQuestionLibrary,
	interruptCleanroomAgentRun,
	recordCleanroomDistributionClientResults,
	resumeCleanroomAgentRun,
	reviseCleanroomAgentRun,
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
	const assetIds = [...new Set(agentRuns.map((run) => Number(run.result_snapshot.asset_id)).filter((id) => Number.isInteger(id) && id > 0))];
	const [reviewPackages, distributionRuns] = await Promise.all([
		Promise.all(assetIds.map((assetId) => getCleanroomContentReviewPackage(workspaceId, assetId).catch(() => null))),
		getCleanroomDistributionRuns(workspaceId).catch(() => []),
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

	async function reviseAgent(runId: number, contentAssetId: number) {
		"use server";
		const run = await reviseCleanroomAgentRun(workspaceId, runId, contentAssetId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		revalidatePath(`/geo/${workspaceId}/content`);
		return run;
	}

	async function readAgentProgress(actionId: number) {
		"use server";
		const runs = await getActionAgentRuns(workspaceId, actionId);
		const latest = runs[0];
		const events = latest ? await getAgentRunEvents(workspaceId, latest.id) : [];
		return { runs, events };
	}

	async function decideReview(
		assetId: number,
		payload: { verdict: "approved" | "changes_requested"; confirmed_claim_ids: number[]; platform_keys: string[]; note?: string | null },
	) {
		"use server";
		const result = await decideCleanroomContentReview(workspaceId, assetId, payload);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function createDistribution(assetId: number, platformKeys: string[]) {
		"use server";
		const result = await createCleanroomDistributionRun(workspaceId, {
			content_asset_id: assetId,
			platform_keys: platformKeys,
			idempotency_key: `browser-client:${assetId}:${[...platformKeys].sort().join(",")}`,
		});
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function recordDistributionResults(
		runId: number,
		targets: Array<{ platform_key: string; request_status: "draft_saved" | "failed" | "cancelled"; draft_url?: string | null; external_draft_id?: string | null; message?: string | null }>,
	) {
		"use server";
		const result = await recordCleanroomDistributionClientResults(workspaceId, runId, targets);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	return <PriorityActionsWorkbench workspaceId={workspaceId} opportunities={opportunities} actions={actions} agentRuntime={agentRuntime} initialAgentRuns={agentRuns} initialReviewPackages={reviewPackages.filter((item): item is NonNullable<typeof item> => item !== null)} initialDistributionRuns={distributionRuns} createAction={createAction} startAgent={startAgent} interruptAgent={interruptAgent} resumeAgent={resumeAgent} reviseAgent={reviseAgent} readAgentProgress={readAgentProgress} decideReview={decideReview} createDistribution={createDistribution} recordDistributionResults={recordDistributionResults} discoverActions={discoverActions} />;
}
