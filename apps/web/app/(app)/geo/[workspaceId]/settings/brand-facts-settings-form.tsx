"use client";

import { useMemo, useState } from "react";
import type { CleanroomBrandFact } from "@/lib/cleanroom-v1-api";
import { saveBrandFact, setBrandFactStatus } from "./actions";
import styles from "./settings.module.css";

type Feedback = { kind: "success" | "error"; message: string } | null;

function isPublicHttpUrl(value: string) {
	try {
		const url = new URL(value);
		return url.protocol === "https:" || url.protocol === "http:";
	} catch {
		return false;
	}
}

export function BrandFactsSettingsForm({ workspaceId, initialFacts }: { workspaceId: number; initialFacts: CleanroomBrandFact[] }) {
	const [facts, setFacts] = useState(initialFacts);
	const [title, setTitle] = useState("");
	const [statement, setStatement] = useState("");
	const [sourceUrl, setSourceUrl] = useState("");
	const [busyId, setBusyId] = useState<number | "new" | null>(null);
	const [feedback, setFeedback] = useState<Feedback>(null);
	const sourcedActiveFacts = useMemo(
		() => facts.filter((fact) => fact.status === "active" && Boolean(fact.source_url?.trim())),
		[facts],
	);

	async function createFact() {
		const cleanTitle = title.trim();
		const cleanStatement = statement.trim();
		const cleanSourceUrl = sourceUrl.trim();
		if (!cleanTitle || !cleanStatement || !cleanSourceUrl) {
			setFeedback({ kind: "error", message: "请完整填写事实名称、可公开陈述和公开来源。" });
			return;
		}
		if (!isPublicHttpUrl(cleanSourceUrl)) {
			setFeedback({ kind: "error", message: "公开来源必须是可访问的 http 或 https 地址。" });
			return;
		}
		setBusyId("new");
		setFeedback(null);
		try {
			const fact = await saveBrandFact(workspaceId, {
				title: cleanTitle,
				statement: cleanStatement,
				source_url: cleanSourceUrl,
			});
			setFacts((current) => [fact, ...current]);
			setTitle("");
			setStatement("");
			setSourceUrl("");
			setFeedback({ kind: "success", message: "品牌事实已保存；之后新启动的 Agent 会把它作为可追溯输入。" });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "品牌事实保存失败。" });
		} finally {
			setBusyId(null);
		}
	}

	async function toggleFact(fact: CleanroomBrandFact) {
		setBusyId(fact.id);
		setFeedback(null);
		try {
			const next = await setBrandFactStatus(
				workspaceId,
				fact.id,
				fact.status === "active" ? "inactive" : "active",
			);
			setFacts((current) => current.map((item) => item.id === next.id ? next : item));
			setFeedback({
				kind: "success",
				message: next.status === "active" ? "该事实已恢复使用。" : "该事实已停用；历史草稿不会被改写。",
			});
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "无法更新品牌事实状态。" });
		} finally {
			setBusyId(null);
		}
	}

	return <section className={styles.brandFactsCard}>
		<header className={styles.integrationHeader}>
			<div><span className={styles.integrationEyebrow}>04 · Agent 事实底座</span><h2>品牌事实库</h2><p>只把有公开来源、当前启用的事实交给新一轮 Agent。停用不会改写历史草稿。</p></div>
			<span className={sourcedActiveFacts.length ? styles.integrationReady : styles.integrationPending}>{sourcedActiveFacts.length ? `${sourcedActiveFacts.length} 条可用` : "等待补齐"}</span>
		</header>
		<div className={styles.brandFactsLayout}>
			<div className={styles.brandFactForm}>
				<label>事实名称<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：产品定位" maxLength={255} /></label>
				<label>可公开陈述<textarea value={statement} onChange={(event) => setStatement(event.target.value)} placeholder="填写可以直接出现在公开内容中的完整陈述，不要只写关键词。" rows={4} /></label>
				<label>公开来源 URL<input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://…" autoComplete="off" spellCheck={false} /></label>
				<p>来源将随事实交给 Agent，并在审核时保留。内部口头信息不应在这里伪装成公开证据。</p>
				<button type="button" onClick={createFact} disabled={busyId !== null}>{busyId === "new" ? "正在保存…" : "保存为可用事实"}</button>
			</div>
			<div className={styles.brandFactList}>
				<header><b>当前事实</b><small>{facts.length} 条记录 · {sourcedActiveFacts.length} 条参与新生成</small></header>
				{facts.length ? <div>{facts.map((fact) => <article key={fact.id} className={fact.status === "active" ? "" : styles.isInactive}>
					<div><span>{fact.status === "active" ? "使用中" : "已停用"}</span><b>{fact.title}</b><p>{fact.statement}</p>{fact.source_url ? <a href={fact.source_url} target="_blank" rel="noreferrer">查看公开来源 ↗</a> : <em>缺少公开来源，不满足官网成稿门禁</em>}</div>
					<button type="button" onClick={() => toggleFact(fact)} disabled={busyId !== null}>{busyId === fact.id ? "处理中…" : fact.status === "active" ? "停用" : "恢复"}</button>
				</article>)}</div> : <div className={styles.brandFactEmpty}><b>还没有可用品牌事实</b><p>官网当前无法回读产品正文。先补充至少一条带公开来源的事实，再启动官网成稿，可以避免消耗一次 Agent 只得到通用整改框架。</p></div>}
			</div>
		</div>
		{feedback ? <p className={`${styles.feedback} ${feedback.kind === "error" ? styles.error : styles.success}`} role="status">{feedback.message}</p> : null}
	</section>;
}
