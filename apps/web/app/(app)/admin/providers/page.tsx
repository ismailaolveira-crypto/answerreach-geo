import { getLLMProviderReadiness, getLLMProviders } from "@/lib/api";
import { PROVIDER_CATALOG, type ProviderCatalogKey } from "@/lib/provider-catalog";
import { getCurrentUser } from "@/lib/session";
import { redirect } from "next/navigation";
import ProviderSettingsClient from "./provider-settings-client";

type PageProps = { searchParams: Promise<{ model?: string; channel?: string }> };

export default async function ProvidersPage({ searchParams }: PageProps) {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin") redirect("/");
  const query = await searchParams;
  const selectedKey = (PROVIDER_CATALOG.some((item) => item.key === query.model) ? query.model : "deepseek") as ProviderCatalogKey;
  const [providers, readinessRows] = await Promise.all([
    getLLMProviders().catch(() => []),
    getLLMProviderReadiness().catch(() => []),
  ]);
  return <ProviderSettingsClient providers={providers} readinessRows={readinessRows} initialKey={selectedKey} />;
}
