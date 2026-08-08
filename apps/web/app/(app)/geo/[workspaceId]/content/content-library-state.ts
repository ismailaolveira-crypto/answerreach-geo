import type { CleanroomContentLibraryItem } from "@/lib/cleanroom-v1-api";

export type ContentLibraryState =
	| "review"
	| "stale"
	| "revision"
	| "approved"
	| "awaiting_confirmation"
	| "draft_saved"
	| "website_handoff"
	| "published"
	| "superseded";

export function getContentLibraryItemState(item: CleanroomContentLibraryItem): ContentLibraryState {
	if (!item.is_latest_version || item.asset.status === "superseded") return "superseded";
	if (item.draft_targets.some((target) => (
		target.human_publish_status === "published"
		&& Boolean(target.public_url)
		&& target.publication_verification_status === "publicly_verified"
	))) return "published";
	if (item.draft_targets.some((target) => (
		target.platform_key === "official_site"
		&& target.adapter_version === "manual-website.v1"
		&& target.request_status === "handoff_ready"
	))) return "website_handoff";
	if (item.draft_targets.some((target) => (
		target.draft_readback_status === "awaiting_human_confirmation"
		&& Boolean(target.candidate_draft_url)
	))) return "awaiting_confirmation";
	if (item.saved_draft_count > 0) return "draft_saved";
	if (item.latest_review_verdict === "changes_requested") return "revision";
	if (item.brand_fact_snapshot_stale) return "stale";
	if (item.approved_platform_keys.length > 0) return "approved";
	return "review";
}

export function getContentLibrarySummary(items: CleanroomContentLibraryItem[]) {
	return {
		versionCount: items.length,
		awaitingReviewCount: items.filter((item) => getContentLibraryItemState(item) === "review").length,
		staleDraftCount: items.filter((item) => getContentLibraryItemState(item) === "stale").length,
		savedDraftCount: items.reduce((total, item) => total + item.saved_draft_count, 0),
		verifiedPublicationCount: items.reduce((total, item) => total + item.draft_targets.filter((target) => (
			target.human_publish_status === "published"
			&& Boolean(target.public_url)
			&& target.publication_verification_status === "publicly_verified"
		)).length, 0),
	};
}
