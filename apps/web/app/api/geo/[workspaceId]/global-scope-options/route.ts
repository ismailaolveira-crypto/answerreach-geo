import { NextRequest, NextResponse } from "next/server";
import { scopeOnlySearchParams } from "@/lib/geo-global-scope";
import { internalApiFetch } from "@/lib/server-api";

export async function GET(
	request: NextRequest,
	{ params }: { params: Promise<{ workspaceId: string }> },
) {
	const { workspaceId } = await params;
	if (!/^\d+$/.test(workspaceId)) return NextResponse.json({ detail: "Invalid workspace" }, { status: 400 });
	const query = scopeOnlySearchParams(request.nextUrl.searchParams);
	const response = await internalApiFetch(
		`/api/v1/workspaces/${workspaceId}/global-scope-options?${query.toString()}`,
	);
	const body = await response.json().catch(() => ({ detail: "范围选项暂时不可用" }));
	return NextResponse.json(body, { status: response.status, headers: { "Cache-Control": "no-store" } });
}
