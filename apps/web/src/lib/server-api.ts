import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/lib/session-security";
import { internalApiUrl } from "@/lib/api-config";

export async function internalApiFetch(path: string, init: RequestInit = {}) {
	const token = (await cookies()).get(SESSION_COOKIE)?.value;
	if (!token) {
		return Response.json({ detail: "登录已过期" }, { status: 401 });
	}
	return fetch(internalApiUrl(path), {
		...init,
		cache: "no-store",
		headers: {
			Authorization: `Bearer ${token}`,
			...(init.headers ?? {}),
		},
	});
}

export function forwardInternalResponse(
	response: Response,
	fallbackContentType = "application/json",
) {
	return new Response(response.body, {
		status: response.status,
		headers: {
			"Content-Type": response.headers.get("content-type") ?? fallbackContentType,
			"Cache-Control": "no-store",
		},
	});
}

export async function internalApiJson<T>(path: string, init: RequestInit = {}) {
	const response = await internalApiFetch(path, {
		...init,
		headers: {
			"Content-Type": "application/json",
			...(init.headers ?? {}),
		},
	});
	if (!response.ok) {
		const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
		const detail = typeof body?.detail === "string" ? body.detail : `GEO API ${response.status}`;
		throw new Error(detail);
	}
	if (response.status === 204) return undefined as T;
	return response.json() as Promise<T>;
}
