import { getSessionToken } from "@/lib/session";
import { internalApiUrl } from "@/lib/api-config";

export async function GET(
	_request: Request,
	context: { params: Promise<{ workspaceId: string; batchId: string }> },
) {
	const [{ workspaceId, batchId }, token] = await Promise.all([context.params, getSessionToken()]);
	if (!token) return new Response("未登录", { status: 401 });
	if (!/^\d+$/.test(batchId)) return new Response("无效批次", { status: 400 });
	const response = await fetch(
		internalApiUrl(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/business-metric-imports/${batchId}/errors.csv`),
		{ cache: "no-store", headers: { Authorization: `Bearer ${token}` } },
	);
	if (!response.ok) return new Response("错误清单下载失败", { status: response.status });
	return new Response(await response.arrayBuffer(), {
		status: 200,
		headers: {
			"Content-Type": response.headers.get("content-type") ?? "text/csv; charset=utf-8",
			"Content-Disposition": `attachment; filename=geo-roi-import-${batchId}-errors.csv`,
			"Cache-Control": "no-store",
		},
	});
}
