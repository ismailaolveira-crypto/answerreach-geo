import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { scopeOnlySearchParams } from "@/lib/geo-global-scope";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function GET(
	request: NextRequest,
	{ params }: { params: Promise<{ workspaceId: string }> },
) {
	const { workspaceId } = await params;
	if (!/^\d+$/.test(workspaceId)) return NextResponse.json({ detail: "Invalid workspace" }, { status: 400 });
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	const query = scopeOnlySearchParams(request.nextUrl.searchParams);
	const response = await fetch(
		`${API_BASE_URL}/api/v1/workspaces/${workspaceId}/global-scope-options?${query.toString()}`,
		{
			cache: "no-store",
			headers: token ? { Authorization: `Bearer ${token}` } : {},
		},
	);
	const body = await response.json().catch(() => ({ detail: "范围选项暂时不可用" }));
	return NextResponse.json(body, { status: response.status, headers: { "Cache-Control": "no-store" } });
}
