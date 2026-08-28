import { getSessionToken } from "@/lib/session";

const API_BASE_URL =
	process.env.INTERNAL_API_BASE_URL ??
	process.env.NEXT_PUBLIC_API_BASE_URL ??
	"http://localhost:8000";

export async function GET(
	_request: Request,
	context: { params: Promise<{ workspaceId: string }> },
) {
	const [{ workspaceId }, token] = await Promise.all([context.params, getSessionToken()]);
	if (!token) return new Response("未登录", { status: 401 });
	const response = await fetch(
		`${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/business-metric-imports/template.csv`,
		{ cache: "no-store", headers: { Authorization: `Bearer ${token}` } },
	);
	if (!response.ok) return new Response("模板下载失败", { status: response.status });
	return new Response(await response.arrayBuffer(), {
		status: 200,
		headers: {
			"Content-Type": response.headers.get("content-type") ?? "text/csv; charset=utf-8",
			"Content-Disposition": "attachment; filename=geo-roi-import-template.csv",
			"Cache-Control": "no-store",
		},
	});
}
