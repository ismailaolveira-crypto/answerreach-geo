import { NextResponse, type NextRequest } from "next/server";
import { requestPublicUrl } from "@/lib/request-url";
import { isTrustedFormOrigin, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session-security";
import { internalApiClientHeaders } from "@/lib/internal-api-security";
import { internalApiUrl } from "@/lib/api-config";
export async function POST(request: NextRequest) {
  if (!isTrustedFormOrigin(request)) {
    return NextResponse.json({ detail: "Untrusted form origin" }, { status: 403 });
  }
  const form = await request.formData();
  const payload = Object.fromEntries([
    "name", "email", "company_name", "brand_name", "website_url", "password",
  ].map((key) => [key, String(form.get(key) ?? "").trim()]));
  let registration: Response;
  try {
    registration = await fetch(internalApiUrl("/api/auth/register-tenant"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...internalApiClientHeaders(request) },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return NextResponse.redirect(requestPublicUrl(request, "/register?error=unavailable"), 303);
  }
  if (!registration.ok) {
    const error = registration.status === 409
      ? "exists"
      : registration.status === 429
        ? "throttled"
        : registration.status === 403
          ? "disabled"
          : registration.status >= 500
            ? "unavailable"
            : "invalid";
    return NextResponse.redirect(requestPublicUrl(request, `/register?error=${error}`), 303);
  }
  const result = await registration.json() as { access_token: string };
  const response = NextResponse.redirect(requestPublicUrl(request, "/"), 303);
  response.cookies.set(SESSION_COOKIE, result.access_token, sessionCookieOptions());
  return response;
}
