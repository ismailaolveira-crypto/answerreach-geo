import { notFound } from "next/navigation";

import { getGeoCollaborationCenter, type GeoCollaborationShareDraft } from "@/lib/cleanroom-v1-api";
import { CollaborationCenter } from "./collaboration-center";

type PageProps = {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<{ context?: string; id?: string; share_kind?: string; object_id?: string; module?: string }>;
};

export default async function CollaborationPage({ params, searchParams }: PageProps) {
	const [{ workspaceId }, query] = await Promise.all([params, searchParams]);
	const numericWorkspaceId = Number(workspaceId);
	if (!Number.isInteger(numericWorkspaceId) || numericWorkspaceId < 1) notFound();
	const contextType: "action" | "alert" | "question" | "evidence" | null = query.context === "alert"
		? "alert"
		: query.context === "action"
			? "action"
			: query.context === "question"
				? "question"
				: query.context === "evidence"
					? "evidence"
					: null;
	const contextId = Number(query.id);
	const selection = contextType && Number.isInteger(contextId) && contextId > 0
		? { context_type: contextType, context_id: contextId }
		: null;
	const data = await getGeoCollaborationCenter(numericWorkspaceId, selection);
	const shareKind = query.share_kind;
	const objectId = Number(query.object_id);
	const initialShare: GeoCollaborationShareDraft | null = shareKind === "module" && query.module
		? { kind: "module", module_key: query.module }
		: (["action", "alert", "question", "content_asset", "evidence"].includes(shareKind || "") && Number.isInteger(objectId) && objectId > 0
			? { kind: shareKind as Exclude<GeoCollaborationShareDraft["kind"], "module">, object_id: objectId }
			: null);
	return <CollaborationCenter workspaceId={numericWorkspaceId} initialData={data} initialShare={initialShare} />;
}
