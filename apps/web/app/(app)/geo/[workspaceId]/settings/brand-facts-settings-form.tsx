"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { CleanroomBrandFact, CleanroomBrandFactSourceCandidate } from "@/lib/cleanroom-v1-api";
import { findBrandFactSourceCandidates, saveBrandFact, saveEditedBrandFact, setBrandFactStatus, verifyBrandFactSource } from "./actions";
import styles from "./settings.module.css";

type Feedback = { kind: "success" | "error"; message: string } | null;
type VerificationResult = { kind: "success" | "error"; message: string };
type BatchProgress = {
	status: "running" | "complete";
	completed: number;
	total: number;
	verified: number;
	failed: number;
	currentId: number | null;
	currentTitle: string | null;
} | null;
type CandidatePanelState = {
	status: "loading" | "ready" | "error";
	candidates: CleanroomBrandFactSourceCandidate[];
	checkedAt?: string;
	message?: string;
};

function isPublicHttpUrl(value: string) {
	try {
		const url = new URL(value);
		return url.protocol === "https:" || url.protocol === "http:";
	} catch {
		return false;
	}
}

function formatAttemptTime(value: string) {
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "最近";
	return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function BrandFactsSettingsForm({ workspaceId, initialFacts }: { workspaceId: number; initialFacts: CleanroomBrandFact[] }) {
	const [facts, setFacts] = useState(initialFacts);
	const [title, setTitle] = useState("");
	const [statement, setStatement] = useState("");
	const [sourceUrl, setSourceUrl] = useState("");
	const [editingId, setEditingId] = useState<number | null>(null);
	const [editTitle, setEditTitle] = useState("");
	const [editStatement, setEditStatement] = useState("");
	const [editSourceUrl, setEditSourceUrl] = useState("");
	const [busyId, setBusyId] = useState<number | "new" | "bulk" | null>(null);
	const [candidateBusyId, setCandidateBusyId] = useState<number | null>(null);
	const [candidatePanels, setCandidatePanels] = useState<Record<number, CandidatePanelState>>({});
	const [feedback, setFeedback] = useState<Feedback>(null);
	const [batchProgress, setBatchProgress] = useState<BatchProgress>(null);
	const [verificationResults, setVerificationResults] = useState<Record<number, VerificationResult>>({});
	const sourcedActiveFacts = useMemo(
		() => facts.filter((fact) => fact.status === "active" && fact.source_verification?.status === "source_and_statement_verified"),
		[facts],
	);
	const pendingActiveFacts = useMemo(
		() => facts.filter((fact) => fact.status === "active" && fact.source_verification?.status !== "source_and_statement_verified"),
		[facts],
	);
	const operationBusy = busyId !== null || candidateBusyId !== null;

	useEffect(() => {
		if (window.location.hash !== "#brand-facts") return;
		const frame = window.requestAnimationFrame(() => {
			document.getElementById("brand-facts")?.scrollIntoView({
				behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
				block: "start",
			});
		});
		return () => window.cancelAnimationFrame(frame);
	}, []);

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
			setFeedback({ kind: "success", message: "来源与公开原文已核验；之后新启动的 Agent 才会使用这条事实。" });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "品牌事实保存失败。" });
		} finally {
			setBusyId(null);
		}
	}

	async function verifyFact(fact: CleanroomBrandFact) {
		if (!fact.source_url) {
			setFeedback({ kind: "error", message: "该记录缺少公开来源，请编辑后重新核验。" });
			return;
		}
		setBusyId(fact.id);
		setFeedback(null);
		setVerificationResults((current) => {
			const next = { ...current };
			delete next[fact.id];
			return next;
		});
		try {
			const next = await verifyBrandFactSource(workspaceId, fact.id, fact.source_url);
			setFacts((current) => current.map((item) => item.id === next.id ? next : item));
			setVerificationResults((current) => ({ ...current, [fact.id]: { kind: "success", message: "公网可访问与完整原文均已通过。" } }));
			setFeedback({ kind: "success", message: `「${next.title}」已通过公网可访问与原文一致性核验。` });
		} catch (error) {
			const message = error instanceof Error ? error.message : "公开来源核验失败。";
			setVerificationResults((current) => ({ ...current, [fact.id]: { kind: "error", message } }));
			setFeedback({ kind: "error", message });
		} finally {
			setBusyId(null);
		}
	}

	async function verifyAllPendingFacts() {
		const queue = pendingActiveFacts.filter((fact) => fact.source_url);
		const missingSourceCount = pendingActiveFacts.length - queue.length;
		if (!queue.length) {
			setFeedback({ kind: "error", message: "待核验记录都缺少公开来源，请先逐条编辑补齐。" });
			return;
		}

		setBusyId("bulk");
		setFeedback(null);
		setVerificationResults({});
		let verified = 0;
		const failures: string[] = [];
		setBatchProgress({ status: "running", completed: missingSourceCount, total: pendingActiveFacts.length, verified: 0, failed: missingSourceCount, currentId: queue[0]?.id ?? null, currentTitle: queue[0]?.title ?? null });

		for (const [index, fact] of queue.entries()) {
			setBatchProgress({ status: "running", completed: missingSourceCount + index, total: pendingActiveFacts.length, verified, failed: missingSourceCount + failures.length, currentId: fact.id, currentTitle: fact.title });
			try {
				const next = await verifyBrandFactSource(workspaceId, fact.id, fact.source_url!);
				setFacts((current) => current.map((item) => item.id === next.id ? next : item));
				setVerificationResults((current) => ({ ...current, [fact.id]: { kind: "success", message: "公网可访问与完整原文均已通过。" } }));
				verified += 1;
			} catch (error) {
				const message = error instanceof Error ? error.message : "核验失败";
				setVerificationResults((current) => ({ ...current, [fact.id]: { kind: "error", message } }));
				failures.push(`${fact.title}：${message}`);
			}
			setBatchProgress({ status: "running", completed: missingSourceCount + index + 1, total: pendingActiveFacts.length, verified, failed: missingSourceCount + failures.length, currentId: null, currentTitle: null });
		}

		setBatchProgress({ status: "complete", completed: pendingActiveFacts.length, total: pendingActiveFacts.length, verified, failed: failures.length + missingSourceCount, currentId: null, currentTitle: null });
		if (failures.length || missingSourceCount) {
			const missingCopy = missingSourceCount ? `；${missingSourceCount} 条缺少来源` : "";
			setFeedback({ kind: "error", message: `已真实核验 ${verified}/${pendingActiveFacts.length} 条${missingCopy}。${failures[0] ? ` ${failures[0]}` : ""}` });
		} else {
			setFeedback({ kind: "success", message: `已逐条完成 ${verified} 条公网与原文核验。请返回优化行动生成新版，历史草稿不会被改写。` });
		}
		setBusyId(null);
	}

	function beginEdit(fact: CleanroomBrandFact, candidate?: CleanroomBrandFactSourceCandidate) {
		setEditingId(fact.id);
		setEditTitle(fact.title);
		setEditStatement(candidate?.statement ?? fact.statement);
		setEditSourceUrl(candidate?.source_url ?? fact.source_url ?? "");
		setFeedback(null);
	}

	async function findSourceCandidates(fact: CleanroomBrandFact) {
		if (!fact.source_url) {
			setFeedback({ kind: "error", message: "该记录缺少公开来源，请先编辑补齐 URL。" });
			return;
		}
		setCandidateBusyId(fact.id);
		setFeedback(null);
		setCandidatePanels((current) => ({
			...current,
			[fact.id]: { status: "loading", candidates: [] },
		}));
		try {
			const result = await findBrandFactSourceCandidates(workspaceId, fact.id);
			setCandidatePanels((current) => ({
				...current,
				[fact.id]: {
					status: "ready",
					candidates: result.candidates,
					checkedAt: result.checked_at,
					message: result.candidate_count
						? `找到 ${result.candidate_count} 段可供人工选择的官网公开原文。`
						: "没有找到符合事实引用标准的公开原文，请打开来源页人工核对。",
				},
			}));
		} catch (error) {
			const message = error instanceof Error ? error.message : "暂时无法读取官网公开原文。";
			setCandidatePanels((current) => ({
				...current,
				[fact.id]: { status: "error", candidates: [], message },
			}));
			setFeedback({ kind: "error", message });
		} finally {
			setCandidateBusyId(null);
		}
	}

	function cancelEdit() {
		setEditingId(null);
		setEditTitle("");
		setEditStatement("");
		setEditSourceUrl("");
	}

	async function saveEdit(fact: CleanroomBrandFact) {
		const cleanTitle = editTitle.trim();
		const cleanStatement = editStatement.trim();
		const cleanSourceUrl = editSourceUrl.trim();
		if (!cleanTitle || !cleanStatement || !cleanSourceUrl) {
			setFeedback({ kind: "error", message: "请完整填写事实名称、可公开陈述和公开来源。" });
			return;
		}
		if (!isPublicHttpUrl(cleanSourceUrl)) {
			setFeedback({ kind: "error", message: "公开来源必须是可访问的 http 或 https 地址。" });
			return;
		}
		setBusyId(fact.id);
		setFeedback(null);
		try {
			const next = await saveEditedBrandFact(workspaceId, fact.id, {
				title: cleanTitle,
				statement: cleanStatement,
				source_url: cleanSourceUrl,
			});
			setFacts((current) => current.map((item) => item.id === next.id ? next : item));
			setCandidatePanels((current) => {
				const updated = { ...current };
				delete updated[next.id];
				return updated;
			});
			cancelEdit();
			setFeedback({ kind: "success", message: `「${next.title}」已按新原文重新核验并启用。` });
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "无法保存并核验这条事实。" });
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
				message: next.status === "active" ? "公开来源已重新核验并恢复使用。" : "该事实已停用；历史草稿不会被改写。",
			});
		} catch (error) {
			setFeedback({ kind: "error", message: error instanceof Error ? error.message : "无法更新品牌事实状态。" });
		} finally {
			setBusyId(null);
		}
	}

	return <section id="brand-facts" className={styles.brandFactsCard}>
		<header className={styles.integrationHeader}>
			<div><span className={styles.integrationEyebrow}>04 · Agent 事实底座</span><h2>品牌事实库</h2><p>只把有公开来源、当前启用的事实交给新一轮 Agent。停用不会改写历史草稿。</p></div>
			<span className={sourcedActiveFacts.length ? styles.integrationReady : styles.integrationPending}>{sourcedActiveFacts.length ? `${sourcedActiveFacts.length} 条可用` : "等待补齐"}</span>
		</header>
		<div className={styles.brandFactsLayout}>
			<div className={styles.brandFactForm}>
				<label>事实名称<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：产品定位" maxLength={255} /></label>
				<label>可公开陈述<textarea value={statement} onChange={(event) => setStatement(event.target.value)} placeholder="粘贴官网页面实际展示的完整原文。" rows={4} /></label>
				<label>公开来源 URL<input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://…" autoComplete="off" spellCheck={false} /></label>
				<p>后端会先核验公网 HTML；如果官网依赖 JavaScript，只继续核验受限的同域公开前端资源。内部口头信息不应在这里伪装成公开证据。</p>
				<button type="button" onClick={createFact} disabled={operationBusy} aria-busy={busyId === "new"}>{busyId === "new" ? "正在核验来源…" : "核验并保存"}</button>
			</div>
			<div className={styles.brandFactList}>
				<header><div><b>当前事实</b><small>{facts.length} 条记录 · {sourcedActiveFacts.length} 条参与新生成</small></div>{pendingActiveFacts.length ? <button className={styles.verifyAllButton} type="button" onClick={verifyAllPendingFacts} disabled={operationBusy}>{busyId === "bulk" ? `正在核验 ${batchProgress?.completed ?? 0}/${batchProgress?.total ?? pendingActiveFacts.length}` : `核验全部 ${pendingActiveFacts.length} 条`}</button> : sourcedActiveFacts.length ? <Link className={styles.returnToActions} href={`/geo/${workspaceId}/actions`}>返回行动生成新版 →</Link> : null}</header>
				{batchProgress ? <div className={`${styles.batchProgress} ${batchProgress.status === "complete" ? batchProgress.failed ? styles.batchFailed : styles.batchComplete : ""}`} role="status" aria-live="polite"><div><b>{batchProgress.status === "running" ? batchProgress.currentTitle ? `正在核验「${batchProgress.currentTitle}」` : "正在整理核验结果" : batchProgress.failed ? "本轮核验已结束，仍有记录需处理" : "全部品牌事实已通过核验"}</b><small>{batchProgress.verified} 条通过{batchProgress.failed ? ` · ${batchProgress.failed} 条未通过` : ""} · 有公开来源的记录均由后端重新读取原文</small></div><progress value={batchProgress.completed} max={batchProgress.total} aria-label="品牌事实核验进度" /><span>{batchProgress.completed}/{batchProgress.total}</span></div> : null}
				{facts.length ? <div>{facts.map((fact) => {
					const verified = fact.source_verification?.status === "source_and_statement_verified";
					const inactive = fact.status !== "active";
					const attemptResult = verificationResults[fact.id];
					const persistedFailure = !attemptResult ? fact.source_verification_failure : null;
					if (editingId === fact.id) return <article key={fact.id} className={styles.factEditing}>
						<div className={styles.brandFactEditor}>
							<label>事实名称<input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} maxLength={255} /></label>
							<label>可公开陈述<textarea value={editStatement} onChange={(event) => setEditStatement(event.target.value)} rows={4} /></label>
							<label>公开来源 URL<input type="url" value={editSourceUrl} onChange={(event) => setEditSourceUrl(event.target.value)} autoComplete="off" spellCheck={false} /></label>
							<small>保存时会重新读取公网来源；只有完整原文存在才会更新并启用。</small>
						</div>
						<div className={styles.brandFactActions}><button type="button" onClick={() => saveEdit(fact)} disabled={operationBusy}>{busyId === fact.id ? "正在核验…" : "核验并保存"}</button><button type="button" onClick={cancelEdit} disabled={operationBusy}>取消</button></div>
					</article>;
					const candidatePanel = candidatePanels[fact.id];
					return <article key={fact.id} className={inactive ? styles.isInactive : ""}>
						<div><span className={inactive ? styles.factStatusInactive : verified ? styles.factStatusVerified : styles.factStatusPending}>{inactive ? "已停用" : verified ? "已核验" : "待核验"}</span><b>{fact.title}</b><p>{fact.statement}</p>{fact.source_url ? <a href={fact.source_url} target="_blank" rel="noreferrer">查看公开来源 ↗</a> : <em>缺少公开来源，不满足官网成稿门禁</em>}{verified && fact.source_verification?.verification_mode === "same_origin_public_javascript" ? <em className={styles.factVerificationNote}>原文来自官网同域公开前端资源；可作为 Agent 事实输入，但不代表搜索引擎能直接抓取首页正文。</em> : null}{!inactive && !verified ? <em>历史记录尚未完成公网与原文核验，当前不会交给 Agent。</em> : null}{attemptResult ? <em className={attemptResult.kind === "error" ? styles.factAttemptError : styles.factAttemptSuccess}>{attemptResult.kind === "error" ? "本次未通过：" : "本次已通过："}{attemptResult.message}</em> : persistedFailure ? <em className={styles.factAttemptError}>{formatAttemptTime(persistedFailure.attempted_at)} 核验未通过：{persistedFailure.detail}</em> : null}{!verified && candidatePanel ? <div className={`${styles.factCandidates} ${candidatePanel.status === "error" ? styles.factCandidatesError : ""}`} aria-live="polite" aria-busy={candidatePanel.status === "loading"}>{candidatePanel.status === "loading" ? <div className={styles.factCandidatesLoading}><i aria-hidden="true" /><span><b>正在读取官网公开文本</b><small>只检查当前来源页与受限的同域公开前端资源。</small></span></div> : <><header><div><b>{candidatePanel.candidates.length ? `找到 ${candidatePanel.candidates.length} 段官网原文` : "没有找到可用原文"}</b><small>{candidatePanel.message}</small></div><button type="button" onClick={() => setCandidatePanels((current) => { const next = { ...current }; delete next[fact.id]; return next; })}>收起</button></header>{candidatePanel.candidates.length ? <ol>{candidatePanel.candidates.map((candidate, index) => <li key={`${candidate.source_sha256}-${candidate.statement}`}><div><span>{candidate.verification_mode === "server_rendered_html" ? "官网可见正文" : "同域公开前端资源"}</span><small>候选 {index + 1}</small></div><p>{candidate.statement}</p><footer><a href={candidate.evidence_url} target="_blank" rel="noreferrer">查看证据资源 ↗</a><button type="button" onClick={() => beginEdit(fact, candidate)}>使用这段原文</button></footer></li>)}</ol> : null}</>}</div> : null}</div>
						<div className={styles.brandFactActions}>{!inactive && !verified ? <button type="button" onClick={() => verifyFact(fact)} disabled={operationBusy}>{busyId === fact.id || batchProgress?.currentId === fact.id ? "正在核验…" : "核验来源"}</button> : null}{!inactive && !verified && fact.source_url ? <button type="button" onClick={() => findSourceCandidates(fact)} disabled={operationBusy}>{candidateBusyId === fact.id ? "正在查找…" : candidatePanel?.status === "ready" ? "重新查找原文" : "查找官网原文"}</button> : null}<button type="button" onClick={() => beginEdit(fact)} disabled={operationBusy || editingId !== null}>编辑</button><button type="button" onClick={() => toggleFact(fact)} disabled={operationBusy || editingId !== null}>{busyId === fact.id ? "处理中…" : inactive ? "恢复并核验" : "停用"}</button></div>
					</article>;
				})}</div> : <div className={styles.brandFactEmpty}><b>还没有可用品牌事实</b><p>官网当前无法回读产品正文。先补充至少一条通过公网与原文核验的事实，再启动官网成稿。</p></div>}
			</div>
		</div>
		{feedback ? <p className={`${styles.feedback} ${feedback.kind === "error" ? styles.error : styles.success}`} role="status">{feedback.message}</p> : null}
	</section>;
}
