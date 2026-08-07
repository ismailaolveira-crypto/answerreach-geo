"use server";

import { revalidatePath } from "next/cache";
import { updateCleanroomWorkspace } from "@/lib/cleanroom-v1-api";

export type SettingsActionState = { status: "idle" | "success" | "error"; message?: string };

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
