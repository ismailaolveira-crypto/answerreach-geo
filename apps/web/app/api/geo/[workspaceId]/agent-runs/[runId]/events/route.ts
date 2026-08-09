import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function GET(
	request: NextRequest,
	{ params }: { params: Promise<{ workspaceId: string; runId: string }> },
) {
	const { workspaceId, runId } = await params;
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	const after = request.nextUrl.searchParams.get("after") ?? "0";
	const response = await fetch(
		`${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-runs/${encodeURIComponent(runId)}/events/stream?after=${encodeURIComponent(after)}`,
		{
			cache: "no-store",
			headers: {
				Accept: "text/event-stream",
				...(token ? { Authorization: `Bearer ${token}` } : {}),
			},
		},
	);
	if (!response.ok || !response.body) {
		const detail = await response.text().catch(() => "Agent event stream unavailable");
		return NextResponse.json({ detail }, { status: response.status });
	}
	return new NextResponse(response.body, {
		status: 200,
		headers: {
			"Content-Type": "text/event-stream; charset=utf-8",
			"Cache-Control": "no-cache, no-transform",
			Connection: "keep-alive",
		},
	});
}
