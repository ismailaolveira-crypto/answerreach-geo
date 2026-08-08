import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

async function forwardJson(response: Response) {
  const body = await response.json().catch(() => ({ detail: "分析服务返回了无效响应。" }));
  return NextResponse.json(body, { status: response.status });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await params;
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const incoming = request.nextUrl.searchParams;
  const query = new URLSearchParams();
  for (const key of ["period_days", "model_key", "question_plan_id", "evidence_limit"]) {
    const value = incoming.get(key);
    if (value) query.set(key, value);
  }
  const response = await fetch(
    `${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/competitor-insights?${query}`,
    {
      method: "GET",
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
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
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const response = await fetch(
    `${API_BASE_URL}/api/v1/workspaces/${encodeURIComponent(workspaceId)}/competitor-insights`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    },
  );
  return forwardJson(response);
}
