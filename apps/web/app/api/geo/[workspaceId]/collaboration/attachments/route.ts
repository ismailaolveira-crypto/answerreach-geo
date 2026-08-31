import { forwardInternalResponse, internalApiFetch } from "@/lib/server-api";

export async function POST(
	request: Request,
	{ params }: { params: Promise<{ workspaceId: string }> },
) {
	const { workspaceId } = await params;
	const headers = new Headers({
		"Content-Type": request.headers.get("content-type") ?? "application/octet-stream",
		"X-File-Name": request.headers.get("x-file-name") ?? "file",
	});
	const size = request.headers.get("x-file-size");
	if (size) headers.set("X-File-Size", size);
	const response = await internalApiFetch(
		`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration/attachments`,
		{ method: "POST", headers, body: request.body, duplex: "half" } as RequestInit & { duplex: "half" },
	);
	return forwardInternalResponse(response);
}
