import { NextRequest, NextResponse } from "next/server";
import { internalApiFetch } from "@/lib/server-api";

async function forwardJson(response: Response) {
  const body = await response.json().catch(() => ({ detail: "分析服务返回了无效响应。" }));
  return NextResponse.json(body, { status: response.status });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await params;
  const incoming = request.nextUrl.searchParams;
  const query = new URLSearchParams();
  for (const key of ["period_days", "model_key", "question_plan_id", "evidence_limit"]) {
    const value = incoming.get(key);
    if (value) query.set(key, value);
  }
  const response = await internalApiFetch(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/competitor-insights?${query}`,
    {
      method: "GET",
    },
  );
  return forwardJson(response);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await params;
  const payload = await request.json().catch(() => null);
  if (!payload || typeof payload !== "object") {
    return NextResponse.json({ detail: "请求参数不正确。" }, { status: 400 });
  }
  const response = await internalApiFetch(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/competitor-insights`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return forwardJson(response);
}
