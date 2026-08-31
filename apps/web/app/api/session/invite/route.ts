import { NextResponse, type NextRequest } from "next/server";
import { requestPublicUrl } from "@/lib/request-url";
import { isTrustedFormOrigin, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session-security";
import { internalApiUrl } from "@/lib/api-config";
export async function POST(request: NextRequest) {
	if (!isTrustedFormOrigin(request)) {
		return NextResponse.json({ detail: "Untrusted form origin" }, { status: 403 });
	}
	const form = await request.formData();
	const token = String(form.get("token") ?? "");
	const payload = {
		token,
		name: String(form.get("name") ?? "").trim(),
		password: String(form.get("password") ?? ""),
	};
	let accepted: Response;
	try {
		accepted = await fetch(internalApiUrl("/api/auth/invitations/accept"), {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
			cache: "no-store",
		});
	} catch {
		return NextResponse.redirect(requestPublicUrl(request, `/invite/${encodeURIComponent(token)}?error=unavailable`), 303);
	}
	if (!accepted.ok) {
		return NextResponse.redirect(requestPublicUrl(request, `/invite/${encodeURIComponent(token)}?error=invalid`), 303);
	}
	const result = await accepted.json() as { access_token: string; workspace_id: number };
	const response = NextResponse.redirect(requestPublicUrl(request, `/geo/${result.workspace_id}`), 303);
	response.cookies.set(SESSION_COOKIE, result.access_token, sessionCookieOptions());
	return response;
}
