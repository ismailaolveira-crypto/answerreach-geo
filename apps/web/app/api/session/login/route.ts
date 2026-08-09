import { NextResponse, type NextRequest } from "next/server";
import { requestPublicUrl } from "@/lib/request-url";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function POST(request: NextRequest) {
  const form = await request.formData();
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
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
  if (!login.ok) return NextResponse.redirect(requestPublicUrl(request, "/login?error=invalid"), 303);
  const payload = await login.json() as { access_token: string };
  const response = NextResponse.redirect(requestPublicUrl(request, "/"), 303);
  response.cookies.set(SESSION_COOKIE, payload.access_token, {
    httpOnly: true, sameSite: "lax", secure: process.env.SESSION_COOKIE_SECURE === "true",
    path: "/", maxAge: 60 * 60 * 24 * 7,
  });
  return response;
}
