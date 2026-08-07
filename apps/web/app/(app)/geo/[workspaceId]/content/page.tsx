import { getCleanroomContentLibrary } from "@/lib/cleanroom-v1-api";
import { ContentLibrary } from "./content-library";
import styles from "./content-library.module.css";

export default async function ContentLibraryPage({ params }: { params: Promise<{ workspaceId: string }> }) {
	const { workspaceId } = await params;
	const items = await getCleanroomContentLibrary(workspaceId);
	const awaitingReview = items.filter((item) => item.asset.status === "draft").length;
	const savedDrafts = items.reduce((total, item) => total + item.saved_draft_count, 0);
	const publishedArticles = items.reduce((total, item) => total + item.draft_targets.filter((target) => target.human_publish_status === "published" && target.public_url).length, 0);

	return <main className={styles.page}>
		<header className={styles.hero}>
			<div><p>内容资产</p><h1>内容库</h1><span>每次 Agent 生成、人工退回和平台适配都保留版本；只显示已持久化的真实状态。</span></div>
			<div className={styles.summary} aria-label="内容库摘要">
				<div><small>全部版本</small><strong>{items.length}</strong></div>
				<div><small>待人工审核</small><strong>{awaitingReview}</strong></div>
				<div><small>已回读草稿</small><strong>{savedDrafts}</strong></div>
				<div><small>人工已发布</small><strong>{publishedArticles}</strong></div>
			</div>
		</header>
		<ContentLibrary workspaceId={workspaceId} items={items} />
	</main>;
}
