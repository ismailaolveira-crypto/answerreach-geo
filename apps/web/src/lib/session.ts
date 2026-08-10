import { cookies } from "next/headers";
import { cache } from "react";
import { getMe } from "@/lib/api";
import { SESSION_COOKIE } from "@/lib/session-security";

export { SESSION_COOKIE };

export async function getSessionToken() {
  const cookieStore = await cookies();
  return cookieStore.get(SESSION_COOKIE)?.value ?? null;
}

export const getCurrentUser = cache(async function getCurrentUser() {
  const token = await getSessionToken();
  if (!token) return null;
  // Let transport and service errors reach the app error boundary. Converting
  // every failure to `null` makes a temporary API outage look like an expired
  // login and causes the middleware to delete an otherwise valid session.
  return getMe(token);
});
