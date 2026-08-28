import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

async function proxy(
	method: "GET" | "DELETE",
	params: Promise<{ workspaceId: string; attachmentId: string }>,
) {
	const { workspaceId, attachmentId } = await params;
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	if (!token) return NextResponse.json({ detail: "登录已过期" }, { status: 401 });
	const response = await fetch(
		`${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration/attachments/${encodeURIComponent(attachmentId)}`,
		{ method, cache: "no-store", headers: { Authorization: `Bearer ${token}` } },
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
