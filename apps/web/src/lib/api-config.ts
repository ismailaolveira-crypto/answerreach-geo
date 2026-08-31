const DEFAULT_API_BASE_URL = "http://localhost:8000";

export const INTERNAL_API_BASE_URL =
	process.env.INTERNAL_API_BASE_URL ??
	process.env.NEXT_PUBLIC_API_BASE_URL ??
	DEFAULT_API_BASE_URL;

export const API_BASE_URL =
	typeof window === "undefined"
		? INTERNAL_API_BASE_URL
		: process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export function internalApiUrl(path: string) {
	return `${INTERNAL_API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}
