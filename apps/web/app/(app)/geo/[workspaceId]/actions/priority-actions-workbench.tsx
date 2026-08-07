"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
import { BrandLogo } from "@/components/brand-logo";
import type { CleanroomAction } from "@/lib/cleanroom-v1-api";
import type { PriorityActionOpportunity } from "./priority-action-opportunities";

type Props = {
	workspaceId: string;
	opportunities: PriorityActionOpportunity[];
	actions: CleanroomAction[];
	createAction: (formData: FormData) => Promise<void>;
	updateActionStatus: (formData: FormData) => Promise<void>;
	discoverActions: () => Promise<void>;
};

type SyncAccount = {
	type: string;
	title: string;
	displayName?: string;
	status?: "pending" | "uploading" | "done" | "failed";
	msg?: string;
	error?: string;
	editResp?: { draftLink?: string } | null;
};

type ArticleSyncPageApi = {
	getAccounts: (callback: (first: unknown, second?: unknown) => void) => void;
	addTask: (
		task: { post: { title: string; content: string; markdown: string }; accounts: SyncAccount[] },
		statusHandler: (task: { accounts?: SyncAccount[] }) => void,
		callback: (first?: unknown, second?: unknown) => void,
	) => void;
};

function escapeHtml(value: string) {
	return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[character] ?? character);
}

function getArticleSyncApi() {
	return (window as Window & { $syncer?: ArticleSyncPageApi }).$syncer;
}

function discoverSyncAccounts(api: ArticleSyncPageApi) {
	return new Promise<SyncAccount[]>((resolve, reject) => {
		const timeout = window.setTimeout(() => reject(new Error("平台登录检查超时，请打开文章同步助手确认登录状态。")), 180_000);
		api.getAccounts((first, second) => {
			window.clearTimeout(timeout);
			const value = Array.isArray(second) ? second : Array.isArray(first) ? first : [];
			resolve(value as SyncAccount[]);
		});
	});
}

const priorityLabel = { high: "高优先级", medium: "中优先级", low: "持续观察" } as const;
const typeLabel = { visibility: "候选缺口", citation: "引用缺口", competitor: "竞品领先" } as const;

function suggestedSources(type: PriorityActionOpportunity["type"]) {
	if (type === "citation") return ["关键指标释义", "应用场景说明", "行业解决方案"];
	if (type === "competitor") return ["客户证言", "权威媒体报道", "第三方评测"];
	return ["企业选型对比", "私有化部署说明", "真实客户案例"];
}

function suggestedCarrier(type: PriorityActionOpportunity["type"]) {
	if (type === "citation") return "官网解决方案页 + 技术文章";
	if (type === "competitor") return "深度回答 + 媒体稿件";
	return "官网专题页 + 深度回答";
}

function modelBrand(label: string) {
	const value = label.toLowerCase();
	if (value.includes("deepseek")) return "deepseek";
	if (value.includes("doubao") || value.includes("豆包")) return "doubao";
	if (value.includes("qwen") || value.includes("千问")) return "qwen";
	if (value.includes("glm") || value.includes("智谱")) return "glm";
	if (value.includes("kimi") || value.includes("moonshot")) return "kimi";
	if (value.includes("hunyuan") || value.includes("混元")) return "hunyuan";
	return null;
}

function ModelBadge({ label }: { label: string }) {
	const brand = modelBrand(label);
	return <span className="pa-model-badge">{brand ? <BrandLogo brand={brand} label={label} className="pa-model-logo" /> : <i>AI</i>}<b>{label}</b></span>;
}

function Icon({ name }: { name: "warning" | "trend" | "draft" | "check" | "chevron" | "arrow" | "quote" | "spark" | "calendar" | "filter" | "eye" }) {
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

function actionStage(action?: CleanroomAction) {
	if (!action) return 0;
	if (["verified", "closed"].includes(action.status)) return 4;
	if (action.status === "in_progress") return 2;
	return 1;
}

function ActionStage({ index, label, state, children }: { index: number; label: string; state: "done" | "active" | "idle"; children?: React.ReactNode }) {
	return <li className={`pa-stage is-${state}`}>
		<span>{state === "done" ? <Icon name="check" /> : index}</span>
		<div><header><b>{label}</b><small>{state === "done" ? "已完成" : state === "active" ? "进行中" : "待处理"}</small></header>{children}</div>
	</li>;
}

export function PriorityActionsWorkbench({ workspaceId, opportunities, actions, createAction, updateActionStatus, discoverActions }: Props) {
	const [selectedId, setSelectedId] = useState(opportunities.find((item) => item.existingAction)?.id ?? opportunities[0]?.id ?? "");
	const [selectedModel, setSelectedModel] = useState("all");
	const [selectedQuestion, setSelectedQuestion] = useState("all");
	const [isTimelineCollapsed, setIsTimelineCollapsed] = useState(false);
	const [previewMessage, setPreviewMessage] = useState("");
	const [syncOpen, setSyncOpen] = useState(false);
	const [syncPhase, setSyncPhase] = useState<"idle" | "discovering" | "confirm" | "syncing" | "complete" | "error">("idle");
	const [syncAccounts, setSyncAccounts] = useState<SyncAccount[]>([]);
	const [selectedSyncAccounts, setSelectedSyncAccounts] = useState<string[]>([]);
	const [syncMessage, setSyncMessage] = useState("");
	const [isSaving, startSaving] = useTransition();

	const models = useMemo(() => [...new Set(opportunities.flatMap((item) => item.modelLabels))], [opportunities]);
	const questions = useMemo(() => [...new Map(opportunities.map((item) => [item.questionId, item.questionText])).entries()], [opportunities]);
	const filtered = useMemo(() => opportunities.filter((item) => (selectedModel === "all" || item.modelLabels.includes(selectedModel)) && (selectedQuestion === "all" || String(item.questionId) === selectedQuestion)), [opportunities, selectedModel, selectedQuestion]);
	useEffect(() => { if (!filtered.some((item) => item.id === selectedId)) setSelectedId(filtered[0]?.id ?? ""); }, [filtered, selectedId]);
	const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
	const actionable = opportunities.filter((item) => !item.existingAction);
	const high = actionable.filter((item) => item.priority === "high").length;
	const pendingActions = actions.filter((item) => ["proposed", "in_progress"].includes(item.status)).length;
	const retestReady = actions.filter((item) => ["verified", "closed"].includes(item.status)).length;
	const stage = actionStage(selected?.existingAction);
	const syncAction = selected?.existingAction ?? actions[0];

	async function openSyncAssistant() {
		if (!syncAction) {
			setPreviewMessage("请先选择一个真实行动，准备好内容后再打开同步助手。");
			return;
		}
		setSyncOpen(true);
		setSyncPhase("discovering");
		setSyncMessage("正在通过文章同步助手检查已登录平台…");
		setSyncAccounts([]);
		setSelectedSyncAccounts([]);
		const api = getArticleSyncApi();
		if (!api) {
			setSyncPhase("error");
			setSyncMessage("当前网页没有检测到文章同步助手。请在 EgoLite 中启用扩展并刷新本页。");
			return;
		}
		try {
			const accounts = await discoverSyncAccounts(api);
			const platformAccounts = accounts.filter((account) => account.type !== "zip-download");
			setSyncAccounts(platformAccounts);
			if (!platformAccounts.length) {
				setSyncPhase("error");
				setSyncMessage("没有检测到已登录平台。请先在 EgoLite 中登录目标平台，再重新打开同步助手。");
				return;
			}
			setSyncPhase("confirm");
			setSyncMessage(platformAccounts.length === 1
				? "当前只检测到 1 个已登录平台；如需双平台，请先在 EgoLite 中登录另一个平台。"
				: `已检测到 ${platformAccounts.length} 个登录平台。选择目标后由你确认，系统不会自动发布。`);
		} catch (error) {
			setSyncPhase("error");
			setSyncMessage(error instanceof Error ? error.message : "文章同步助手连接失败。");
		}
	}

	function confirmSync() {
		const api = getArticleSyncApi();
		const accounts = syncAccounts.filter((account) => selectedSyncAccounts.includes(account.type));
		if (!api || !syncAction || accounts.length === 0) return;
		const content = `<h1>${escapeHtml(syncAction.title)}</h1><p>${escapeHtml(syncAction.rationale)}</p>${syncAction.hypothesis ? `<h2>验证目标</h2><p>${escapeHtml(syncAction.hypothesis)}</p>` : ""}<p><strong>说明：</strong>此内容由春秋元泉 GEO 工作台交给文章同步助手，仅写入平台草稿，不执行发布。</p>`;
		const markdown = `# ${syncAction.title}\n\n${syncAction.rationale}${syncAction.hypothesis ? `\n\n## 验证目标\n\n${syncAction.hypothesis}` : ""}\n\n**说明：** 此内容由春秋元泉 GEO 工作台交给文章同步助手，仅写入平台草稿，不执行发布。`;
		setSyncPhase("syncing");
		setSyncMessage("同步请求已提交，正在等待各平台返回草稿结果…");
		api.addTask(
			{ post: { title: syncAction.title, content, markdown }, accounts },
			(task) => {
				if (!task.accounts?.length) return;
				setSyncAccounts(task.accounts);
				const finished = task.accounts.every((account) => account.status === "done" || account.status === "failed");
				if (finished) {
					setSyncPhase("complete");
					const saved = task.accounts.filter((account) => account.status === "done" && account.editResp?.draftLink).length;
					setSyncMessage(saved > 0 ? `${saved} 个平台返回了可回读的草稿链接；其余结果请逐项核对。` : "平台未返回可回读草稿；不会计为已保存。请查看下方失败原因。");
				}
			},
			() => undefined,
		);
	}

	return <main className="pa-page">
		<section className="pa-topline">
			<header className="pa-hero">
				<div><h1>优先行动</h1><span>从真实观测缺口出发，补齐信源、生成内容、写入草稿，并在下一轮验证变化。</span>
					<form action={discoverActions} className="pa-discover-form"><button type="submit">从真实观测刷新机会</button></form>
					<div className="pa-filters" aria-label="筛选行动机会">
						<label><Icon name="calendar" /><select defaultValue="current" disabled><option value="current">当前批次证据</option></select><Icon name="chevron" /></label>
						<label><Icon name="filter" /><select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)}><option value="all">全部模型</option>{models.map((model) => <option key={model} value={model}>{model}</option>)}</select><Icon name="chevron" /></label>
						<label><Icon name="spark" /><select value={selectedQuestion} onChange={(event) => setSelectedQuestion(event.target.value)}><option value="all">全部问题</option>{questions.map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select><Icon name="chevron" /></label>
					</div>
				</div>
			</header>

			<section className="pa-summary" aria-label="行动状态摘要">
				<article><span className="pa-summary-icon is-warning"><Icon name="warning" /></span><div><small>待处理缺口</small><strong>{actionable.length}</strong></div></article>
				<article><span className="pa-summary-icon is-trend"><Icon name="trend" /></span><div><small>高优先级</small><strong>{high}</strong></div></article>
				<article><span className="pa-summary-icon is-draft"><Icon name="draft" /></span><div><small>草稿待确认</small><strong>{pendingActions}</strong></div></article>
				<article><span className="pa-summary-icon is-check"><Icon name="check" /></span><div><small>已完成待复测</small><strong>{retestReady}</strong></div></article>
			</section>
		</section>

		{opportunities.length === 0 ? <section className="pa-empty"><span><Icon name="spark" /></span><h2>还没有足够的真实证据</h2><p>完成一次联网观测并归档回答与来源后，系统才会从真实结果中识别行动机会。</p><Link href={`/geo/${workspaceId}`}>发起真实观测 <Icon name="arrow" /></Link></section> : <>
			<section className="pa-workspace">
				<div className="pa-opportunity-panel">
					<header><div><h2>系统发现的优先机会</h2><p>仅使用已归档回答生成，不补造证据。</p></div><small>{filtered.length} 个机会</small></header>
					<div className="pa-opportunity-list">
						{filtered.map((item) => <article key={item.id} className={selected?.id === item.id ? "is-selected" : ""}>
							<div className="pa-opportunity-main"><span className={`pa-priority ${item.priority}`}>{priorityLabel[item.priority]}</span><h3>{item.title}</h3><p>{item.summary}</p><div className="pa-models">{item.modelLabels.slice(0, 4).map((label) => <ModelBadge key={label} label={label} />)}</div></div>
							<div className="pa-gap"><small>缺失信源</small><div className="pa-source-tags">{suggestedSources(item.type).map((source) => <span key={source}>{source}</span>)}</div><em>建议载体 · {suggestedCarrier(item.type)}</em></div>
							<div className="pa-opportunity-actions"><span className="pa-evidence-ok"><Icon name="check" />证据充分</span><button type="button" onClick={() => setSelectedId(item.id)}>{item.existingAction ? "查看行动" : "选择并开始"}</button><Link href={`/geo/${workspaceId}/evidence/${item.evidenceIds[0]}`}>查看 {item.evidenceIds.length} 条证据 <Icon name="arrow" /></Link></div>
						</article>)}
					</div>
				</div>

				<aside className={`pa-current-action ${isTimelineCollapsed ? "is-collapsed" : ""}`}>
					<header><h2>本次行动</h2><button type="button" onClick={() => setIsTimelineCollapsed((value) => !value)}>{isTimelineCollapsed ? "展开" : "收起"} <Icon name="chevron" /></button></header>
					{!isTimelineCollapsed && selected ? <ol>
						<ActionStage index={1} label="选择信源" state={stage >= 1 ? "done" : "active"}>{stage === 0 ? <div className="pa-stage-card"><b>目标载体</b><p>{selected.recommendedAsset}</p><form action={(formData) => startSaving(() => createAction(formData))}><input type="hidden" name="title" value={`${selected.title}：${selected.questionText}`} /><input type="hidden" name="rationale" value={selected.summary} /><input type="hidden" name="hypothesis" value={`下一轮相同问题中，期待“${selected.recommendedAsset}”补齐后，春秋元泉进入候选或获得引用。`} /><input type="hidden" name="priority" value={selected.priority} /><input type="hidden" name="question_plan_id" value={selected.questionId} /><input type="hidden" name="source_evidence_id" value={selected.evidenceIds[0]} />{selected.backendId ? <input type="hidden" name="opportunity_id" value={selected.backendId} /> : null}<button disabled={isSaving} type="submit">{isSaving ? "正在保存行动…" : "选择这个行动"}</button></form></div> : <p className="pa-stage-note">已关联当前问题的真实证据与行动记录。</p>}</ActionStage>
						<ActionStage index={2} label="生成内容" state={stage === 2 ? "active" : stage > 2 ? "done" : "idle"}>{stage === 1 && selected.existingAction ? <form className="pa-stage-card" action={(formData) => startSaving(() => updateActionStatus(formData))}><b>关联证据</b><p>批次：当前归档　问题：{selected.questionText}<br />模型：{selected.modelLabels.slice(0, 3).join("、")}</p><input type="hidden" name="action_id" value={selected.existingAction.id} /><button disabled={isSaving} type="submit"><Icon name="spark" />{isSaving ? "正在准备…" : "生成真实内容"}</button></form> : stage >= 2 ? <p className="pa-stage-note">行动已开始；内容资产接入后会在这里显示草稿。</p> : null}</ActionStage>
						<ActionStage index={3} label="人工审核" state="idle"><p className="pa-stage-note">内容审核将在已接入内容资产台账后开放。</p></ActionStage>
						<ActionStage index={4} label="写入平台草稿" state="idle"><p className="pa-stage-note">只允许写入草稿，最终发布仍由人工确认。</p></ActionStage>
						<ActionStage index={5} label="下轮复测" state={stage >= 4 ? "active" : "idle"}>{stage >= 4 ? <p className="pa-stage-note">请使用相同问题与模型集合创建复测批次。</p> : null}</ActionStage>
					</ol> : !isTimelineCollapsed ? <p className="pa-empty-copy">调整筛选条件后，选择一个机会开始。</p> : null}
				</aside>
			</section>

			{actions.length > 0 ? <section className="pa-progress">
				<header><div><h2>内容与发布进度</h2><p>只显示数据库已保存的行动；内容、草稿与发布将在对应接口接入后逐格推进。</p></div></header>
				<div className="pa-progress-lanes"><div className="is-current"><b>内容草稿</b><span>{actions.filter((item) => item.status === "proposed").length}</span>{actions.filter((item) => item.status === "proposed").slice(0, 1).map((item) => <p key={item.id}>{item.title}</p>)}</div><div><b>事实校验</b><span>0</span><p>暂无待核验内容</p></div><div><b>平台适配</b><span>0</span><p>暂无待适配内容</p></div><div><b>写入草稿</b><span>{actions.filter((item) => item.status === "in_progress").length}</span>{actions.filter((item) => item.status === "in_progress").slice(0, 1).map((item) => <p key={item.id}>{item.title}</p>)}</div><div><b>人工发布</b><span>0</span><p>始终由人工确认</p></div><div><b>等待复测</b><span>{actions.filter((item) => ["verified", "closed"].includes(item.status)).length}</span><p>完成后回到同题复测</p></div></div>
				<footer className="pa-progress-footer"><span><Icon name="eye" />系统只写入草稿，最终发布由人工确认</span><div><button type="button" onClick={() => setPreviewMessage("当前同步内容来自已保存的行动记录；正式平台适配稿仍需在内容生成阶段补齐。")}>预览说明</button><button className="pa-sync-button" type="button" onClick={openSyncAssistant}>打开同步助手 <Icon name="arrow" /></button></div></footer>
				{previewMessage ? <p className="pa-front-notice" role="status">{previewMessage}</p> : null}
			</section> : null}
		{syncOpen ? <div className="pa-sync-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && syncPhase !== "syncing") setSyncOpen(false); }}>
			<section className="pa-sync-dialog" role="dialog" aria-modal="true" aria-labelledby="sync-assistant-title">
				<header><div><small>文章同步助手</small><h2 id="sync-assistant-title">选择平台并确认写入</h2></div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"} aria-label="关闭同步助手">×</button></header>
				<div className="pa-sync-summary"><b>{syncAction?.title}</b><p>当前使用已保存的行动内容进行接入；每个平台默认只保存草稿。</p></div>
				<p className={`pa-sync-message is-${syncPhase}`} role="status">{syncMessage}</p>
				{syncAccounts.length ? <div className="pa-sync-platforms">{syncAccounts.map((account) => {
					const disabled = syncPhase !== "confirm";
					const checked = selectedSyncAccounts.includes(account.type);
					return <label key={account.type} className={checked ? "is-selected" : ""}><input type="checkbox" checked={checked} disabled={disabled} onChange={() => setSelectedSyncAccounts((current) => current.includes(account.type) ? current.filter((value) => value !== account.type) : [...current, account.type])} /><span><b>{account.displayName || account.title}</b><small>{account.status === "done" ? "草稿已返回" : account.status === "failed" ? (account.error || "写入失败") : account.msg || account.title}</small></span>{account.editResp?.draftLink ? <a href={account.editResp.draftLink} target="_blank" rel="noreferrer">打开草稿</a> : null}</label>;
				})}</div> : null}
				<footer><span>确认只会触发草稿写入，不会点击平台发布。</span><div><button type="button" onClick={() => setSyncOpen(false)} disabled={syncPhase === "syncing"}>取消</button>{syncPhase === "confirm" ? <button className="is-primary" type="button" onClick={confirmSync} disabled={!selectedSyncAccounts.length}>确认写入 {selectedSyncAccounts.length} 个平台</button> : null}{syncPhase === "error" ? <button className="is-primary" type="button" onClick={openSyncAssistant}>重新检测</button> : null}</div></footer>
			</section>
		</div> : null}
		</>}
	</main>;
}
