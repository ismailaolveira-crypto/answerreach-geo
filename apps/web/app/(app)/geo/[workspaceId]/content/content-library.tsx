"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { CleanroomContentLibraryItem } from "@/lib/cleanroom-v1-api";
import styles from "./content-library.module.css";

const PLATFORM_META: Record<string, { label: string; logo?: string }> = {
	zhihu: { label: "知乎", logo: "/brand/zhihu.svg" },
	wechat: { label: "公众号", logo: "/brand/wechat.svg" },
	official_site: { label: "官网" },
	xiaohongshu: { label: "小红书" },
};

const FILTERS = [
	{ key: "all", label: "全部" },
	{ key: "review", label: "待审核" },
	{ key: "revision", label: "待修订" },
	{ key: "approved", label: "已通过" },
	{ key: "draft_saved", label: "已写草稿" },
] as const;

function itemState(item: CleanroomContentLibraryItem) {
	if (item.saved_draft_count > 0) return "draft_saved";
	if (item.asset.status === "superseded") return "superseded";
	if (item.latest_review_verdict === "changes_requested") return "revision";
	if (item.approved_platform_keys.length > 0) return "approved";
	return "review";
}

function stateLabel(state: string) {
	return {
		review: "待审核",
		revision: "待修订",
		approved: "已通过",
		draft_saved: "草稿已回读",
		superseded: "历史版本",
	}[state] || state;
}

function formatDate(value: string) {
	return new Intl.DateTimeFormat("zh-CN", {
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		hour12: false,
	}).format(new Date(value));
}

export function ContentLibrary({ workspaceId, items }: { workspaceId: string; items: CleanroomContentLibraryItem[] }) {
	const [status, setStatus] = useState<(typeof FILTERS)[number]["key"]>("all");
	const [platform, setPlatform] = useState("all");
	const platforms = useMemo(() => [...new Set(items.flatMap((item) => item.variants.map((variant) => variant.platform_key)))], [items]);
	const visibleItems = useMemo(() => items.filter((item) => {
		const state = itemState(item);
		const matchesStatus = status === "all" || state === status;
		const matchesPlatform = platform === "all" || item.variants.some((variant) => variant.platform_key === platform);
		return matchesStatus && matchesPlatform;
	}), [items, platform, status]);

	if (!items.length) return <section className={styles.empty}>
		<div aria-hidden="true">◇</div><h2>还没有内容资产</h2><p>从优化行动选择一个真实机会，完成 Agent 调研后，草稿会自动出现在这里。</p><Link href={`/geo/${workspaceId}/actions`}>去优化行动</Link>
	</section>;

	return <>
		<section className={styles.toolbar} aria-label="内容筛选">
			<div className={styles.segmented}>{FILTERS.map((filter) => <button type="button" key={filter.key} className={status === filter.key ? styles.active : ""} onClick={() => setStatus(filter.key)}>{filter.label}<span>{items.filter((item) => filter.key === "all" || itemState(item) === filter.key).length}</span></button>)}</div>
			<label><span>平台</span><select value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="all">全部平台</option>{platforms.map((key) => <option key={key} value={key}>{PLATFORM_META[key]?.label || key}</option>)}</select></label>
		</section>

		<section className={styles.list} aria-live="polite">
			{visibleItems.length ? visibleItems.map((item) => {
				const state = itemState(item);
				const reviewComplete = item.approved_platform_keys.length > 0;
				const draftComplete = item.saved_draft_count > 0;
				return <article className={styles.item} key={item.asset.id}>
					<header>
						<div className={styles.identity}><span className={`${styles.state} ${styles[state]}`}>{stateLabel(state)}</span><small>内容 #{item.asset.id} · v{item.asset.version} · {formatDate(item.asset.updated_at)}</small></div>
						<div className={styles.platforms} aria-label="平台版本">{item.variants.map((variant) => { const meta = PLATFORM_META[variant.platform_key]; return <span key={variant.id} title={`${meta?.label || variant.platform_key}：${variant.status}`}>{meta?.logo ? <img src={meta.logo} alt="" /> : null}{meta?.label || variant.platform_key}</span>; })}</div>
					</header>
					<div className={styles.copy}><small>{item.action_title}</small><h2>{item.asset.title}</h2><p>{item.asset.summary}</p>{item.latest_review_note ? <blockquote><b>人工意见</b>{item.latest_review_note}</blockquote> : null}</div>
					<div className={styles.flow} aria-label="内容进度">
						<div className={styles.done}><span>1</span><b>Agent 生成</b><small>已持久化</small></div>
						<div className={reviewComplete ? styles.done : state === "revision" ? styles.warning : styles.current}><span>2</span><b>人工审核</b><small>{reviewComplete ? `${item.approved_platform_keys.length} 个平台已通过` : state === "revision" ? "已退回修订" : `${item.pending_claim_count} 条待确认`}</small></div>
						<div className={draftComplete ? styles.done : reviewComplete ? styles.current : ""}><span>3</span><b>平台草稿</b><small>{draftComplete ? `${item.saved_draft_count}/${item.total_draft_targets} 已回读` : reviewComplete ? "可打开同步助手" : "尚未开放"}</small></div>
						<div><span>4</span><b>人工发布</b><small>未记录为已发布</small></div>
					</div>
					{item.draft_targets.some((target) => target.draft_url) ? <div className={styles.draftLinks}><b>已回读草稿</b>{item.draft_targets.filter((target) => target.draft_url).map((target) => { const meta = PLATFORM_META[target.platform_key]; return <a key={target.id} href={target.draft_url!} target="_blank" rel="noreferrer">{meta?.logo ? <img src={meta.logo} alt="" /> : null}打开{meta?.label || target.platform_key}草稿</a>; })}</div> : null}
					<details className={styles.details}>
						<summary>查看正文与 {item.variants.length} 个平台版本<span aria-hidden="true">›</span></summary>
						<div className={styles.documents}>
							<section><small>母稿 · v{item.asset.version}</small><h3>{item.asset.title}</h3><pre>{item.asset.body_markdown}</pre></section>
							{item.variants.map((variant) => <section key={variant.id}><small>{PLATFORM_META[variant.platform_key]?.label || variant.platform_key} · {variant.policy_version}</small><h3>{variant.title}</h3><pre>{variant.body_markdown}</pre></section>)}
						</div>
					</details>
					<footer><span>原始 Agent 工件与审核记录已保留</span><Link href={`/geo/${workspaceId}/actions`}>回到优化行动</Link></footer>
				</article>;
			}) : <div className={styles.noMatch}>当前筛选下没有内容。</div>}
		</section>
	</>;
}
