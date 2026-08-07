"use server";

import { revalidatePath } from "next/cache";
import {
	getWorkspaceIntegrations,
	testWorkspaceIntegration,
	updateCleanroomWorkspace,
	updateWorkspaceIntegrations,
	type WorkspaceIntegrationSettings,
} from "@/lib/cleanroom-v1-api";

export type SettingsActionState = { status: "idle" | "success" | "error"; message?: string };

export async function readWorkspaceIntegrations(workspaceId: number): Promise<WorkspaceIntegrationSettings | null> {
	try {
		return await getWorkspaceIntegrations(workspaceId);
	} catch {
		return null;
	}
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
