"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { OfficialApiObservationJobStatus } from "@/lib/cleanroom-v1-api";

export default function ObservationJobNotice({
  workspaceId,
  jobs,
}: {
  workspaceId: string;
  jobs: OfficialApiObservationJobStatus[];
}) {
  const router = useRouter();
  const pending = jobs.filter((job) => job.status === "pending").length;
  const running = jobs.filter((job) => job.status === "running").length;
  const succeeded = jobs.filter((job) => job.status === "success").length;
  const failed = jobs.filter((job) => job.status === "failed").length;
  const settled = pending === 0 && running === 0;
  const latestEvidenceId = [...jobs].reverse().find((job) => job.evidence_id)?.evidence_id;

  useEffect(() => {
    if (!settled) {
      const timer = window.setInterval(() => router.refresh(), 1800);
      return () => window.clearInterval(timer);
    }
    if (failed === 0 && latestEvidenceId) {
      const timer = window.setTimeout(
        () => router.replace(`/geo/${workspaceId}/evidence/${latestEvidenceId}?source=background-api`),
        700,
      );
      return () => window.clearTimeout(timer);
    }
  }, [failed, latestEvidenceId, router, settled, workspaceId]);

  return <div className={`sy-notice ${failed ? "sy-notice-error" : ""}`} role="status">
    <b>{settled ? (failed ? "本轮后台观测已结束" : "后台观测已完成") : "后台正在联网观测"}</b>
    <span>
      {succeeded ? `已完成 ${succeeded} 条；` : ""}
      {running ? `正在运行 ${running} 条；` : ""}
      {pending ? `队列等待 ${pending} 条；` : ""}
      {failed ? `失败 ${failed} 条。${jobs.find((job) => job.error_message)?.error_message ?? ""}` : "页面可以继续使用，无需停留等待。"}
    </span>
  </div>;
}
