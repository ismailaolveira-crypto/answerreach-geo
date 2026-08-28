import { getCleanroomContentLibrary } from "@/lib/cleanroom-v1-api";
import { ContentLibrary } from "./content-library";
import { getContentLibrarySummary } from "./content-library-state";
import styles from "./content-library.module.css";
import { GeoGlobalScopeBar } from "@/components/geo-global-scope-bar";

export default async function ContentLibraryPage({ params }: { params: Promise<{ workspaceId: string }> }) {
	const { workspaceId } = await params;
	const items = await getCleanroomContentLibrary(workspaceId);
	const summary = getContentLibrarySummary(items);

	return <main className={styles.page}>
		<header className={styles.hero}>
			<div><p>内容资产</p><h1>内容库</h1><span>每次 Agent 生成、人工退回和平台适配都保留版本；只显示已持久化的真实状态。</span></div>
			<div className={styles.summary} aria-label="内容库摘要">
				<div><small>全部版本</small><strong>{summary.versionCount}</strong></div>
				<div><small>待人工审核</small><strong>{summary.awaitingReviewCount}</strong></div>
				<div><small>需重新生成</small><strong>{summary.staleDraftCount}</strong></div>
				<div><small>已回读草稿</small><strong>{summary.savedDraftCount}</strong></div>
				<div><small>公网已核验</small><strong>{summary.verifiedPublicationCount}</strong></div>
			</div>
		</header>
		<GeoGlobalScopeBar workspaceId={workspaceId} support="context" />
		<ContentLibrary workspaceId={workspaceId} items={items} />
	</main>;
}
