import { NextResponse, type NextRequest } from "next/server";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function POST(request: NextRequest) {
  const form = await request.formData();
  const payload = Object.fromEntries([
    "name", "email", "company_name", "brand_name", "website_url", "password",
  ].map((key) => [key, String(form.get(key) ?? "").trim()]));
  const registration = await fetch(`${API_BASE_URL}/api/auth/register-tenant`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!registration.ok) {
    const error = registration.status === 409 ? "exists" : "invalid";
    return NextResponse.redirect(new URL(`/register?error=${error}`, request.url), 303);
  }
  const result = await registration.json() as { access_token: string };
  const response = NextResponse.redirect(new URL("/", request.url), 303);
  response.cookies.set(SESSION_COOKIE, result.access_token, {
    httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production",
    path: "/", maxAge: 60 * 60 * 24 * 7,
  });
  return response;
}
