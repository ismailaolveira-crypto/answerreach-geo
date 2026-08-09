"use client";

import { useActionState } from "react";
import { saveWorkspaceSettings, type SettingsActionState } from "./actions";
import styles from "./settings.module.css";

const initialState: SettingsActionState = { status: "idle" };

export function WorkspaceSettingsForm({
  workspace,
  readOnly = false,
}: {
  workspace: { id: number; brand_name: string; brand_aliases: string[]; website_url?: string | null };
  readOnly?: boolean;
}) {
  const [state, action, pending] = useActionState(saveWorkspaceSettings, initialState);
  return <form action={action} className={styles.form}>
    <input type="hidden" name="workspace_id" value={workspace.id} />
    <label>品牌名称<input name="brand_name" defaultValue={workspace.brand_name} required maxLength={255} disabled={readOnly} /></label>
    <label>品牌别名<textarea name="brand_aliases" defaultValue={workspace.brand_aliases.join("\n")} placeholder="每行一个别名，例如：春秋元泉、元泉" maxLength={1000} disabled={readOnly} /></label>
    <label>官网或主域名<input name="website_url" type="url" defaultValue={workspace.website_url ?? ""} placeholder="https://example.com" maxLength={500} disabled={readOnly} /></label>
    <p className={styles.hint}>这些信息用于识别后续真实回答中的品牌实体；不会改写历史答案。</p>
    {state.message ? <p className={`${styles.feedback} ${state.status === "error" ? styles.error : styles.success}`} role="status">{state.message}</p> : null}
    {readOnly ? <p className={styles.hint}>你当前是只读成员，可查看但不能修改工作区口径。</p> : <button type="submit" disabled={pending}>{pending ? "正在保存…" : "保存品牌设置"}</button>}
  </form>;
}
