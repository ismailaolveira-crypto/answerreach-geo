import { revalidatePath } from "next/cache";
import { createHash, randomUUID } from "node:crypto";
import {
	type AgentExecutionSelection,
	type AgentRuntimeKey,
	type CodexReasoningEffort,
	type GeoArticleAssistantTask,
	captureAgentRunVisuals,
	acceptActionExecution,
	blockActionExecution,
	createCleanroomAction,
	createCleanroomAgentRun,
	createCleanroomActionRetest,
	createCleanroomDistributionRun,
	createTargetActionRetest,
	decideActionExecutionApproval,
	decideCleanroomContentReview,
	discoverCleanroomActionOpportunities,
	getActionAgentRuns,
	getActionExecutionDetail,
	getActionExecutionList,
	getCleanroomActionWorkbenchState,
	refreshCleanroomActionRetest,
	getAgentRunProgress,
	getAgentRuntimes,
	getCleanroomBrandFacts,
	getCleanroomActionOpportunityScope,
	getCleanroomActionOpportunities,
	getCleanroomOpportunityAnalysis,
	getLatestCleanroomOpportunityAnalysis,
	getCleanroomActions,
	interruptCleanroomAgentRun,
	issueGeoArticleAssistantTask,
	recordGeoArticleAssistantResults,
	confirmCleanroomHumanDraftReadback,
	recordCleanroomHumanPublication,
	resumeCleanroomAgentRun,
	reviseCleanroomAgentRun,
	updateCleanroomPlatformVariant,
	createWebsiteGapAnalysis,
	getLatestWebsiteGapAnalysis,
	getWebsiteGapAnalysis,
	getLatestWebsiteAudit,
	getWorkspaceMembers,
	requestActionExecutionApproval,
	selfApproveActionExecutionTarget,
	submitActionExecutionEvidence,
	transitionActionExecutionTarget,
	unblockActionExecution,
} from "@/lib/cleanroom-v1-api";
import { PriorityActionsWorkbench } from "./priority-actions-workbench";
import { ActionCommandCenter } from "./action-command-center";
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
	const [actions, opportunityScope, actionExecution, myActionExecution, approvalActionExecution, riskActionExecution, members] = await Promise.all([
		getCleanroomActions(workspaceId),
		getCleanroomActionOpportunityScope(workspaceId),
		getActionExecutionList(workspaceId),
		getActionExecutionList(workspaceId, "mine"),
		getActionExecutionList(workspaceId, "approvals"),
		getActionExecutionList(workspaceId, "overdue_blocked"),
		getWorkspaceMembers(workspaceId),
	]);
	const requestedBatchIds = (Array.isArray(query.batch) ? query.batch : query.batch ? [query.batch] : []).map(Number).filter((value) => Number.isInteger(value) && value > 0);
	const requestedBatchId = requestedBatchIds.length ? Math.max(...requestedBatchIds) : 0;
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
	const requestedActionId = Number(firstValue(query.action_id));
	const persistedOpportunities = await getCleanroomActionOpportunities(workspaceId, {
		batch_id: batchId,
		model_key: modelKey,
		question_plan_id: questionPlanId,
		action_id: Number.isInteger(requestedActionId) && requestedActionId > 0 ? requestedActionId : null,
	});
	const [workbenchState, websiteAuditOverview, brandFacts, opportunityAnalysis, websiteGapAnalysis] = await Promise.all([
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
	const initialSelectedId = opportunities.find((item) => item.existingAction?.id === requestedActionId)?.id;

	async function discoverActions(scope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null; runtimeKey: AgentRuntimeKey; agentModel: string | null; reasoningEffort: CodexReasoningEffort | null }) {
		"use server";
		return discoverCleanroomActionOpportunities(workspaceId, {
			batch_id: scope.batchId,
			model_keys: scope.modelKey ? [scope.modelKey] : [],
			question_plan_ids: scope.questionPlanId ? [scope.questionPlanId] : [],
			max_items: 50,
			runtime_key: scope.runtimeKey,
			model: scope.agentModel,
			reasoning_effort: scope.reasoningEffort,
		});
	}

	async function readOpportunityAnalysis(jobId: number) {
		"use server";
		return getCleanroomOpportunityAnalysis(workspaceId, jobId);
	}

	async function analyzeWebsiteGap(scope: { batchId: number | null; modelKey: string | null; questionPlanId: number | null; runtimeKey: AgentRuntimeKey; agentModel: string | null; reasoningEffort: CodexReasoningEffort | null }) {
		"use server";
		if (!scope.batchId) throw new Error("请先选择一个已完成的观测批次");
		return createWebsiteGapAnalysis(workspaceId, {
			batch_id: scope.batchId,
			model_keys: scope.modelKey ? [scope.modelKey] : [],
			question_plan_ids: scope.questionPlanId ? [scope.questionPlanId] : [],
			runtime_key: scope.runtimeKey,
			model: scope.agentModel,
			reasoning_effort: scope.reasoningEffort,
		});
	}

	async function readWebsiteGapAnalysis(jobId: number) {
		"use server";
		return getWebsiteGapAnalysis(workspaceId, jobId);
	}

	async function readAgentRuntimes() {
		"use server";
		return getAgentRuntimes(workspaceId);
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

	async function startAgent(actionId: number, platforms: string[], execution: AgentExecutionSelection) {
		"use server";
		const run = await createCleanroomAgentRun(workspaceId, actionId, {
			selected_platforms: platforms,
			runtime_key: execution.runtime_key,
			model: execution.model,
			reasoning_effort: execution.reasoning_effort,
		});
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

	async function issueArticleAssistantTask(runId: number) {
		"use server";
		return issueGeoArticleAssistantTask(workspaceId, runId);
	}

	async function recordArticleAssistantResults(
		runId: number,
		task: Pick<GeoArticleAssistantTask, "protocol_version" | "task_token" | "content_fingerprint">,
		targets: Array<{ platform_key: string; request_status: "draft_link_returned" | "failed" | "cancelled"; draft_url?: string | null; external_draft_id?: string | null; message?: string | null }>,
	) {
		"use server";
		const result = await recordGeoArticleAssistantResults(workspaceId, runId, task, targets);
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

	async function refreshRetest(actionId: number) {
		"use server";
		return refreshCleanroomActionRetest(workspaceId, actionId);
	}

	async function acceptExecution(actionId: number, assigneeUserId: number, dueAt: string) {
		"use server";
		const result = await acceptActionExecution(workspaceId, actionId, {
			assignee_user_id: assigneeUserId,
			due_at: dueAt,
		});
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function transitionExecution(actionId: number, targetId: number, toStatus: string) {
		"use server";
		const result = await transitionActionExecutionTarget(workspaceId, actionId, targetId, {
			to_status: toStatus,
			idempotency_key: `transition-${actionId}-${targetId}-${randomUUID()}`,
		});
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function submitExecutionEvidence(actionId: number, targetId: number, sourceUrl: string) {
		"use server";
		const action = await getActionExecutionDetail(workspaceId, actionId);
		const evidenceTypes = action.action_type === "official_site"
			? ["same_domain_readback"]
			: action.action_type === "structured_data"
				? ["source_code", "schema_validation"]
				: action.action_type === "third_party_source"
					? ["external_publication"]
					: ["public_url"];
		const verifiedTypes = new Set(action.evidence.filter((item) => item.target_id === targetId && item.verification_status === "verified").map((item) => item.evidence_type));
		const requestId = randomUUID();
		for (const evidenceType of evidenceTypes.filter((item) => !verifiedTypes.has(item))) {
			await submitActionExecutionEvidence(workspaceId, actionId, targetId, {
				evidence_type: evidenceType,
				source_url: sourceUrl,
				detail: { source: "action_command_center" },
				idempotency_key: `evidence-${actionId}-${targetId}-${evidenceType}-${requestId}`,
			});
		}
		revalidatePath(`/geo/${workspaceId}/actions`);
		return getActionExecutionDetail(workspaceId, actionId);
	}

	async function requestExecutionApproval(actionId: number, targetId: number, reviewerUserId: number, dueAt: string) {
		"use server";
		const action = await getActionExecutionDetail(workspaceId, actionId);
		const target = action.targets.find((item) => item.id === targetId);
		if (!target) throw new Error("行动目标不存在");
		const approvalType = target.delivery_status === "awaiting_fact_review"
			? "fact"
			: target.delivery_status === "awaiting_platform_review"
				? "platform_draft"
				: target.delivery_status === "awaiting_brand_legal_review"
					? "brand_legal"
					: "technical";
		const subjectFingerprint = createHash("sha256")
			.update(`${action.scope_fingerprint || "legacy"}:${target.id}:${target.delivery_status}:${target.updated_at}`)
			.digest("hex");
		await requestActionExecutionApproval(workspaceId, actionId, {
			target_id: targetId,
			approval_type: approvalType,
			reviewer_user_id: reviewerUserId,
			due_at: dueAt,
			subject_fingerprint: subjectFingerprint,
		});
		revalidatePath(`/geo/${workspaceId}/actions`);
		return getActionExecutionDetail(workspaceId, actionId);
	}

	async function decideExecutionApproval(actionId: number, approvalId: number, decision: "approved" | "changes_requested") {
		"use server";
		const result = await decideActionExecutionApproval(workspaceId, actionId, approvalId, { decision });
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function selfApproveExecution(actionId: number, targetId: number) {
		"use server";
		const result = await selfApproveActionExecutionTarget(workspaceId, actionId, targetId);
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function blockExecution(actionId: number, note: string) {
		"use server";
		const result = await blockActionExecution(workspaceId, actionId, { reason_code: "waiting_external", note });
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function unblockExecution(actionId: number) {
		"use server";
		const result = await unblockActionExecution(workspaceId, actionId, { note: "已确认可继续执行" });
		revalidatePath(`/geo/${workspaceId}/actions`);
		return result;
	}

	async function retestExecution(actionId: number, targetIds: number[]) {
		"use server";
		await createTargetActionRetest(workspaceId, actionId, {
			target_ids: targetIds,
			idempotency_key: `target-retest-${actionId}-${randomUUID()}`,
		});
		revalidatePath(`/geo/${workspaceId}/actions`);
		revalidatePath(`/geo/${workspaceId}/results`);
		return getActionExecutionDetail(workspaceId, actionId);
	}

	const legacyWorkbench = <PriorityActionsWorkbench workspaceId={workspaceId} hideGlobalScope opportunities={opportunities} scopeOpportunityIds={persistedOpportunities.filter((item) => item.opportunity_type !== "website_citation_readiness").map((item) => item.id)} opportunityScope={opportunityScope} initialScope={{ batchId, modelKey, questionPlanId }} initialSelectedId={initialSelectedId} actions={actions} initialAgentRuntimes={[]} activeSourcedBrandFactCount={brandFacts.filter((fact) => (
			fact.status === "active"
			&& fact.source_verification?.status === "source_and_statement_verified"
		)).length} websiteUrl={websiteAuditOverview.website_url ?? null} initialOpportunityAnalysis={opportunityAnalysis} initialWebsiteGapAnalysis={websiteGapAnalysis} initialAgentRuns={agentRuns} initialReviewPackages={reviewPackages} initialDistributionRuns={distributionRuns} initialRetests={retests} createAction={createAction} startAgent={startAgent} interruptAgent={interruptAgent} resumeAgent={resumeAgent} reviseAgent={reviseAgent} captureAgentVisuals={captureAgentVisuals} readAgentProgress={readAgentProgress} decideReview={decideReview} savePlatformVariant={savePlatformVariant} createDistribution={createDistribution} issueArticleAssistantTask={issueArticleAssistantTask} recordArticleAssistantResults={recordArticleAssistantResults} confirmDraftReadback={confirmDraftReadback} recordHumanPublication={recordHumanPublication} createRetest={createRetest} refreshRetestRequest={refreshRetest} discoverActions={discoverActions} readOpportunityAnalysis={readOpportunityAnalysis} analyzeWebsiteGap={analyzeWebsiteGap} readWebsiteGapAnalysis={readWebsiteGapAnalysis} readAgentRuntimes={readAgentRuntimes} />;

	return <ActionCommandCenter workspaceId={workspaceId} initialActions={actionExecution} initialSelectedActionId={Number.isInteger(requestedActionId) && requestedActionId > 0 ? requestedActionId : null} initialShowLegacy={firstValue(query.mode) === "legacy"} viewActionIds={{ all: actionExecution.map((item) => item.id), mine: myActionExecution.map((item) => item.id), approvals: approvalActionExecution.map((item) => item.id), overdue_blocked: riskActionExecution.map((item) => item.id) }} members={members} initialDistributionRuns={distributionRuns} legacyWorkbench={legacyWorkbench} onAccept={acceptExecution} onTransition={transitionExecution} onSubmitEvidence={submitExecutionEvidence} onRequestApproval={requestExecutionApproval} onDecideApproval={decideExecutionApproval} onSelfApprove={selfApproveExecution} onConfirmDraftReadback={confirmDraftReadback} onBlock={blockExecution} onUnblock={unblockExecution} onRetest={retestExecution} />;
}
