import { NextResponse, type NextRequest } from "next/server";
import { requestPublicUrl } from "@/lib/request-url";
import { isTrustedFormOrigin, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session-security";
import { internalApiClientHeaders } from "@/lib/internal-api-security";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export async function POST(request: NextRequest) {
  if (!isTrustedFormOrigin(request)) {
    return NextResponse.json({ detail: "Untrusted form origin" }, { status: 403 });
  }
  const form = await request.formData();
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  let login: Response;
  try {
    login = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...internalApiClientHeaders(request) },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.redirect(requestPublicUrl(request, "/login?error=unavailable"), 303);
  }
  if (!login.ok) {
    const error = login.status === 429 ? "throttled" : login.status >= 500 ? "unavailable" : "invalid";
    return NextResponse.redirect(requestPublicUrl(request, `/login?error=${error}`), 303);
  }
  const payload = await login.json() as { access_token: string };
  const response = NextResponse.redirect(requestPublicUrl(request, "/"), 303);
  response.cookies.set(SESSION_COOKIE, payload.access_token, sessionCookieOptions());
  return response;
}
