import { getLLMProviderReadiness, getLLMProviders } from "@/lib/api";
import { PROVIDER_CATALOG, type ProviderCatalogKey } from "@/lib/provider-catalog";
import { getCurrentUser } from "@/lib/session";
import { redirect } from "next/navigation";
import ProviderSettingsClient from "./provider-settings-client";

type PageProps = { searchParams: Promise<{ model?: string; channel?: string; workspace?: string }> };

export default async function ProvidersPage({ searchParams }: PageProps) {
  const user = await getCurrentUser();
  if (user?.role !== "super_admin") redirect("/");
  const query = await searchParams;
  const selectedKey = (PROVIDER_CATALOG.some((item) => item.key === query.model) ? query.model : "deepseek") as ProviderCatalogKey;
  const workspaceId = /^\d+$/.test(query.workspace ?? "") ? query.workspace : undefined;
  const [providersResult, readinessResult] = await Promise.allSettled([
    getLLMProviders(),
    getLLMProviderReadiness(),
  ]);
  const providers = providersResult.status === "fulfilled" ? providersResult.value : [];
  const readinessRows = readinessResult.status === "fulfilled" ? readinessResult.value : [];
  const loadError = providersResult.status === "rejected" || readinessResult.status === "rejected"
    ? "后端没有完整返回渠道配置与联网门禁。"
    : undefined;
  return <ProviderSettingsClient providers={providers} readinessRows={readinessRows} initialKey={selectedKey} workspaceId={workspaceId} loadError={loadError} />;
}
