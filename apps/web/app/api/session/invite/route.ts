import { NextResponse, type NextRequest } from "next/server";
import { requestPublicUrl } from "@/lib/request-url";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "geo_session";

export async function POST(request: NextRequest) {
	const form = await request.formData();
	const token = String(form.get("token") ?? "");
	const payload = {
		token,
		name: String(form.get("name") ?? "").trim(),
		password: String(form.get("password") ?? ""),
	};
	const accepted = await fetch(`${API_BASE_URL}/api/auth/invitations/accept`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
		cache: "no-store",
	});
	if (!accepted.ok) {
		return NextResponse.redirect(requestPublicUrl(request, `/invite/${encodeURIComponent(token)}?error=invalid`), 303);
	}
	const result = await accepted.json() as { access_token: string; workspace_id: number };
	const response = NextResponse.redirect(requestPublicUrl(request, `/geo/${result.workspace_id}`), 303);
	response.cookies.set(SESSION_COOKIE, result.access_token, {
		httpOnly: true,
		sameSite: "lax",
		secure: process.env.SESSION_COOKIE_SECURE === "true",
		path: "/",
		maxAge: 60 * 60 * 24 * 7,
	});
	return response;
}
