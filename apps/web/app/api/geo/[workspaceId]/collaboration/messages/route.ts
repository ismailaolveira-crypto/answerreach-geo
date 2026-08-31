import { forwardInternalResponse, internalApiFetch } from "@/lib/server-api";

export async function POST(
	request: Request,
	{ params }: { params: Promise<{ workspaceId: string }> },
) {
	const { workspaceId } = await params;
	const response = await internalApiFetch(
		`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration/messages`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: await request.text(),
		},
	);
	return forwardInternalResponse(response);
}
