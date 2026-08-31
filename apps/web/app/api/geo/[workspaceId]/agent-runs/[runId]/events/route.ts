import { NextRequest, NextResponse } from "next/server";
import { internalApiFetch } from "@/lib/server-api";

export async function GET(
	request: NextRequest,
	{ params }: { params: Promise<{ workspaceId: string; runId: string }> },
) {
	const { workspaceId, runId } = await params;
	const after = request.nextUrl.searchParams.get("after") ?? "0";
	const response = await internalApiFetch(
		`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-runs/${encodeURIComponent(runId)}/events/stream?after=${encodeURIComponent(after)}`,
		{
			headers: { Accept: "text/event-stream" },
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
