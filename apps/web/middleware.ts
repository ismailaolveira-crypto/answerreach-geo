import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/session-security";

function secure(response: NextResponse): NextResponse {
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  response.headers.set("Cross-Origin-Opener-Policy", "same-origin");
  if (
    process.env.NODE_ENV === "production" &&
    process.env.GEO_LOCAL_HTTP?.trim().toLowerCase() !== "true"
  ) {
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=31536000; includeSubDomains"
    );
  }
  return response;
}

export function middleware(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const { pathname } = request.nextUrl;
  const isApi = pathname.startsWith("/api/");
  const isLogin = pathname === "/login";
  const isRegister = pathname === "/register";
  const isInvite = pathname.startsWith("/invite/");
  const isPublicAuth = isLogin || isRegister || isInvite;
  const isPublicShare = pathname.startsWith("/share/");
  const isPublicAsset =
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".");

  if (isApi) {
    return secure(NextResponse.next());
  }

  if (isPublicAsset || isPublicShare) {
    return secure(NextResponse.next());
  }

  if (!token && !isPublicAuth) {
    return secure(NextResponse.redirect(new URL("/login", request.url)));
  }

  if (token && isLogin && request.nextUrl.searchParams.get("expired") === "1") {
    const response = NextResponse.next();
    response.cookies.delete(SESSION_COOKIE);
    return secure(response);
  }

  if (token && isLogin) {
    return secure(NextResponse.redirect(new URL("/", request.url)));
  }

  if (token && isRegister) {
    return secure(NextResponse.redirect(new URL("/", request.url)));
  }

  return secure(NextResponse.next());
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]
};
