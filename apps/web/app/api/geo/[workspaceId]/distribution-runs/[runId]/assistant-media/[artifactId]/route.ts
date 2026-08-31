import { NextResponse } from "next/server";
import { internalApiUrl } from "@/lib/api-config";

export async function GET(
	request: Request,
	{ params }: { params: Promise<{ workspaceId: string; runId: string; artifactId: string }> },
) {
	const { workspaceId, runId, artifactId } = await params;
	const taskToken = new URL(request.url).searchParams.get("task_token");
	if (!taskToken || taskToken.length < 20 || taskToken.length > 200) {
		return NextResponse.json({ detail: "Article assistant task credential is invalid" }, { status: 403 });
	}
	const upstream = new URL(
		internalApiUrl(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/distribution-runs/${encodeURIComponent(runId)}/assistant-media/${encodeURIComponent(artifactId)}`),
	);
	upstream.searchParams.set("task_token", taskToken);
	const response = await fetch(upstream, { cache: "no-store" });
	if (!response.ok || !response.body) {
		const detail = await response.text().catch(() => "Article media unavailable");
		return NextResponse.json({ detail }, { status: response.status });
	}
	return new NextResponse(response.body, {
		status: 200,
		headers: {
			"Content-Type": response.headers.get("content-type") ?? "image/png",
			"Cache-Control": "private, no-store",
			...(response.headers.get("etag") ? { ETag: response.headers.get("etag")! } : {}),
		},
	});
}
