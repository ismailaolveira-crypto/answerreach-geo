"use server";

import {
	configureGeoCollaborationChannel,
	getGeoCollaborationCenter,
	markGeoCollaborationThreadRead,
	updateGeoCollaborationWorkInfo,
	testGeoCollaborationChannel,
	type GeoCollaborationChannel,
} from "@/lib/cleanroom-v1-api";

export async function loadCollaborationCenter(
	workspaceId: number,
	contextType: "action" | "alert" | "question" | "evidence",
	contextId: number,
) {
	return getGeoCollaborationCenter(workspaceId, {
		context_type: contextType,
		context_id: contextId,
	});
}

export async function saveCollaborationWorkInfo(
	workspaceId: number,
	contextType: "action" | "alert" | "question" | "evidence",
	contextId: number,
	payload: {
		assignee_user_id: number | null;
		start_at: string | null;
		due_at: string | null;
		participant_user_ids: number[];
	},
) {
	return updateGeoCollaborationWorkInfo(workspaceId, contextType, contextId, payload);
}

export async function markCollaborationRead(workspaceId: number, threadId: number) {
	return markGeoCollaborationThreadRead(workspaceId, threadId);
}

export async function saveCollaborationChannel(
	workspaceId: number,
	provider: GeoCollaborationChannel["provider"],
	webhookUrl: string,
	displayName: string,
) {
	await configureGeoCollaborationChannel(workspaceId, provider, {
		webhook_url: webhookUrl,
		display_name: displayName || null,
	});
	return getGeoCollaborationCenter(workspaceId);
}

export async function verifyCollaborationChannel(
	workspaceId: number,
	provider: GeoCollaborationChannel["provider"],
) {
	await testGeoCollaborationChannel(workspaceId, provider);
	return getGeoCollaborationCenter(workspaceId);
}
