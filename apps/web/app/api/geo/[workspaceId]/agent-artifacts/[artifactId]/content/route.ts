import { NextResponse } from "next/server";
import { internalApiFetch } from "@/lib/server-api";

export async function GET(
	_request: Request,
	{ params }: { params: Promise<{ workspaceId: string; artifactId: string }> },
) {
	const { workspaceId, artifactId } = await params;
	const response = await internalApiFetch(
		`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-artifacts/${encodeURIComponent(artifactId)}/content`,
	);
	if (!response.ok || !response.body) {
		const detail = await response.text().catch(() => "Visual artifact unavailable");
		return NextResponse.json({ detail }, { status: response.status });
	}
	return new NextResponse(response.body, {
		status: 200,
		headers: {
			"Content-Type": response.headers.get("content-type") ?? "image/png",
			"Cache-Control": "private, max-age=3600",
			...(response.headers.get("etag") ? { ETag: response.headers.get("etag")! } : {}),
		},
	});
}
