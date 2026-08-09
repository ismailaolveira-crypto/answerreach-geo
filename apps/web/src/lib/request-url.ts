import type { NextRequest } from "next/server";

export function requestPublicUrl(request: NextRequest, path: string): URL {
  const forwardedHost = request.headers.get("x-forwarded-host");
  const host = forwardedHost ?? request.headers.get("host");
  const protocol = request.headers.get("x-forwarded-proto") ?? new URL(request.url).protocol.replace(":", "");
  if (host) return new URL(path, `${protocol}://${host}`);
  return new URL(path, request.url);
}
