import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getCleanroomWorkspaces } from "@/lib/cleanroom-v1-api";
import { WorkspaceSettingsForm } from "./workspace-settings-form";
import { IntegrationSettingsForm } from "./integration-settings-form";
import { BrandFactsSettingsForm } from "./brand-facts-settings-form";
import { readAgentRuntime, readBrandFacts, readWorkspaceIntegrations } from "./actions";
import styles from "./settings.module.css";

async function IntegrationSettingsSection({ workspaceId }: { workspaceId: number }) {
	const [integrations, agentRuntime] = await Promise.all([
		readWorkspaceIntegrations(workspaceId),
		readAgentRuntime(workspaceId),
	]);
	return <IntegrationSettingsForm workspaceId={workspaceId} initialSettings={integrations} initialRuntime={agentRuntime} />;
}

function IntegrationSettingsLoading() {
	return <section className={`${styles.integrationCard} ${styles.integrationLoading}`} aria-live="polite" aria-busy="true">
		<header className={styles.integrationHeader}><div><span className={styles.integrationEyebrow}>05 · Agent 与草稿交付</span><h2>本机 Codex 与文章同步</h2><p>品牌与事实设置已可使用；本机执行状态正在独立检查。</p></div><span className={styles.integrationPending}>正在检查</span></header>
		<div className={styles.integrationLoadingGrid} aria-hidden="true"><i /><i /></div>
		<p>正在核对本机 Agent 与同步配置，不会读取或显示密钥。</p>
	</section>;
}

export default async function GeoSettingsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
	const { workspaceId } = await params;
	const numericWorkspaceId = Number(workspaceId);
	if (!Number.isInteger(numericWorkspaceId) || numericWorkspaceId < 1) notFound();
	const [workspaces, brandFacts] = await Promise.all([
		getCleanroomWorkspaces(),
		readBrandFacts(numericWorkspaceId),
	]);
	const workspace = workspaces.find((item) => item.id === numericWorkspaceId);
	if (!workspace) notFound();
	return <main className={styles.page}>
		<header className={styles.header}><div><p>工作区设置</p><h1>让每一次观测有一致的识别口径</h1><span>品牌名称、别名和官网只影响之后归档的识别，不会改写历史回答。</span></div><Link href={`/geo/${workspaceId}`}>返回决策地图</Link></header>
		<div className={styles.grid}>
			<section className={styles.card}><header><span>01</span><div><h2>品牌识别</h2><p>这是指标、竞品对比和问题分析共用的品牌口径。</p></div></header><WorkspaceSettingsForm workspace={workspace} /></section>
			<section className={styles.card}><header><span>02</span><div><h2>模型与渠道</h2><p>API 连接和联网验证在独立页面完成。</p></div></header><Link className={styles.cardLink} href="/admin/providers">管理模型与渠道 <b>→</b></Link></section>
			<section className={styles.card}><header><span>03</span><div><h2>真实运行</h2><p>查看采集任务、失败原因与证据归档。</p></div></header><div className={styles.linkStack}><Link href={`/geo/${workspaceId}/operations`}>运营状态 <b>→</b></Link><Link href={`/geo/${workspaceId}/questions`}>问题库 <b>→</b></Link></div></section>
		</div>
		<BrandFactsSettingsForm workspaceId={workspace.id} initialFacts={brandFacts} />
		<Suspense fallback={<IntegrationSettingsLoading />}><IntegrationSettingsSection workspaceId={workspace.id} /></Suspense>
	</main>;
}
