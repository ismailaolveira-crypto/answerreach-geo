"use server";

import {
	bindGeoCollaborationMember,
	configureGeoCollaborationChannel,
	getGeoCollaborationCenter,
	markGeoCollaborationThreadRead,
	previewGeoCollaborationNotification,
	sendGeoCollaborationNotification,
	updateGeoCollaborationWorkInfo,
	testGeoCollaborationChannel,
	updateGeoCollaborationNotificationPreferences,
	type GeoCollaborationChannel,
	type GeoCollaborationEventType,
	type GeoCollaborationItem,
	type GeoCollaborationProvider,
} from "@/lib/cleanroom-v1-api";

export type CollaborationActionResult<T> =
	| { ok: true; data: T }
	| { ok: false; error: string };

function actionError(value: unknown, fallback: string): string {
	if (!(value instanceof Error) || !value.message) return fallback;
	return value.message.startsWith("Clean-room GEO API 5") ? fallback : value.message;
}

async function runAction<T>(work: () => Promise<T>, fallback: string): Promise<CollaborationActionResult<T>> {
	try {
		return { ok: true, data: await work() };
	} catch (value) {
		return { ok: false, error: actionError(value, fallback) };
	}
}

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
	payload: {
		connection_mode: "webhook" | "app";
		webhook_url?: string | null;
		corp_id?: string | null;
		app_id?: string | null;
		app_key?: string | null;
		agent_id?: string | null;
		app_secret?: string | null;
		display_name?: string | null;
		deep_link_base_url?: string | null;
	},
) {
	return runAction(async () => {
		await configureGeoCollaborationChannel(workspaceId, provider, payload);
		return getGeoCollaborationCenter(workspaceId);
	}, "保存失败，请检查连接信息后重试");
}

export async function bindCollaborationMember(
	workspaceId: number,
	memberId: number,
	provider: GeoCollaborationProvider,
	externalUserId: string,
	externalIdType: "user_id" | "open_id" | "union_id",
) {
	return runAction(async () => {
		await bindGeoCollaborationMember(workspaceId, memberId, provider, {
			external_user_id: externalUserId,
			external_id_type: externalIdType,
		});
		return getGeoCollaborationCenter(workspaceId);
	}, "官方通讯录未确认该成员");
}

export async function saveCollaborationNotificationPreferences(
	workspaceId: number,
	memberId: number,
	providerSettings: Partial<Record<GeoCollaborationProvider, boolean>>,
	eventTypes: GeoCollaborationEventType[],
) {
	return runAction(async () => {
		await updateGeoCollaborationNotificationPreferences(workspaceId, memberId, {
			provider_settings: providerSettings,
			event_types: eventTypes,
		});
		return getGeoCollaborationCenter(workspaceId);
	}, "通知偏好保存失败");
}

type NotificationDraft = {
	recipient_user_id: number;
	context_type: GeoCollaborationItem["context_type"];
	context_id: number;
	event_type: GeoCollaborationEventType;
	providers: GeoCollaborationProvider[];
	note?: string;
};

export async function previewCollaborationNotification(
	workspaceId: number,
	payload: NotificationDraft,
) {
	return runAction(
		() => previewGeoCollaborationNotification(workspaceId, payload),
		"无法生成通知预览",
	);
}

export async function sendCollaborationNotification(
	workspaceId: number,
	payload: NotificationDraft & { idempotency_key: string },
) {
	return runAction(async () => {
		await sendGeoCollaborationNotification(workspaceId, payload);
		return getGeoCollaborationCenter(workspaceId);
	}, "发送失败，未确认写入外部平台");
}

export async function verifyCollaborationChannel(
	workspaceId: number,
	provider: GeoCollaborationChannel["provider"],
) {
	return runAction(async () => {
		await testGeoCollaborationChannel(workspaceId, provider);
		return getGeoCollaborationCenter(workspaceId);
	}, "官方平台未确认连接");
}
