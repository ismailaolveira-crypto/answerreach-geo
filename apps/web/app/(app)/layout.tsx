import { InteractionFeedback } from "@/app/(app)/interaction-feedback";
import { GeoFloatingSidebar } from "@/components/geo-floating-sidebar";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/session";
import { getCleanroomWorkspaces } from "@/lib/cleanroom-v1-api";

export default async function AppLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Middleware can only see that a cookie exists. Validate it before any protected
  // Server Component reaches the GEO API so an expired local session is recoverable.
  const user = await getCurrentUser();
  if (!user) redirect("/login?expired=1");
  const workspaces = await getCleanroomWorkspaces().catch(() => []);
  return (
    <div className="cq-app-shell">
      <InteractionFeedback />
      <GeoFloatingSidebar workspaces={workspaces.map(({ id, brand_name }) => ({ id, name: brand_name }))} />
      <div className="cq-app-main">{children}</div>
    </div>
  );
}
