import { isIP } from "node:net";
import type { NextRequest } from "next/server";

export function internalApiClientHeaders(request: NextRequest): Record<string, string> {
  const secret = process.env.INTERNAL_PROXY_SECRET;
  if (!secret) return {};
  const direct = request.headers.get("x-real-ip")?.trim() ?? "";
  const forwarded = request.headers.get("x-forwarded-for")
    ?.split(",")
    .at(-1)
    ?.trim() ?? "";
  const clientIp = direct || forwarded;
  if (!isIP(clientIp)) return {};
  return {
    "X-Geo-Client-IP": clientIp,
    "X-Geo-Proxy-Secret": secret,
  };
}
