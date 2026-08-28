import Link from "next/link";
import type { Route } from "next";

import { BrandLogo } from "@/components/brand-logo";
import styles from "./results.module.css";

type FilterProps = {
	workspaceId: string;
	periodDays: number;
	modelKey: string | null;
	questionPlanIds: number[];
	modelOptions: Array<{ key: string; label: string }>;
	questionOptions: Array<{ id: number; label: string }>;
	selectedActionId: number | null;
};

function modelBrand(value: string) {
	const key = value.toLowerCase();
	if (key.includes("qianwen") || key.includes("qwen")) return "qwen";
	if (key.includes("glm")) return "glm";
	if (key.includes("deepseek")) return "deepseek";
	if (key.includes("doubao")) return "doubao";
	if (key.includes("kimi")) return "kimi";
	if (key.includes("yuanbao") || key.includes("hunyuan")) return "yuanbao";
	return "";
}

export function ResultsFilters({ workspaceId, periodDays, modelKey, questionPlanIds, modelOptions, questionOptions, selectedActionId }: FilterProps) {
	function href(next: { period?: number; model?: string | null; questions?: number[] | null }) {
		const params = new URLSearchParams();
		const period = next.period ?? periodDays;
		const model = next.model === undefined ? modelKey : next.model;
		const questions = next.questions === undefined ? questionPlanIds : (next.questions ?? []);
		if (period !== 30) params.set("period", String(period));
		if (model) params.set("model", model);
		for (const questionId of questions) params.append("question", String(questionId));
		const query = params.toString();
		return `/geo/${workspaceId}/results${query ? `?${query}` : ""}` as Route;
	}
	const selectedQuestion = questionPlanIds.length === 1 ? questionOptions.find((item) => item.id === questionPlanIds[0]) : null;
	const selectedModel = modelOptions.find((item) => item.key === modelKey);
	return <div className={styles.filters}>
		<details className={styles.filterMenu}>
			<summary>最近 {periodDays === 365 ? "1 年" : `${periodDays} 天`}<span>⌄</span></summary>
			<div className={styles.filterPopover}>{[30, 90, 365].map((days) => <Link key={days} className={days === periodDays ? styles.filterActive : ""} href={href({ period: days })}>{days === 365 ? "最近 1 年" : `最近 ${days} 天`}<i>{days === periodDays ? "✓" : ""}</i></Link>)}</div>
		</details>
		<details className={`${styles.filterMenu} ${styles.modelFilter}`}>
			<summary>{selectedModel ? <><BrandLogo brand={modelBrand(selectedModel.key)} label={selectedModel.label} className={styles.filterModelLogo}/><span className={styles.srOnly}>{selectedModel.label}</span></> : "全部模型"}<span>⌄</span></summary>
			<div className={`${styles.filterPopover} ${styles.modelPopover}`}>
				<Link className={!modelKey ? styles.filterActive : ""} href={href({ model: null })}>全部模型<i>{!modelKey ? "✓" : ""}</i></Link>
				<div>{modelOptions.map((option) => { const brand=modelBrand(option.key); return <Link key={option.key} className={option.key === modelKey ? styles.filterActive : ""} href={href({ model: option.key })} title={option.label} aria-label={option.label}>{brand ? <BrandLogo brand={brand} label={option.label} className={styles.filterModelLogo}/> : <span>AI</span>}<i>{option.key === modelKey ? "✓" : ""}</i></Link>; })}</div>
			</div>
		</details>
		<details className={`${styles.filterMenu} ${styles.questionFilter}`}>
			<summary title={selectedQuestion?.label ?? "选择多个问题范围"}><b>{selectedQuestion?.label ?? (questionPlanIds.length ? `已选择 ${questionPlanIds.length} 个问题` : "问题范围 · 全部")}</b><span>⌄</span></summary>
			<form className={`${styles.filterPopover} ${styles.questionPopover}`} action={`/geo/${workspaceId}/results`} method="get">
				{periodDays !== 30 ? <input type="hidden" name="period" value={periodDays}/> : null}
				{modelKey ? <input type="hidden" name="model" value={modelKey}/> : null}
				<header>
					<b>选择问题范围</b>
					<div><Link href={href({ questions: questionOptions.map((item) => item.id) })}>全选</Link><Link href={href({ questions: null })}>清空</Link></div>
				</header>
				<div className={styles.questionChecks}>{questionOptions.map((option) => <label key={option.id}><input type="checkbox" name="question" value={option.id} defaultChecked={questionPlanIds.includes(option.id)}/><span>{option.label}</span><i>✓</i></label>)}</div>
				<footer><span>{questionPlanIds.length ? `已选择 ${questionPlanIds.length} 个` : "不选则查看全部"}</span><button type="submit">应用范围</button></footer>
			</form>
		</details>
		<Link className={styles.primaryAction} href={`/geo/${workspaceId}/actions${selectedActionId?`?action_id=${selectedActionId}`:""}` as Route}>创建复测</Link>
	</div>;
}
