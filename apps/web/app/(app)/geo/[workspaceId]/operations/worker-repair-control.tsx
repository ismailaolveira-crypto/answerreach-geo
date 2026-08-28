"use client";

import { useActionState } from "react";
import { repairWorkerAction, type WorkerRepairActionState } from "./actions";

const initialState: WorkerRepairActionState = { status: "idle" };

export function WorkerRepairControl({ workspaceId }: { workspaceId: string }) {
  const [state, action, pending] = useActionState(repairWorkerAction, initialState);
  return <div className="sy-worker-repair-control">
    <form action={action}>
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <button type="submit" disabled={pending}>
        <span aria-hidden="true">{pending ? "•••" : "↻"}</span>
        {pending ? "正在检测" : "检测并修复"}
      </button>
    </form>
    {state.message ? <p className={`is-${state.status}`} role="status">{state.message}</p> : null}
  </div>;
}
