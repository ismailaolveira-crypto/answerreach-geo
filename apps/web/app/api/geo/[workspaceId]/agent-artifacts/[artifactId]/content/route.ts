import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function GET(
	_request: Request,
	{ params }: { params: Promise<{ workspaceId: string; artifactId: string }> },
) {
	const { workspaceId, artifactId } = await params;
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	const response = await fetch(
		`${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-artifacts/${encodeURIComponent(artifactId)}/content`,
		{
			cache: "no-store",
			headers: token ? { Authorization: `Bearer ${token}` } : {},
		},
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
