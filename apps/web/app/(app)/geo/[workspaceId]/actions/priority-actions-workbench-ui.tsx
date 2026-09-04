import type { ReactNode } from "react";
import { BrandLogo } from "@/components/brand-logo";
import { capturedVisualPurpose } from "@/lib/captured-visual";
import { markdownToSafeHtml } from "@/lib/markdown-html";
import type {
	AgentRuntime,
	CodexReasoningEffort,
	CleanroomAction,
	CleanroomAgentEvent,
	CleanroomPlatformVariant,
} from "@/lib/cleanroom-v1-api";
import type { PriorityActionOpportunity } from "./priority-action-opportunities";

export const priorityLabel = { high: "高优先级", medium: "中优先级", low: "持续观察" } as const;
export const reasoningEffortLabels: Record<CodexReasoningEffort, string> = {
	none: "关闭",
	minimal: "极低",
	low: "低",
	medium: "中",
	high: "高",
	xhigh: "超高",
	max: "最高",
	ultra: "极致",
};

export function agentExecutionLabel(model?: string | null, effort?: CodexReasoningEffort | null) {
	return [model, effort ? `${reasoningEffortLabels[effort]}推理` : null].filter(Boolean).join(" · ");
}

export function runtimeConnectionLabel(runtime: AgentRuntime, long = false) {
	if (!runtime.ready) return "未配置";
	if (runtime.connection_status === "warm") return long ? "常驻已连接" : "已连接";
	if (runtime.connection_status === "configured") return "已配置";
	return "已就绪";
}

export type ReviewVisualAsset = {
	artifactId: number;
	altText: string;
	purpose: string;
	sourceHost: string;
	sourceUrl: string;
	sha256: string;
	strategy: "generate" | "web_search";
	decisionReason: string;
	caption: string;
	placement: string;
	licenseName: string;
	recommendedPlatforms: string[];
};

export function reviewVisualAssets(variants: CleanroomPlatformVariant[]): ReviewVisualAsset[] {
	const items = new Map<number, ReviewVisualAsset>();
	for (const variant of variants) {
		for (const manifest of variant.image_manifest) {
			const artifactId = Number(manifest.artifact_id || 0);
			const sourceUrl = typeof manifest.source_url === "string" ? manifest.source_url : "";
			const generated = manifest.strategy === "generate";
			if (artifactId < 1 || manifest.quality_gate !== "passed" || (!generated && !sourceUrl)) continue;
			let sourceHost = generated ? "Codex Image2" : sourceUrl;
			if (!generated) {
				try {
					sourceHost = new URL(sourceUrl).hostname;
				} catch {
					continue;
				}
			}
			items.set(artifactId, {
				artifactId,
				altText: typeof manifest.alt_text === "string" ? manifest.alt_text : "官网归档素材",
				purpose: capturedVisualPurpose(manifest.purpose),
				sourceHost,
				sourceUrl,
				sha256: typeof manifest.sha256 === "string" ? manifest.sha256 : "",
				strategy: generated ? "generate" : "web_search",
				decisionReason: typeof manifest.decision_reason === "string" ? manifest.decision_reason : "已按内容类型自动选择配图方式",
				caption: typeof manifest.caption === "string" ? manifest.caption : "",
				placement: typeof manifest.placement === "string" ? manifest.placement : "after_intro",
				licenseName: typeof manifest.license_name === "string" ? manifest.license_name : "",
				recommendedPlatforms: Array.isArray(manifest.recommended_platforms) ? manifest.recommended_platforms.map(String) : [],
			});
		}
	}
	return [...items.values()];
}

function escapeInlineHtml(value: string) {
	return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

export function articleHtmlWithVisuals(body: string, visuals: ReviewVisualAsset[], workspaceId: string) {
	let html = markdownToSafeHtml(body);
	for (const visual of visuals) {
		const image = `<figure class="pa-article-visual"><img src="/api/geo/${encodeURIComponent(workspaceId)}/agent-artifacts/${visual.artifactId}/content" alt="${escapeInlineHtml(visual.altText)}" />${visual.caption ? `<figcaption>图注：${escapeInlineHtml(visual.caption)}</figcaption>` : ""}</figure>`;
		if (visual.placement === "cover") {
			html = `${image}${html}`;
			continue;
		}
		const paragraphEnds = [...html.matchAll(/<\/p>/gi)];
		const sectionMatch = visual.placement.match(/^after_section_(\d+)$/);
		const requestedIndex = sectionMatch ? Math.max(0, Number(sectionMatch[1])) : 0;
		const match = paragraphEnds[Math.min(requestedIndex, Math.max(0, paragraphEnds.length - 1))];
		if (!match || match.index === undefined) {
			html = `${html}${image}`;
			continue;
		}
		const offset = match.index + match[0].length;
		html = `${html.slice(0, offset)}${image}${html.slice(offset)}`;
	}
	return html;
}

export function visualPlacementLabel(placement: string) {
	if (placement === "cover") return "首图";
	if (placement === "after_intro") return "导语后";
	const sectionMatch = placement.match(/^after_section_(\d+)$/);
	return sectionMatch ? `正文第 ${sectionMatch[1]} 节后` : "正文中";
}

export function suggestedSources(type: PriorityActionOpportunity["type"]) {
	if (type === "website") return ["服务端正文", "页面标题结构", "结构化数据"];
	if (type === "citation") return ["关键指标释义", "应用场景说明", "行业解决方案"];
	if (type === "competitor") return ["客户证言", "权威媒体报道", "第三方评测"];
	return ["企业选型对比", "私有化部署说明", "真实客户案例"];
}

export function suggestedCarrier(type: PriorityActionOpportunity["type"]) {
	if (type === "website") return "官网服务端正文 + FAQ";
	if (type === "citation") return "官网解决方案页 + 技术文章";
	if (type === "competitor") return "深度回答 + 媒体稿件";
	return "官网专题页 + 深度回答";
}

function modelBrand(label: string) {
	const value = label.toLowerCase();
	if (value.includes("deepseek")) return "deepseek";
	if (value.includes("doubao") || value.includes("豆包")) return "doubao";
	if (value.includes("qwen") || value.includes("qianwen") || value.includes("千问")) return "qwen";
	if (value.includes("glm") || value.includes("智谱")) return "glm";
	if (value.includes("kimi") || value.includes("moonshot")) return "kimi";
	if (value.includes("hunyuan") || value.includes("混元")) return "hunyuan";
	return null;
}

export function ModelBadge({ label }: { label: string }) {
	const brand = modelBrand(label);
	return <span className="pa-model-badge">{brand ? <BrandLogo brand={brand} label={label} className="pa-model-logo" /> : <i>AI</i>}<b>{label}</b></span>;
}

export function Icon({ name }: { name: "warning" | "trend" | "draft" | "check" | "chevron" | "arrow" | "quote" | "spark" | "calendar" | "filter" | "eye" }) {
	const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
	return <svg viewBox="0 0 24 24" aria-hidden="true">
		{name === "warning" && <><path {...common} d="M12 4 3.8 19h16.4L12 4Z" /><path {...common} d="M12 9v4.3M12 16.8h.01" /></>}
		{name === "trend" && <><path {...common} d="M4 18V6M4 18h16" /><path {...common} d="m7 14 3.5-3.4 2.7 1.8L18 7" /></>}
		{name === "draft" && <><path {...common} d="M6 3.8h8l4 4V20H6z" /><path {...common} d="M14 3.8V8h4M9 12h6M9 15.5h4" /></>}
		{name === "check" && <path {...common} d="m5 12.5 4.2 4.2L19 7" />}
		{name === "chevron" && <path {...common} d="m8 10 4 4 4-4" />}
		{name === "arrow" && <path {...common} d="M5 12h13M13 7l5 5-5 5" />}
		{name === "quote" && <path {...common} d="M7.8 10H4.5v3.2h3.1c0 2-1 3.6-2.8 4.5m12.7-7.7h-3.3v3.2h3.1c0 2-1 3.6-2.8 4.5" />}
		{name === "spark" && <path {...common} d="m12 3 1.5 5.8L19 10.5l-5.5 1.7L12 18l-1.5-5.8L5 10.5l5.5-1.7z" />}
		{name === "calendar" && <><rect {...common} x="4" y="5.5" width="16" height="14" rx="2" /><path {...common} d="M8 3.5v4M16 3.5v4M4 10h16" /></>}
		{name === "filter" && <><path {...common} d="M4 6h16M7 12h10M10 18h4" /></>}
		{name === "eye" && <><path {...common} d="M2.7 12s3.3-5.1 9.3-5.1 9.3 5.1 9.3 5.1-3.3 5.1-9.3 5.1S2.7 12 2.7 12Z" /><circle {...common} cx="12" cy="12" r="2" /></>}
	</svg>;
}

export function actionStage(action?: CleanroomAction) {
	if (!action) return 0;
	if (["verified", "closed"].includes(action.status)) return 4;
	return 1;
}

export function initialSelectedOpportunityId(opportunities: PriorityActionOpportunity[]) {
	const latestAction = opportunities
		.filter((item) => item.existingAction)
		.sort((left, right) => (right.existingAction?.id ?? 0) - (left.existingAction?.id ?? 0))[0];
	return latestAction?.id ?? opportunities[0]?.id ?? "";
}

export function ActionStage({ index, label, state, children }: { index: number; label: string; state: "done" | "active" | "idle"; children?: ReactNode }) {
	return <li className={`pa-stage is-${state}`}><span>{state === "done" ? <Icon name="check" /> : index}</span><div><header><b>{label}</b><small>{state === "done" ? "已完成" : state === "active" ? "进行中" : "待处理"}</small></header>{children}</div></li>;
}

export const agentStageLabels: Record<string, string> = {
	queued: "等待本机 worker", preparing_context: "整理真实证据", researching_platform: "查阅平台规则",
	researching_brand: "核对品牌事实", adapting_platforms: "生成平台差异稿", awaiting_review: "等待人工审核",
	resuming: "正在恢复原任务", running: "正在执行", cancelling: "正在中止", cancelled: "已中止",
	timed_out: "运行超时", failed: "运行失败",
};

export const platformOptions = [
	{ key: "official_site", label: "春秋元泉官网", logo: "/brand/spring-yuan-workspace.svg" },
	{ key: "zhihu", label: "知乎", logo: "/brand/zhihu.svg" },
	{ key: "juejin", label: "掘金", logo: "/brand/platforms/juejin.png" },
	{ key: "csdn", label: "CSDN", logo: "/brand/platforms/csdn.ico" },
	{ key: "51cto", label: "51CTO", logo: "/brand/platforms/51cto.png" },
	{ key: "wechat", label: "公众号", logo: "/brand/wechat.svg" },
	{ key: "bilibili", label: "哔哩哔哩", logo: "/brand/platforms/bilibili.ico" },
	{ key: "baijiahao", label: "百家号", logo: "/brand/platforms/baijiahao.ico" },
	{ key: "weibo", label: "微博", logo: "/brand/platforms/weibo.ico" },
	{ key: "yuque", label: "语雀", logo: "/brand/platforms/yuque.png" },
	{ key: "douban", label: "豆瓣", logo: "/brand/platforms/douban.ico" },
	{ key: "sohu", label: "搜狐号", logo: "/brand/platforms/sohu.ico" },
	{ key: "xueqiu", label: "雪球", logo: "/brand/platforms/xueqiu.ico" },
	{ key: "cnblogs", label: "博客园", logo: "/brand/platforms/cnblogs.ico" },
	{ key: "oschina", label: "开源中国", logo: "/brand/platforms/oschina.ico" },
	{ key: "segmentfault", label: "思否", logo: "/brand/platforms/segmentfault.png" },
	{ key: "imooc", label: "慕课手记", logo: "/brand/platforms/imooc.ico" },
	{ key: "woshipm", label: "人人都是产品经理", logo: "/brand/platforms/woshipm.ico" },
	{ key: "eastmoney", label: "东方财富", logo: "/brand/platforms/eastmoney.ico" },
] as const;

export const syncablePlatformKeys = new Set<string>(platformOptions.filter((platform) => platform.key !== "official_site").map((platform) => platform.key));
export const platformDisplayName = (key: string) => platformOptions.find((platform) => platform.key === key)?.label || key;

export function runtimeVersionLabel(value?: string | null) {
	if (!value) return "Codex 运行时已检测";
	const desktopVersion = value.match(/Codex Desktop\/([^\s;]+)/i)?.[1];
	if (desktopVersion) return `Codex Desktop ${desktopVersion}`;
	const cliVersion = value.match(/codex(?:-cli)?\s+([^\s;]+)/i)?.[1];
	return cliVersion ? `Codex CLI ${cliVersion}` : "Codex 运行时已检测";
}

export function formatAgentDuration(totalSeconds: number) {
	const seconds = Math.max(0, Math.floor(totalSeconds));
	const minutes = Math.floor(seconds / 60);
	const remainder = seconds % 60;
	return minutes ? `${minutes} 分 ${remainder} 秒` : `${remainder} 秒`;
}

export function formatArtifactSize(size: number) {
	if (size < 1024) return `${size} B`;
	if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
	return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function agentArtifactLabel(kind: string) {
	if (kind === "official_page_screenshot") return "官网截图";
	if (kind === "invalid_page_screenshot") return "无效截图（未使用）";
	if (kind === "structured_result") return "结构化结果";
	return "Agent 工件";
}

export const formatEventTime = (value: string) => value.replace("T", " ").slice(11, 19);
export function formatReviewTime(value?: string | null) {
	if (!value) return "时间待回读";
	return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function groupAgentEvents(events: CleanroomAgentEvent[]) {
	return events.reduce<Array<{ key: number; stage: string; message: string; count: number; firstAt: string; lastAt: string }>>((groups, event) => {
		const previous = groups.at(-1);
		if (previous && previous.stage === event.stage && previous.message === event.message) {
			previous.count += 1;
			previous.lastAt = event.created_at;
			return groups;
		}
		groups.push({ key: event.id, stage: event.stage, message: event.message, count: 1, firstAt: event.created_at, lastAt: event.created_at });
		return groups;
	}, []);
}

export const agentProgressStateLabels = {
	waiting: "等待", running: "进行中", done: "已完成", waiting_human: "待你审核", failed: "未完成",
} as const;
