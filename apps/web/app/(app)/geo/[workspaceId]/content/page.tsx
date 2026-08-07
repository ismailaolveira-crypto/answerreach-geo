import { getCleanroomContentLibrary } from "@/lib/cleanroom-v1-api";
import { ContentLibrary } from "./content-library";
import styles from "./content-library.module.css";

export default async function ContentLibraryPage({ params }: { params: Promise<{ workspaceId: string }> }) {
	const { workspaceId } = await params;
	const items = await getCleanroomContentLibrary(workspaceId);
	const awaitingReview = items.filter((item) => item.asset.status === "draft").length;
	const needsRevision = items.filter((item) => item.latest_review_verdict === "changes_requested" && item.asset.status !== "superseded").length;
	const readyForSync = items.filter((item) => item.approved_platform_keys.length > 0 && item.saved_draft_count === 0).length;
	const savedDrafts = items.reduce((total, item) => total + item.saved_draft_count, 0);

	return <main className={styles.page}>
		<header className={styles.hero}>
			<div><p>内容资产</p><h1>内容库</h1><span>每次 Agent 生成、人工退回和平台适配都保留版本；只显示已持久化的真实状态。</span></div>
			<div className={styles.summary} aria-label="内容库摘要">
				<div><small>全部版本</small><strong>{items.length}</strong></div>
				<div><small>待人工审核</small><strong>{awaitingReview}</strong></div>
				<div><small>待修订 / 待同步</small><strong>{needsRevision + readyForSync}</strong></div>
				<div><small>已回读草稿</small><strong>{savedDrafts}</strong></div>
			</div>
		</header>
		<ContentLibrary workspaceId={workspaceId} items={items} />
	</main>;
}
