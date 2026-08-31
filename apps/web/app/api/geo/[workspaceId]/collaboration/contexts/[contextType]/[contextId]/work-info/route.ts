import { forwardInternalResponse, internalApiFetch } from "@/lib/server-api";

export async function PATCH(
	request: Request,
	{ params }: { params: Promise<{ workspaceId: string; contextType: string; contextId: string }> },
) {
	const { workspaceId, contextType, contextId } = await params;
	const response = await internalApiFetch(
		`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration/contexts/${encodeURIComponent(contextType)}/${encodeURIComponent(contextId)}/work-info`,
		{
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: await request.text(),
		},
	);
	return forwardInternalResponse(response);
}
