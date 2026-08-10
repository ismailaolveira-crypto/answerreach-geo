import type { NextRequest } from "next/server";

export const SESSION_COOKIE = "geo_session";
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24;

function isExplicitLocalHttpMode(): boolean {
  return process.env.GEO_LOCAL_HTTP?.trim().toLowerCase() === "true";
}

export function sessionCookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure:
      !isExplicitLocalHttpMode() &&
      (process.env.NODE_ENV === "production" ||
        process.env.SESSION_COOKIE_SECURE === "true"),
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  };
}

export function isTrustedFormOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    const originUrl = new URL(origin);
    if (originUrl.origin === request.nextUrl.origin) return true;

    // Behind the bundled Nginx gateway Next.js may see the container origin
    // (web:3000), while the browser and Host header use the public local port.
    // Compare against that public request authority without accepting an
    // arbitrary X-Forwarded-Host supplied by the client.
    const host = request.headers.get("host");
    const forwardedProtocol = request.headers
      .get("x-forwarded-proto")
      ?.split(",", 1)[0]
      ?.trim()
      ?.toLowerCase();
    const protocol = forwardedProtocol ?? request.nextUrl.protocol.replace(":", "");
    if (!host || (protocol !== "http" && protocol !== "https")) return false;
    return originUrl.origin === new URL(`${protocol}://${host}`).origin;
  } catch {
    return false;
  }
}
