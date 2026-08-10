"use client";

import { useActionState, useState, type KeyboardEvent } from "react";
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
  const [aliases, setAliases] = useState(workspace.brand_aliases);
  const [aliasDraft, setAliasDraft] = useState("");

  function addAlias() {
    const value = aliasDraft.trim();
    if (!value || aliases.includes(value)) {
      setAliasDraft("");
      return;
    }
    setAliases((current) => [...current, value]);
    setAliasDraft("");
  }

  function handleAliasKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" && event.key !== ",") return;
    event.preventDefault();
    addAlias();
  }

  return <form action={action} className={styles.form}>
    <input type="hidden" name="workspace_id" value={workspace.id} />
    <label>品牌名称<input name="brand_name" defaultValue={workspace.brand_name} required maxLength={255} disabled={readOnly} /></label>
    <label>品牌别名
      <input type="hidden" name="brand_aliases" value={aliases.join("\n")} />
      <div className={styles.aliasEditor}>
        {aliases.map((alias) => <span key={alias}>{alias}{!readOnly ? <button type="button" onClick={() => setAliases((current) => current.filter((item) => item !== alias))} aria-label={`移除别名 ${alias}`}>×</button> : null}</span>)}
        {!readOnly ? <input value={aliasDraft} onChange={(event) => setAliasDraft(event.target.value)} onKeyDown={handleAliasKeyDown} onBlur={addAlias} placeholder={aliases.length ? "添加别名" : "输入别名后按回车"} maxLength={255} /> : null}
      </div>
    </label>
    <label>官网或主域名<input name="website_url" type="url" defaultValue={workspace.website_url ?? ""} placeholder="https://example.com" maxLength={500} disabled={readOnly} /></label>
    <p className={styles.hint}>这些信息用于识别后续真实回答中的品牌实体，不会改写或删除历史答案。</p>
    {state.message ? <p className={`${styles.feedback} ${state.status === "error" ? styles.error : styles.success}`} role="status">{state.message}</p> : null}
    {readOnly ? <p className={styles.hint}>你当前是只读成员，可查看但不能修改工作区口径。</p> : <div className={styles.saveBar}><span><b>品牌口径仅影响后续识别</b><small>保存后立即用于新观测与新生成。</small></span><button type="submit" disabled={pending}>{pending ? "正在保存…" : "保存品牌设置"}</button></div>}
  </form>;
}
