import { NextResponse, type NextRequest } from "next/server";
import { requestPublicUrl } from "@/lib/request-url";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/session-security";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  if (process.env.GEO_DEMO_AUTO_LOGIN !== "true") {
    return NextResponse.json({ detail: "Auto login is disabled" }, { status: 403 });
  }
  const email = process.env.GEO_DEMO_EMAIL ?? "geo-demo-e2e@example.com";
  const password = process.env.GEO_DEMO_PASSWORD ?? "geo-demo-123";
  let login: Response;
  try {
    login = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.redirect(requestPublicUrl(request, "/login?error=unavailable"), 303);
  }
  if (!login.ok) {
    return NextResponse.redirect(requestPublicUrl(request, "/login?error=invalid"), 303);
  }
  const payload = (await login.json()) as { access_token: string };
  const response = NextResponse.redirect(requestPublicUrl(request, "/"), 303);
  response.cookies.set(SESSION_COOKIE, payload.access_token, sessionCookieOptions());
  return response;
}
