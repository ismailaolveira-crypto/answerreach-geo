import { NextResponse, type NextRequest } from "next/server";
import { requestPublicUrl } from "@/lib/request-url";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function POST(request: NextRequest) {
  const form = await request.formData();
  const payload = Object.fromEntries([
    "name", "email", "company_name", "brand_name", "website_url", "password",
  ].map((key) => [key, String(form.get(key) ?? "").trim()]));
  let registration: Response;
  try {
    registration = await fetch(`${API_BASE_URL}/api/auth/register-tenant`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return NextResponse.redirect(requestPublicUrl(request, "/register?error=unavailable"), 303);
  }
  if (!registration.ok) {
    const error = registration.status === 409 ? "exists" : "invalid";
    return NextResponse.redirect(requestPublicUrl(request, `/register?error=${error}`), 303);
  }
  const result = await registration.json() as { access_token: string };
  const response = NextResponse.redirect(requestPublicUrl(request, "/"), 303);
  response.cookies.set(SESSION_COOKIE, result.access_token, {
    httpOnly: true, sameSite: "lax", secure: process.env.SESSION_COOKIE_SECURE === "true",
    path: "/", maxAge: 60 * 60 * 24 * 7,
  });
  return response;
}
