import { NextResponse, type NextRequest } from "next/server";
import { timingSafeEqual } from "node:crypto";
import { requestPublicUrl } from "@/lib/request-url";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/session-security";
import { internalApiUrl } from "@/lib/api-config";

export async function GET(request: NextRequest) {
  const email = process.env.GEO_DEMO_EMAIL?.trim();
  const password = process.env.GEO_DEMO_PASSWORD;
  const accessKey = process.env.GEO_DEMO_AUTO_LOGIN_ACCESS_KEY;
  const suppliedKey = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  const enabled =
    process.env.NODE_ENV !== "production" &&
    process.env.GEO_DEMO_AUTO_LOGIN === "true" &&
    Boolean(email && password && accessKey && suppliedKey);
  if (!enabled) {
    return NextResponse.json({ detail: "Auto login is disabled" }, { status: 403 });
  }
  const expected = Buffer.from(accessKey!);
  const supplied = Buffer.from(suppliedKey!);
  if (expected.length !== supplied.length || !timingSafeEqual(expected, supplied)) {
    return NextResponse.json({ detail: "Auto login is disabled" }, { status: 403 });
  }
  let login: Response;
  try {
    login = await fetch(internalApiUrl("/api/auth/login"), {
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
