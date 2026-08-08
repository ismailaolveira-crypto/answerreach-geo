import type { ActionEvidenceSummary, CleanroomAction, CleanroomActionOpportunity, CleanroomQuestion } from "@/lib/cleanroom-v1-api";

export type PriorityActionOpportunity = {
	id: string;
	backendId?: number;
	questionId: number;
	questionText: string;
	evidenceIds: number[];
	websiteAuditId?: number;
	sourceType: "model_observation" | "website_audit";
	modelLabels: string[];
	type: "visibility" | "citation" | "competitor" | "website";
	priority: "high" | "medium" | "low";
	title: string;
	summary: string;
	recommendedAsset: string;
	recommendedPlatforms: string[];
	generationReady: boolean;
	requiresSourcedBrandFacts: boolean;
	proof: string;
	existingAction?: CleanroomAction;
};

/** Convert persisted backend opportunities to the existing workbench view model. */
export function mapBackendPriorityActionOpportunities(
	rows: CleanroomActionOpportunity[],
	actions: CleanroomAction[],
): PriorityActionOpportunity[] {
	const actionByOpportunity = new Map(actions.filter((action) => action.opportunity_id).map((action) => [action.opportunity_id, action]));
	return rows.map((row) => {
		const questionId = Number(row.scope_snapshot.question_plan_id ?? 0);
		const questionText = String(row.scope_snapshot.question ?? row.title);
		const evidenceIds = row.evidence.map((item) => item.evidence_id);
		const sourceType = row.scope_snapshot.source_type === "website_audit" ? "website_audit" : "model_observation";
		const websiteAuditId = Number(row.scope_snapshot.website_audit_id ?? 0) || undefined;
		const websiteAuditHash = String(row.scope_snapshot.raw_html_sha256 ?? "");
		const findingCodes = Array.isArray(row.scope_snapshot.finding_codes)
			? row.scope_snapshot.finding_codes.map(String)
			: [];
		const type = row.opportunity_type === "website_citation_readiness"
			? "website"
			: row.opportunity_type === "competitor_gap"
				? "competitor"
				: row.opportunity_type === "citation_gap"
					? "citation"
					: "visibility";
		return {
			id: String(row.id),
			backendId: row.id,
			questionId,
			questionText,
			evidenceIds,
			websiteAuditId,
			sourceType,
			modelLabels: [...new Set(row.evidence.map((item) => item.model_key))],
			type,
			priority: row.priority_label,
			title: row.title,
			summary: row.summary,
			recommendedAsset: String(row.scope_snapshot.recommended_carrier ?? row.recommended_asset_type),
			recommendedPlatforms: row.recommended_platforms,
			generationReady: sourceType !== "website_audit"
				|| (row.scope_snapshot.website_audit_status !== "blocked" && Boolean(websiteAuditHash)),
			requiresSourcedBrandFacts: sourceType === "website_audit" && findingCodes.some((code) => [
				"client_rendering_required",
				"server_visible_content_missing",
				"server_visible_content_too_short",
			].includes(code)),
			proof: sourceType === "website_audit"
				? websiteAuditHash
					? `依据官网审计 #${websiteAuditId ?? "—"} · 原始证据 ${websiteAuditHash.slice(0, 12)}`
					: `依据官网审计 #${websiteAuditId ?? "—"} · 公网访问阻塞记录`
				: `依据 ${evidenceIds.length} 条真实证据 · 规则 ${row.rule_version}`,
			existingAction: actionByOpportunity.get(row.id),
		};
	});
}

const brandWins = new Set(["shortlisted", "recommended", "cited"]);

function sourceLabel(source: Record<string, unknown>) {
	const value = source.title ?? source.name ?? source.domain ?? source.url;
	return typeof value === "string" ? value : "已引用来源";
}

function competitorName(row: Record<string, unknown>) {
	const value = row.name ?? row.brand_name ?? row.competitor ?? row.entity_name;
	return typeof value === "string" ? value.trim() : "";
}

function buildExistingMap(actions: CleanroomAction[]) {
	return new Map(actions.filter((action) => action.question_plan_id).map((action) => [action.question_plan_id!, action]));
}

/**
 * Phase 1 action discovery: only uses persisted, real-provider evidence already in our database.
 * It deliberately does not invent a recommendation when there is no real answer to inspect.
 */
export function derivePriorityActionOpportunities({
	questions,
	evidence,
	actions,
}: {
	questions: CleanroomQuestion[];
	evidence: ActionEvidenceSummary[];
	actions: CleanroomAction[];
}): PriorityActionOpportunity[] {
	const questionById = new Map(questions.map((question) => [question.id, question]));
	const existingByQuestion = buildExistingMap(actions);
	const byQuestion = new Map<number, ActionEvidenceSummary[]>();

	for (const row of evidence) {
		if (!row.is_real_provider_evidence) continue;
		const collection = byQuestion.get(row.question_plan_id) ?? [];
		collection.push(row);
		byQuestion.set(row.question_plan_id, collection);
	}

	const opportunities: PriorityActionOpportunity[] = [];
	for (const [questionId, rows] of byQuestion) {
		const question = questionById.get(questionId);
		if (!question || rows.length === 0) continue;
		const modelLabels = [...new Set(rows.map((row) => row.model_label))];
		const evidenceIds = rows.map((row) => row.id);
		const absentRows = rows.filter((row) => !brandWins.has(row.brand_status));
		const citedSources = rows.flatMap((row) => row.source_items).filter((item) => Object.keys(item).length > 0);
		const competitors = [...new Set(rows.flatMap((row) => row.competitor_positions.map(competitorName)).filter(Boolean))];
		const existingAction = existingByQuestion.get(questionId);

		if (absentRows.length > 0 && competitors.length > 0) {
			opportunities.push({
				id: `${questionId}:visibility`, questionId, questionText: question.question_text,
				evidenceIds, modelLabels, type: "visibility", priority: absentRows.length === rows.length ? "high" : "medium",
				sourceType: "model_observation", recommendedPlatforms: ["zhihu", "juejin", "csdn", "51cto"],
				generationReady: true,
				requiresSourcedBrandFacts: false,
				title: "补齐采购决策入口", recommendedAsset: "采购选型 FAQ + 对比页",
				summary: `在 ${absentRows.length}/${rows.length} 条真实回答中，春秋元泉未进入候选；同题已出现 ${competitors.slice(0, 2).join("、")} 等竞品。`,
				proof: `依据 ${evidenceIds.length} 条已归档回答 · 覆盖 ${modelLabels.join("、")}`,
				existingAction,
			});
		}

		if (citedSources.length > 0 && rows.some((row) => row.brand_status !== "cited")) {
			const uniqueSources = [...new Set(citedSources.map(sourceLabel))];
			opportunities.push({
				id: `${questionId}:citation`, questionId, questionText: question.question_text,
				evidenceIds, modelLabels, type: "citation", priority: citedSources.length >= rows.length ? "high" : "medium",
				sourceType: "model_observation", recommendedPlatforms: ["zhihu", "juejin", "csdn", "51cto"],
				generationReady: true,
				requiresSourcedBrandFacts: false,
				title: "补齐可被引用的依据", recommendedAsset: "可引用的数据说明 / FAQ",
				summary: `模型在该问题中引用了 ${uniqueSources.slice(0, 2).join("、")} 等来源，但尚未引用春秋元泉的可控内容。`,
				proof: `依据 ${uniqueSources.length} 个真实引用来源 · ${rows.length} 条回答`,
				existingAction,
			});
		}
	}

	return opportunities
		.sort((a, b) => (a.existingAction ? 1 : 0) - (b.existingAction ? 1 : 0) || (a.priority === "high" ? -1 : 1))
		.slice(0, 12);
}
