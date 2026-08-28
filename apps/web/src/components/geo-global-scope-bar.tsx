"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Route } from "next";
import {
	GEO_SCOPE_KEYS,
	hasGeoScope,
	modelLogoPath,
	scopeOnlySearchParams,
	writeGeoScope,
	type GeoGlobalScope,
	type GeoGlobalScopeOptions,
	type GeoScopePreset,
} from "@/lib/geo-global-scope";
import styles from "./geo-global-scope-bar.module.css";

type Tab = "batches" | "models" | "questions";
type Props = { workspaceId: string; support?: "full" | "context" | "single-batch" };

const rangeLabels: Record<GeoScopePreset, string> = {
	"7d": "最近 7 天",
	"30d": "最近 30 天",
	"90d": "最近 90 天",
	"365d": "最近 1 年",
	custom: "自定义日期",
};
const batchStatusLabels: Record<string, string> = { completed: "已完成", success: "已完成", partial: "部分完成" };

function uniqueNumbers(values: number[]) {
	return [...new Set(values)].sort((a, b) => a - b);
}

function uniqueStrings(values: string[]) {
	return [...new Set(values)].sort();
}

function ScopeLayersIcon() {
	return <svg viewBox="0 0 40 40" role="img" aria-label="当前分析范围">
		<path d="m20 5.5 13.5 7.2L20 19.9 6.5 12.7 20 5.5Z" />
		<path d="m7.2 18.6 12.8 6.8 12.8-6.8" />
		<path d="m7.2 24.6 12.8 6.8 12.8-6.8" />
	</svg>;
}

export function GeoGlobalScopeBar({ workspaceId, support = "full" }: Props) {
	const pathname = usePathname();
	const router = useRouter();
	const searchParams = useSearchParams();
	const searchString = searchParams.toString();
	const panelRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const [options, setOptions] = useState<GeoGlobalScopeOptions | null>(null);
	const [draft, setDraft] = useState<GeoGlobalScope | null>(null);
	const [open, setOpen] = useState(false);
	const [tab, setTab] = useState<Tab>("batches");
	const [search, setSearch] = useState("");
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		if (hasGeoScope(new URLSearchParams(searchString))) return;
		const saved = window.localStorage.getItem(`cq-geo-scope:${workspaceId}`);
		if (!saved || !hasGeoScope(new URLSearchParams(saved))) return;
		const current = new URLSearchParams(searchString);
		const stored = new URLSearchParams(saved);
		for (const key of GEO_SCOPE_KEYS) {
			current.delete(key);
			for (const value of stored.getAll(key)) current.append(key, value);
		}
		router.replace(`${pathname}?${current.toString()}` as Route, { scroll: false });
	}, [pathname, router, searchString, workspaceId]);

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		setError("");
		const scopeQuery = scopeOnlySearchParams(new URLSearchParams(searchString));
		fetch(`/api/geo/${encodeURIComponent(workspaceId)}/global-scope-options?${scopeQuery.toString()}`, { cache: "no-store" })
			.then(async (response) => {
				const payload = await response.json();
				if (!response.ok) throw new Error(payload.detail || "范围数据暂时不可用");
				return payload as GeoGlobalScopeOptions;
			})
			.then((payload) => {
				if (cancelled) return;
				setOptions(payload);
				setDraft(payload.scope);
				const current = new URLSearchParams(searchString);
				const stored = window.localStorage.getItem(`cq-geo-scope:${workspaceId}`);
				if (!hasGeoScope(current) && (!stored || !hasGeoScope(new URLSearchParams(stored)))) {
					const canonical = writeGeoScope(current, payload.scope);
					window.localStorage.setItem(`cq-geo-scope:${workspaceId}`, scopeOnlySearchParams(canonical).toString());
					router.replace(`${pathname}?${canonical.toString()}` as Route, { scroll: false });
				}
			})
			.catch((reason) => {
				if (!cancelled) setError(reason instanceof Error ? reason.message : "范围数据暂时不可用");
			})
			.finally(() => { if (!cancelled) setLoading(false); });
		return () => { cancelled = true; };
	}, [pathname, router, searchString, workspaceId]);

	useEffect(() => {
		if (!open) return;
		const previousOverflow = document.body.style.overflow;
		document.body.classList.add("geo-scope-panel-open");
		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			setOpen(false);
			triggerRef.current?.focus();
		};
		document.addEventListener("keydown", onKeyDown);
		if (window.innerWidth < 720) document.body.style.overflow = "hidden";
		window.requestAnimationFrame(() => panelRef.current?.focus());
		return () => {
			document.removeEventListener("keydown", onKeyDown);
			document.body.style.overflow = previousOverflow;
			document.body.classList.remove("geo-scope-panel-open");
		};
	}, [open]);

	const selectedModels = useMemo(() => options?.models.filter((item) => draft?.model_keys.includes(item.key)) ?? [], [draft?.model_keys, options?.models]);
	const countLabel = draft ? `${draft.batch_ids.length} 个批次 · ${draft.model_keys.length} 个模型 · ${draft.question_plan_ids.length} 个问题` : "正在读取真实范围";
	const supportMessage = support === "context"
		? "此页继承时间、模型与问题范围；内容资产本身不按批次隐藏。"
		: support === "single-batch" && ((draft?.batch_ids.length ?? 0) > 1 || (draft?.model_keys.length ?? 0) > 1 || (draft?.question_plan_ids.length ?? 0) > 1)
			? "行动执行使用所选范围中最新批次及第一组模型、问题；历史对比仍保留完整多选范围。"
			: "";

	function toggleNumber(field: "batch_ids" | "question_plan_ids", value: number) {
		if (!draft) return;
		const current = draft[field];
		setDraft({ ...draft, [field]: current.includes(value) ? current.filter((item) => item !== value) : uniqueNumbers([...current, value]) });
	}

	function toggleModel(value: string) {
		if (!draft) return;
		setDraft({ ...draft, model_keys: draft.model_keys.includes(value) ? draft.model_keys.filter((item) => item !== value) : uniqueStrings([...draft.model_keys, value]) });
	}

	function apply() {
		if (!draft || !draft.batch_ids.length || !draft.model_keys.length || !draft.question_plan_ids.length) return;
		const next = writeGeoScope(new URLSearchParams(searchString), draft);
		const stored = new URLSearchParams();
		for (const key of GEO_SCOPE_KEYS) for (const value of next.getAll(key)) stored.append(key, value);
		window.localStorage.setItem(`cq-geo-scope:${workspaceId}`, stored.toString());
		setOpen(false);
		router.replace(`${pathname}?${next.toString()}` as Route, { scroll: false });
	}

	function openPanel() {
		setOpen(true);
	}

	const filteredQuestions = options?.questions.filter((item) => item.label.toLowerCase().includes(search.trim().toLowerCase())) ?? [];
	const filteredBatches = options?.batches.filter((item) => item.label.toLowerCase().includes(search.trim().toLowerCase())) ?? [];

	return <section className={`${styles.shell}${open ? ` ${styles.open}` : ""}`} aria-label="全局数据范围">
		<div className={styles.bar}>
			<div className={styles.scopeTitle}>
				<span className={styles.scopeIcon}><ScopeLayersIcon /></span>
				<div>
					<strong>当前分析范围</strong>
					<small>{loading ? "正在同步真实数据…" : error ? "范围数据暂时不可用" : "以下内容基于所选数据生成"}</small>
					<span className={styles.mobileScopeCount}>{draft ? `${draft.batch_ids.length} 次检测 · ${draft.model_keys.length} 个模型 · ${draft.question_plan_ids.length} 个问题` : "正在读取范围"}</span>
				</div>
			</div>
			<div className={styles.rangeSummary} aria-live="polite">
				<span className={styles.scopeMetric}>{draft ? rangeLabels[draft.range] : "—"}</span>
				<span className={styles.scopeMetric}>{draft ? `${draft.batch_ids.length} 次检测` : "—"}</span>
				<div className={`${styles.scopeMetric} ${styles.logoStack}`} aria-label={selectedModels.map((item) => item.label).join("、") || "未选择模型"}>
					{selectedModels.slice(0, 5).map((item) => {
						const logo = modelLogoPath(item.logo_key || item.key);
						return <i key={item.key} title={item.label}>{logo ? <img src={logo} alt="" /> : <b>{item.label.slice(0, 1)}</b>}</i>;
					})}
				</div>
				<span className={styles.scopeMetric}>{draft ? `${draft.question_plan_ids.length} 个问题` : "—"}</span>
			</div>
			<button ref={triggerRef} type="button" className={styles.trigger} onClick={openPanel} disabled={loading || Boolean(error)} aria-expanded={open} aria-haspopup="dialog">
				<span className={styles.desktopLabel}>更换范围</span><span className={styles.mobileLabel}>更换</span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5.5 3.5 4.5 4.5-4.5 4.5" /></svg>
			</button>
		</div>
		{error ? <div className={styles.error} role="status">{error}</div> : null}
		{supportMessage ? <span className={styles.srOnly}>{supportMessage}</span> : null}
		{options?.corrections.length ? <div className={styles.notice} role="status"><span>i</span><p>{options.corrections.join("；")}</p></div> : null}
		{open && options && draft ? <>
			<button className={styles.scrim} type="button" aria-label="关闭范围选择" onClick={() => setOpen(false)} />
			<div ref={panelRef} className={styles.panel} role="dialog" aria-modal="true" aria-label="选择全局数据范围" tabIndex={-1}>
				<header><div><small>统一所有页面的数据口径</small><h2>选择数据范围</h2></div><button type="button" onClick={() => setOpen(false)} aria-label="关闭">×</button></header>
				<div className={styles.dateRow}>
					<label><span>时间</span><select value={draft.range} onChange={(event) => setDraft({ ...draft, range: event.target.value as GeoScopePreset })}>{Object.entries(rangeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
					{draft.range === "custom" ? <><label><span>开始</span><input type="date" value={draft.date_from} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} /></label><label><span>结束</span><input type="date" value={draft.date_to} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} /></label></> : null}
				</div>
				<nav className={styles.tabs} aria-label="范围维度">
					<button type="button" className={tab === "batches" ? styles.active : ""} onClick={() => { setTab("batches"); setSearch(""); }}>批次 <b>{draft.batch_ids.length}</b></button>
					<button type="button" className={tab === "models" ? styles.active : ""} onClick={() => { setTab("models"); setSearch(""); }}>模型 <b>{draft.model_keys.length}</b></button>
					<button type="button" className={tab === "questions" ? styles.active : ""} onClick={() => { setTab("questions"); setSearch(""); }}>问题 <b>{draft.question_plan_ids.length}</b></button>
				</nav>
				<div className={styles.options}>
					{tab === "batches" ? <><input className={styles.search} type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索批次编号" aria-label="搜索批次" />{filteredBatches.map((item) => <label key={item.id} className={draft.batch_ids.includes(item.id) ? styles.selected : ""}><input type="checkbox" checked={draft.batch_ids.includes(item.id)} onChange={() => toggleNumber("batch_ids", item.id)} /><span><strong>{item.label}</strong><small>{item.provider_count} 个模型 · {item.question_count} 个问题 · {batchStatusLabels[item.status] ?? "可分析"}</small></span><i>✓</i></label>)}</> : null}
					{tab === "models" ? <div className={styles.modelGrid}>{options.models.map((item) => { const logo = modelLogoPath(item.logo_key || item.key); return <label key={item.key} className={draft.model_keys.includes(item.key) ? styles.selected : ""} title={item.label}><input type="checkbox" checked={draft.model_keys.includes(item.key)} onChange={() => toggleModel(item.key)} /><span>{logo ? <img src={logo} alt="" /> : <b>{item.label.slice(0, 1)}</b>}<em className={styles.srOnly}>{item.label}</em></span><i>✓</i></label>; })}</div> : null}
					{tab === "questions" ? <><input className={styles.search} type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索问题" aria-label="搜索问题" />{filteredQuestions.map((item) => <label key={item.id} className={draft.question_plan_ids.includes(item.id) ? styles.selected : ""}><input type="checkbox" checked={draft.question_plan_ids.includes(item.id)} onChange={() => toggleNumber("question_plan_ids", item.id)} /><span><strong>{item.label}</strong><small>重要度 {item.importance} · {item.journey_stage}</small></span><i>✓</i></label>)}</> : null}
				</div>
				<footer><span>{countLabel}</span><div><button type="button" onClick={() => { setDraft(options.scope); setOpen(false); }}>取消</button><button type="button" className={styles.apply} onClick={apply} disabled={!draft.batch_ids.length || !draft.model_keys.length || !draft.question_plan_ids.length}>应用范围</button></div></footer>
			</div>
		</> : null}
	</section>;
}
