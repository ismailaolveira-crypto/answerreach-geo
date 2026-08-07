import { cookies } from "next/headers";
import { cache } from "react";
import { getMe } from "@/lib/api";

export const SESSION_COOKIE = "geo_session";

export async function getSessionToken() {
  const cookieStore = await cookies();
  return cookieStore.get(SESSION_COOKIE)?.value ?? null;
}

export const getCurrentUser = cache(async function getCurrentUser() {
  const token = await getSessionToken();
  if (!token) return null;
  return getMe(token).catch(() => null);
});
