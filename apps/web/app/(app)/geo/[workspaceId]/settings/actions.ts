"use server";

import { revalidatePath } from "next/cache";
import {
	createCleanroomBrandFact,
	discoverCleanroomBrandFactSourceCandidates,
	getAgentRuntime,
	getCleanroomBrandFacts,
	getWorkspaceIntegrations,
	testWorkspaceIntegration,
	testAgentRuntime,
	updateCleanroomWorkspace,
	updateCleanroomBrandFact,
	updateWorkspaceIntegrations,
	type CleanroomBrandFact,
	type CleanroomBrandFactSourceCandidates,
	type WorkspaceIntegrationSettings,
	type AgentRuntime,
} from "@/lib/cleanroom-v1-api";

export type SettingsActionState = { status: "idle" | "success" | "error"; message?: string };

export async function readWorkspaceIntegrations(workspaceId: number): Promise<WorkspaceIntegrationSettings | null> {
	try {
		return await getWorkspaceIntegrations(workspaceId);
	} catch {
		return null;
	}
}

export async function readAgentRuntime(workspaceId: number): Promise<AgentRuntime | null> {
	try {
		return await getAgentRuntime(workspaceId);
	} catch {
		return null;
	}
}

export async function runAgentRuntimeTest(workspaceId: number) {
	return testAgentRuntime(workspaceId);
}

export async function saveWorkspaceIntegrations(
	workspaceId: number,
	payload: { deepseek_api_key?: string; article_sync_mcp_server_path?: string; article_sync_mcp_token?: string },
) {
	return updateWorkspaceIntegrations(workspaceId, payload);
}

export async function runWorkspaceIntegrationTest(workspaceId: number, integration: "deepseek" | "article_sync_mcp") {
	return testWorkspaceIntegration(workspaceId, integration);
}

export async function readBrandFacts(workspaceId: number): Promise<CleanroomBrandFact[]> {
	try {
		return await getCleanroomBrandFacts(workspaceId);
	} catch {
		return [];
	}
}

export async function saveBrandFact(
	workspaceId: number,
	payload: { title: string; statement: string; source_url: string },
) {
	const fact = await createCleanroomBrandFact(workspaceId, payload);
	revalidatePath(`/geo/${workspaceId}/settings`);
	revalidatePath(`/geo/${workspaceId}/actions`);
	return fact;
}

export async function setBrandFactStatus(
	workspaceId: number,
	factId: number,
	status: "active" | "inactive",
) {
	const fact = await updateCleanroomBrandFact(workspaceId, factId, { status });
	revalidatePath(`/geo/${workspaceId}/settings`);
	revalidatePath(`/geo/${workspaceId}/actions`);
	return fact;
}

export async function verifyBrandFactSource(
	workspaceId: number,
	factId: number,
	sourceUrl: string,
) {
	const fact = await updateCleanroomBrandFact(workspaceId, factId, { source_url: sourceUrl });
	revalidatePath(`/geo/${workspaceId}/settings`);
	revalidatePath(`/geo/${workspaceId}/actions`);
	return fact;
}

export async function findBrandFactSourceCandidates(
	workspaceId: number,
	factId: number,
): Promise<CleanroomBrandFactSourceCandidates> {
	return discoverCleanroomBrandFactSourceCandidates(workspaceId, factId);
}

export async function saveEditedBrandFact(
	workspaceId: number,
	factId: number,
	payload: { title: string; statement: string; source_url: string },
) {
	const fact = await updateCleanroomBrandFact(workspaceId, factId, {
		...payload,
		status: "active",
	});
	revalidatePath(`/geo/${workspaceId}/settings`);
	revalidatePath(`/geo/${workspaceId}/actions`);
	return fact;
}

export async function saveWorkspaceSettings(
  _previous: SettingsActionState,
  formData: FormData,
): Promise<SettingsActionState> {
  const workspaceId = String(formData.get("workspace_id") ?? "");
  const brandName = String(formData.get("brand_name") ?? "").trim();
  const websiteUrl = String(formData.get("website_url") ?? "").trim();
  const aliases = String(formData.get("brand_aliases") ?? "")
    .split(/[\n,，]/)
    .map((value) => value.trim())
    .filter(Boolean);
  if (!workspaceId || !brandName) return { status: "error", message: "请填写品牌名称。" };
  try {
    await updateCleanroomWorkspace(workspaceId, {
      brand_name: brandName,
      brand_aliases: aliases,
      website_url: websiteUrl || null,
    });
    revalidatePath(`/geo/${workspaceId}`);
    revalidatePath(`/geo/${workspaceId}/settings`);
    return { status: "success", message: "已保存。新的品牌识别口径会用于之后归档的观测结果。" };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "保存失败，请稍后重试。" };
  }
}
