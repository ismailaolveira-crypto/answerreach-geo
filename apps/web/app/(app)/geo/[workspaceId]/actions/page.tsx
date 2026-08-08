import { revalidatePath } from "next/cache";
import {
	captureAgentRunVisuals,
	createCleanroomAction,
	createCleanroomAgentRun,
	createCleanroomActionRetest,
	createCleanroomDistributionRun,
	decideCleanroomContentReview,
	discoverCleanroomActionOpportunities,
	getActionAgentRuns,
	getCleanroomActionWorkbenchState,
	getCleanroomActionRetest,
	getAgentRunProgress,
	getAgentRuntime,
	getCleanroomBrandFacts,
	getCleanroomActionOpportunityScope,
	getCleanroomActionOpportunities,
	getCleanroomOpportunityAnalysis,
	getLatestCleanroomOpportunityAnalysis,
	getCleanroomActions,
	interruptCleanroomAgentRun,
	recordCleanroomDistributionClientResults,
	confirmCleanroomHumanDraftReadback,
	recordCleanroomHumanPublication,
	resumeCleanroomAgentRun,
	reviseCleanroomAgentRun,
	updateCleanroomPlatformVariant,
	createWebsiteAudit,
	createWebsiteGapAnalysis,
	getLatestWebsiteGapAnalysis,
	getWebsiteGapAnalysis,
	getLatestWebsiteAudit,
} from "@/lib/cleanroom-v1-api";
import { PriorityActionsWorkbench } from "./priority-actions-workbench";
import { mapBackendPriorityActionOpportunities } from "./priority-action-opportunities";

type ActionsPageProps = {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function firstValue(value: string | string[] | undefined) {
	return Array.isArray(value) ? value[0] : value;
}

export default async function ActionsPage({ params, searchParams }: ActionsPageProps) {
	const [{ workspaceId }, query] = await Promise.all([params, searchParams]);
	const [actions, opportunityScope] = await Promise.all([
		getCleanroomActions(workspaceId),
		getCleanroomActionOpportunityScope(workspaceId),
	]);
	const requestedBatchId = Number(firstValue(query.batch));
	const batchId = opportunityScope.batches.some((batch) => batch.id === requestedBatchId)
		? requestedBatchId
		: opportunityScope.latest_batch_id ?? null;
	const selectedBatch = opportunityScope.batches.find((batch) => batch.id === batchId);
	const requestedModel = firstValue(query.model) ?? "all";
	const modelKey = requestedModel !== "all" && selectedBatch?.model_keys.includes(requestedModel)
		? requestedModel
		: null;
	const requestedQuestionId = Number(firstValue(query.question));
	const questionPlanId = selectedBatch?.question_plan_ids.includes(requestedQuestionId)
		? requestedQuestionId
		: null;
	const persistedOpportunities = await getCleanroomActionOpportunities(workspaceId, {
		batch_id: batchId,
		model_key: modelKey,
		question_plan_id: questionPlanId,
	});
	const [agentRuntime, workbenchState, websiteAuditOverview, brandFacts, opportunityAnalysis, websiteGapAnalysis] = await Promise.all([
		getAgentRuntime(workspaceId).catch(() => null),
		getCleanroomActionWorkbenchState(workspaceId),
		getLatestWebsiteAudit(workspaceId).catch(() => ({ website_url: null, latest: null })),
		getCleanroomBrandFacts(workspaceId).catch(() => []),
		batchId ? getLatestCleanroomOpportunityAnalysis(workspaceId, {
			batch_id: batchId,
			model_key: modelKey,
			question_plan_id: questionPlanId,
		}).catch(() => null) : Promise.resolve(null),
		batchId ? getLatestWebsiteGapAnalysis(workspaceId, {
			batch_id: batchId,
			model_key: modelKey,
			question_plan_id: questionPlanId,
		}).catch(() => null) : Promise.resolve(null),
	]);
	const { agent_runs: agentRuns, review_packages: reviewPackages, distribution_runs: distributionRuns, retests } = workbenchState;
	const opportunities = mapBackendPriorityActionOpportunities(persistedOpportunities, actions);
	const requestedActionId = Number(firstValue(query.action_id));
	const initialSelectedId = opportunities.find((item) => item.existingAction?.id === requestedActionId)?.id;

	async function discoverActions(scope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null }) {
		"use server";
		return discoverCleanroomActionOpportunities(workspaceId, {
			batch_id: scope.batchId,
			model_keys: scope.modelKey ? [scope.modelKey] : [],
			question_plan_ids: scope.questionPlanId ? [scope.questionPlanId] : [],
			max_items: 50,
		});
	}

	async function readOpportunityAnalysis(jobId: number) {
		"use server";
		return getCleanroomOpportunityAnalysis(workspaceId, jobId);
	}

	async function analyzeWebsiteGap(scope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null }) {
		"use server";
		if (!scope.batchId) throw new Error("请先选择一个已完成的观测批次");
		return createWebsiteGapAnalysis(workspaceId, {
			batch_id: scope.batchId,
			model_keys: scope.modelKey ? [scope.modelKey] : [],
			question_plan_ids: scope.questionPlanId ? [scope.questionPlanId] : [],
		});
	}

	async function readWebsiteGapAnalysis(jobId: number) {
		"use server";
		return getWebsiteGapAnalysis(workspaceId, jobId);
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

	async function captureAgentVisuals(runId: number) {
		"use server";
		const progress = await captureAgentRunVisuals(workspaceId, runId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		revalidatePath(`/geo/${workspaceId}/content`);
		return progress;
	}

	async function readAgentProgress(actionId: number) {
		"use server";
		const runs = await getActionAgentRuns(workspaceId, actionId);
		const latest = runs[0];
		const progress = latest ? await getAgentRunProgress(workspaceId, latest.id) : null;
		return { runs, progress };
	}

	async function decideReview(
		assetId: number,
		payload: { verdict: "approved" | "changes_requested"; confirmed_claim_ids: number[]; unverified_claim_ids: number[]; platform_keys: string[]; reviewed_platform_keys: string[]; note?: string | null },
	) {
		"use server";
		const result = await decideCleanroomContentReview(workspaceId, assetId, payload);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function savePlatformVariant(
		variantId: number,
		payload: { title: string; summary: string; body_markdown: string; tags?: string[]; category?: string | null },
	) {
		"use server";
		const result = await updateCleanroomPlatformVariant(workspaceId, variantId, payload);
		revalidatePath(`/geo/${workspaceId}/actions`);
		revalidatePath(`/geo/${workspaceId}/content`);
		return result;
	}

	async function createDistribution(assetId: number, platformKeys: string[]) {
		"use server";
		const deliveryMode = platformKeys.length === 1 && platformKeys[0] === "official_site"
			? "manual-website"
			: "browser-client";
		const result = await createCleanroomDistributionRun(workspaceId, {
			content_asset_id: assetId,
			platform_keys: platformKeys,
			idempotency_key: `${deliveryMode}:${assetId}:${[...platformKeys].sort().join(",")}`,
		});
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function recordDistributionResults(
		runId: number,
		targets: Array<{ platform_key: string; request_status: "draft_link_returned" | "draft_saved" | "failed" | "cancelled"; draft_url?: string | null; external_draft_id?: string | null; message?: string | null }>,
	) {
		"use server";
		const result = await recordCleanroomDistributionClientResults(workspaceId, runId, targets);
		revalidatePath(`/geo/${workspaceId}/actions`);
		revalidatePath(`/geo/${workspaceId}/content`);
		return result;
	}

	async function confirmDraftReadback(runId: number, targetId: number) {
		"use server";
		const result = await confirmCleanroomHumanDraftReadback(workspaceId, runId, targetId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		revalidatePath(`/geo/${workspaceId}/content`);
		return result;
	}

	async function recordHumanPublication(runId: number, targetId: number, publicUrl: string) {
		"use server";
		const result = await recordCleanroomHumanPublication(workspaceId, runId, targetId, publicUrl);
		revalidatePath(`/geo/${workspaceId}/actions`);
		revalidatePath(`/geo/${workspaceId}/content`);
		return result;
	}

	async function createRetest(actionId: number) {
		"use server";
		const result = await createCleanroomActionRetest(workspaceId, actionId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function readRetest(actionId: number) {
		"use server";
		return getCleanroomActionRetest(workspaceId, actionId);
	}

	async function runWebsiteAudit() {
		"use server";
		const result = await createWebsiteAudit(workspaceId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	return <PriorityActionsWorkbench workspaceId={workspaceId} opportunities={opportunities} opportunityScope={opportunityScope} initialScope={{ batchId, modelKey, questionPlanId }} initialSelectedId={initialSelectedId} actions={actions} agentRuntime={agentRuntime} activeSourcedBrandFactCount={brandFacts.filter((fact) => (
		fact.status === "active"
		&& fact.source_verification?.status === "source_and_statement_verified"
	)).length} websiteUrl={websiteAuditOverview.website_url ?? null} initialWebsiteAudit={websiteAuditOverview.latest ?? null} initialOpportunityAnalysis={opportunityAnalysis} initialWebsiteGapAnalysis={websiteGapAnalysis} initialAgentRuns={agentRuns} initialReviewPackages={reviewPackages} initialDistributionRuns={distributionRuns} initialRetests={retests} createAction={createAction} startAgent={startAgent} interruptAgent={interruptAgent} resumeAgent={resumeAgent} reviseAgent={reviseAgent} captureAgentVisuals={captureAgentVisuals} readAgentProgress={readAgentProgress} decideReview={decideReview} savePlatformVariant={savePlatformVariant} createDistribution={createDistribution} recordDistributionResults={recordDistributionResults} confirmDraftReadback={confirmDraftReadback} recordHumanPublication={recordHumanPublication} createRetest={createRetest} readRetest={readRetest} runWebsiteAudit={runWebsiteAudit} discoverActions={discoverActions} readOpportunityAnalysis={readOpportunityAnalysis} analyzeWebsiteGap={analyzeWebsiteGap} readWebsiteGapAnalysis={readWebsiteGapAnalysis} />;
}
