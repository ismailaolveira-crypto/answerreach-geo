import { InteractionFeedback } from "@/app/(app)/interaction-feedback";
import { GeoFloatingSidebar } from "@/components/geo-floating-sidebar";
import { GeoShareLauncher } from "@/components/geo-share-launcher";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/session";
import { getCleanroomWorkspaces } from "@/lib/cleanroom-v1-api";

export default async function AppLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Middleware can only see that a cookie exists. Validate it before any protected
  // Server Component reaches the GEO API so an expired local session is recoverable.
  // Both reads use the same request cookie and are independent. Running them in
  // parallel removes one serial API round-trip from every protected navigation.
  const [user, workspaces] = await Promise.all([
    getCurrentUser(),
    getCleanroomWorkspaces().catch(() => []),
  ]);
  if (!user) redirect("/login?expired=1");
  return (
    <div className="cq-app-shell">
      <InteractionFeedback />
      <GeoFloatingSidebar workspaces={workspaces.map(({ id, brand_name }) => ({ id, name: brand_name }))} />
      <GeoShareLauncher />
      <div className="cq-app-main">{children}</div>
    </div>
  );
}
