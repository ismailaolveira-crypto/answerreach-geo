import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function POST(
	request: Request,
	{ params }: { params: Promise<{ workspaceId: string }> },
) {
	const { workspaceId } = await params;
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	if (!token) return NextResponse.json({ detail: "登录已过期" }, { status: 401 });
	const headers = new Headers({
		Authorization: `Bearer ${token}`,
		"Content-Type": request.headers.get("content-type") ?? "application/octet-stream",
		"X-File-Name": request.headers.get("x-file-name") ?? "file",
	});
	const size = request.headers.get("x-file-size");
	if (size) headers.set("X-File-Size", size);
	const response = await fetch(
		`${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration/attachments`,
		{ method: "POST", headers, body: request.body, duplex: "half" } as RequestInit & { duplex: "half" },
	);
	return new NextResponse(response.body, {
		status: response.status,
		headers: { "Content-Type": response.headers.get("content-type") ?? "application/json" },
	});
}
