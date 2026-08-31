import { NextResponse } from "next/server";
import { internalApiFetch } from "@/lib/server-api";

async function proxy(
	method: "GET" | "DELETE",
	params: Promise<{ workspaceId: string; attachmentId: string }>,
) {
	const { workspaceId, attachmentId } = await params;
	const response = await internalApiFetch(
		`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration/attachments/${encodeURIComponent(attachmentId)}`,
		{ method },
	);
	if (method === "DELETE") return new NextResponse(null, { status: response.status });
	return new NextResponse(response.body, {
		status: response.status,
		headers: {
			"Content-Type": response.headers.get("content-type") ?? "application/octet-stream",
			"Content-Disposition": response.headers.get("content-disposition") ?? "inline",
			"Cache-Control": "private, max-age=3600",
		},
	});
}

export async function GET(_request: Request, { params }: { params: Promise<{ workspaceId: string; attachmentId: string }> }) {
	return proxy("GET", params);
}

export async function DELETE(_request: Request, { params }: { params: Promise<{ workspaceId: string; attachmentId: string }> }) {
	return proxy("DELETE", params);
}
