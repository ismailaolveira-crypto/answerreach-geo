"use server";

import { revalidatePath } from "next/cache";
import { repairQueueWorker } from "@/lib/cleanroom-v1-api";

export type WorkerRepairActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export async function repairWorkerAction(
  _previous: WorkerRepairActionState,
  formData: FormData,
): Promise<WorkerRepairActionState> {
  const workspaceId = String(formData.get("workspace_id") ?? "");
  if (!/^\d+$/.test(workspaceId)) {
    return { status: "error", message: "工作区无效，未执行修复。" };
  }
  try {
    const result = await repairQueueWorker(workspaceId);
    revalidatePath(`/geo/${workspaceId}`);
    revalidatePath(`/geo/${workspaceId}/operations`);
    const recovered = result.recovered_jobs + result.schedule_retries;
    const suffix = recovered > 0 ? ` 已恢复 ${recovered} 项中断工作。` : "";
    return {
      status: result.status === "needs_attention" ? "error" : "success",
      message: `${result.message}${suffix}`,
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "修复失败，请稍后再试。",
    };
  }
}
