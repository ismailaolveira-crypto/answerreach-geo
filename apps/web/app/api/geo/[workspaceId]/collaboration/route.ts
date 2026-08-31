import { forwardInternalResponse, internalApiFetch } from "@/lib/server-api";

export async function GET(
	request: Request,
	{ params }: { params: Promise<{ workspaceId: string }> },
) {
	const { workspaceId } = await params;
	const source = new URL(request.url);
	const query = new URLSearchParams();
	for (const key of ["context_type", "context_id"]) {
		const value = source.searchParams.get(key);
		if (value) query.set(key, value);
	}
	const response = await internalApiFetch(
		`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/collaboration${query.size ? `?${query}` : ""}`,
	);
	return forwardInternalResponse(response);
}
