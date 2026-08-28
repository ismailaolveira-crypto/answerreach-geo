import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function GET(
	request: Request,
	{ params }: { params: Promise<{ workspaceId: string }> },
) {
	const { workspaceId } = await params;
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	if (!token) return NextResponse.json({ detail: "登录已过期" }, { status: 401 });
	const source = new URL(request.url);
	const query = new URLSearchParams();
	for (const key of ["context_type", "context_id"]) {
		const value = source.searchParams.get(key);
		if (value) query.set(key, value);
	}
	const response = await fetch(
		`${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration${query.size ? `?${query}` : ""}`,
		{ cache: "no-store", headers: { Authorization: `Bearer ${token}` } },
	);
	return new NextResponse(response.body, {
		status: response.status,
		headers: { "Content-Type": response.headers.get("content-type") ?? "application/json" },
	});
}
