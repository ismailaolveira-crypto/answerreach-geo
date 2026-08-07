import { InteractionFeedback } from "@/app/(app)/interaction-feedback";
import { GeoFloatingSidebar } from "@/components/geo-floating-sidebar";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/session";

export default async function AppLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Middleware can only see that a cookie exists. Validate it before any protected
  // Server Component reaches the GEO API so an expired local session is recoverable.
  const user = await getCurrentUser();
  if (!user) redirect("/login?expired=1");
  return (
    <div className="cq-app-shell">
      <InteractionFeedback />
      <GeoFloatingSidebar />
      <div className="cq-app-main">{children}</div>
    </div>
  );
}
