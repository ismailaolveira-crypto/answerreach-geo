"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { CleanroomContentLibraryItem } from "@/lib/cleanroom-v1-api";
import { markdownToSafeHtml } from "@/lib/markdown-html";
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
	{ key: "stale", label: "需重新生成" },
	{ key: "revision", label: "待修订" },
	{ key: "approved", label: "已通过" },
	{ key: "draft_saved", label: "已写草稿" },
	{ key: "website_handoff", label: "官网待上线" },
	{ key: "published", label: "人工已发布" },
	{ key: "superseded", label: "历史版本" },
] as const;

function itemState(item: CleanroomContentLibraryItem) {
	if (!item.is_latest_version || item.asset.status === "superseded") return "superseded";
	if (item.draft_targets.some((target) => target.human_publish_status === "published" && target.public_url)) return "published";
	if (item.draft_targets.some((target) => target.platform_key === "official_site" && target.adapter_version === "manual-website.v1" && target.request_status === "handoff_ready")) return "website_handoff";
	if (item.saved_draft_count > 0) return "draft_saved";
	if (item.latest_review_verdict === "changes_requested") return "revision";
	if (item.brand_fact_snapshot_stale) return "stale";
	if (item.approved_platform_keys.length > 0) return "approved";
	return "review";
}

function stateLabel(state: string) {
	return {
		review: "待审核",
		stale: "事实快照过期",
		revision: "待修订",
		approved: "已通过",
		draft_saved: "草稿已回读",
		website_handoff: "官网待上线",
		published: "人工已发布",
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

type ExportFeedback = "copied" | "copy_error" | "downloaded";

function DocumentActions({ feedback, title, onCopy, onDownload }: { feedback?: ExportFeedback; title: string; onCopy: () => void; onDownload: () => void }) {
	return <div className={styles.documentActions}>
		<button type="button" onClick={onCopy}>{feedback === "copied" ? "已复制 Markdown" : feedback === "copy_error" ? "复制失败，请重试" : "复制 Markdown"}</button>
		<button type="button" onClick={onDownload}>{feedback === "downloaded" ? "已下载 .md" : "下载 .md"}</button>
		<span className={styles.srOnly} role="status" aria-live="polite">{feedback === "copied" ? `${title} 已复制` : feedback === "copy_error" ? `${title} 复制失败` : feedback === "downloaded" ? `${title} 已开始下载` : ""}</span>
	</div>;
}

export function ContentLibrary({ workspaceId, items }: { workspaceId: string; items: CleanroomContentLibraryItem[] }) {
	const [status, setStatus] = useState<(typeof FILTERS)[number]["key"]>("all");
	const [platform, setPlatform] = useState("all");
	const [exportFeedback, setExportFeedback] = useState<Record<string, ExportFeedback>>({});
	const platforms = useMemo(() => [...new Set(items.flatMap((item) => item.variants.map((variant) => variant.platform_key)))], [items]);
	const visibleItems = useMemo(() => items.filter((item) => {
		const state = itemState(item);
		const matchesStatus = status === "all" || state === status;
		const matchesPlatform = platform === "all" || item.variants.some((variant) => variant.platform_key === platform);
		return matchesStatus && matchesPlatform;
	}), [items, platform, status]);

	function documentMarkdown(title: string, bodyMarkdown: string) {
		const body = bodyMarkdown.trim();
		return `${body.startsWith("# ") ? "" : `# ${title}\n\n`}${body}\n`;
	}

	async function copyMarkdown(key: string, title: string, bodyMarkdown: string) {
		const markdown = documentMarkdown(title, bodyMarkdown);
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(markdown);
			} else {
				const field = document.createElement("textarea");
				field.value = markdown;
				field.style.position = "fixed";
				field.style.opacity = "0";
				document.body.appendChild(field);
				field.select();
				const copied = document.execCommand("copy");
				field.remove();
				if (!copied) throw new Error("copy failed");
			}
			setExportFeedback((current) => ({ ...current, [key]: "copied" }));
		} catch {
			setExportFeedback((current) => ({ ...current, [key]: "copy_error" }));
		}
	}

	function downloadMarkdown(key: string, fileName: string, title: string, bodyMarkdown: string) {
		const safeName = fileName.replace(/[\\/:*?"<>|]/g, "-").replace(/\s+/g, "-").slice(0, 80) || "content-draft";
		const url = URL.createObjectURL(new Blob([documentMarkdown(title, bodyMarkdown)], { type: "text/markdown;charset=utf-8" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = `${safeName}.md`;
		document.body.appendChild(link);
		link.click();
		link.remove();
		window.setTimeout(() => URL.revokeObjectURL(url), 0);
		setExportFeedback((current) => ({ ...current, [key]: "downloaded" }));
	}

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
				const canExport = state !== "superseded" && state !== "stale";
				const reviewComplete = item.approved_platform_keys.length > 0;
				const isWebsiteAsset = item.variants.length > 0 && item.variants.every((variant) => variant.platform_key === "official_site");
				const websiteHandoffReady = item.draft_targets.some((target) => target.platform_key === "official_site" && target.adapter_version === "manual-website.v1" && target.request_status === "handoff_ready");
				const draftComplete = item.saved_draft_count > 0;
				const deliveryComplete = isWebsiteAsset ? websiteHandoffReady : draftComplete;
				const publishedCount = item.draft_targets.filter((target) => target.human_publish_status === "published" && target.public_url).length;
				return <article className={`${styles.item} ${state === "superseded" ? styles.history : ""}`} key={item.asset.id}>
					<header>
						<div className={styles.identity}><span className={`${styles.state} ${styles[state]}`}>{stateLabel(state)}</span><small>内容 #{item.asset.id} · v{item.asset.version} · {formatDate(item.asset.updated_at)}</small></div>
						<div className={styles.platforms} aria-label="平台版本">{item.variants.map((variant) => { const meta = PLATFORM_META[variant.platform_key]; return <span key={variant.id} title={`${meta?.label || variant.platform_key}：${variant.status}`}>{meta?.logo ? <img src={meta.logo} alt="" /> : null}{meta?.label || variant.platform_key}</span>; })}</div>
					</header>
					<div className={styles.copy}><small>{item.action_title}</small><h2>{item.asset.title}</h2><p>{item.asset.summary}</p>{item.latest_review_note ? <blockquote><b>人工意见</b>{item.latest_review_note}</blockquote> : null}</div>
					{state === "stale" ? <div className={styles.staleNote} role="status"><b>需根据当前品牌事实重新生成</b><span>事实库已有 {item.available_sourced_brand_fact_count} 条带来源事实，本稿使用 {item.sourced_brand_fact_count} 条；审核已禁止直接通过。</span></div> : null}
					{state === "superseded" ? <div className={styles.historyNote}><b>已由 v{item.latest_version_number} 替代</b><span>仅保留正文和退回意见用于追溯，不再进入审核、交付或发布流程。</span></div> : <div className={styles.flow} aria-label="内容进度">
						<div className={styles.done}><span>1</span><b>Agent 生成</b><small>已持久化</small></div>
						<div className={reviewComplete ? styles.done : state === "revision" || state === "stale" ? styles.warning : styles.current}><span>2</span><b>人工审核</b><small>{reviewComplete ? `${item.approved_platform_keys.length} 个平台已通过` : state === "revision" ? "已退回修订" : state === "stale" ? "需退回生成新版" : `${item.pending_claim_count} 条待判断`}</small></div>
						<div className={deliveryComplete ? styles.done : reviewComplete ? styles.current : ""}><span>3</span><b>{isWebsiteAsset ? "官网交付" : "平台草稿"}</b><small>{isWebsiteAsset ? websiteHandoffReady ? "交付记录已建立" : reviewComplete ? "可建立交付记录" : "尚未开放" : draftComplete ? `${item.saved_draft_count}/${item.total_draft_targets} 已回读` : reviewComplete ? "可打开同步助手" : "尚未开放"}</small></div>
						<div className={publishedCount > 0 ? styles.done : deliveryComplete ? styles.current : ""}><span>4</span><b>{isWebsiteAsset ? "人工上线" : "人工发布"}</b><small>{publishedCount > 0 ? `${publishedCount}/${item.total_draft_targets} 已记录 URL` : deliveryComplete ? isWebsiteAsset ? "等待网站负责人上线" : "等待平台人工确认" : "尚未开放"}</small></div>
					</div>}
					{item.draft_targets.some((target) => target.draft_url) ? <div className={styles.draftLinks}><b>已回读草稿</b>{item.draft_targets.filter((target) => target.draft_url).map((target) => { const meta = PLATFORM_META[target.platform_key]; return <a key={target.id} href={target.draft_url!} target="_blank" rel="noreferrer">{meta?.logo ? <img src={meta.logo} alt="" /> : null}打开{meta?.label || target.platform_key}草稿</a>; })}</div> : null}
					{publishedCount > 0 ? <div className={styles.publicLinks}><b>人工发布记录</b>{item.draft_targets.filter((target) => target.public_url).map((target) => { const meta = PLATFORM_META[target.platform_key]; return <a key={target.id} href={target.public_url!} target="_blank" rel="noreferrer">{meta?.logo ? <img src={meta.logo} alt="" /> : null}查看{meta?.label || target.platform_key}公开文章</a>; })}</div> : null}
					<details className={styles.details}>
						<summary>查看正文与 {item.variants.length} 个平台版本<span aria-hidden="true">›</span></summary>
						<div className={styles.documents}>
							{state === "stale" ? <p className={`${styles.exportNote} ${styles.staleExport}`}>这版稿件没有使用当前品牌事实，仅供比对；请返回优化行动生成新版后再交付。</p> : state !== "superseded" ? <p className={styles.exportNote}>复制或下载只用于人工审核与交付，不会改变审核、草稿或发布状态。</p> : null}
							<section>
								<div className={styles.documentHeading}><div><small>母稿 · v{item.asset.version}</small><h3>{item.asset.title}</h3></div>{canExport ? <DocumentActions feedback={exportFeedback[`asset-${item.asset.id}`]} title={item.asset.title} onCopy={() => copyMarkdown(`asset-${item.asset.id}`, item.asset.title, item.asset.body_markdown)} onDownload={() => downloadMarkdown(`asset-${item.asset.id}`, `${item.asset.title}-母稿-v${item.asset.version}`, item.asset.title, item.asset.body_markdown)} /> : null}</div>
								<div className={styles.markdown} dangerouslySetInnerHTML={{ __html: markdownToSafeHtml(item.asset.body_markdown) }} />
							</section>
							{item.variants.map((variant) => { const label = PLATFORM_META[variant.platform_key]?.label || variant.platform_key; return <section key={variant.id}>
								<div className={styles.documentHeading}><div><small>{label} · {variant.policy_version}</small><h3>{variant.title}</h3></div>{canExport ? <DocumentActions feedback={exportFeedback[`variant-${variant.id}`]} title={variant.title} onCopy={() => copyMarkdown(`variant-${variant.id}`, variant.title, variant.body_markdown)} onDownload={() => downloadMarkdown(`variant-${variant.id}`, `${variant.title}-${label}-v${variant.version}`, variant.title, variant.body_markdown)} /> : null}</div>
								<div className={styles.markdown} dangerouslySetInnerHTML={{ __html: markdownToSafeHtml(variant.body_markdown) }} />
							</section>; })}
						</div>
					</details>
					<footer><span>{state === "superseded" ? "历史正文、原始 Agent 工件与退回意见已保留" : state === "stale" ? `当前事实库 ${item.available_sourced_brand_fact_count} 条，本稿使用 ${item.sourced_brand_fact_count} 条；直接通过已被阻止` : "原始 Agent 工件与审核记录已保留"}</span><Link href={`/geo/${workspaceId}/actions`}>{state === "stale" ? "处理并生成新版" : "回到优化行动"}</Link></footer>
				</article>;
			}) : <div className={styles.noMatch}>当前筛选下没有内容。</div>}
		</section>
	</>;
}
