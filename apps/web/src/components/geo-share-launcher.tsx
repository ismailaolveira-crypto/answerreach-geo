"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useSearchParams } from "next/navigation";

import styles from "./geo-share-launcher.module.css";

const moduleKeys: Array<[RegExp, string]> = [
	[/\/insights\/decision(?:\/|$)/, "decision"],
	[/\/sources(?:\/|$)/, "source"],
	[/\/competitors(?:\/|$)/, "competitor"],
	[/\/questions(?:\/|$)/, "question"],
	[/\/actions(?:\/|$)/, "actions"],
	[/\/content(?:\/|$)/, "content"],
	[/\/results(?:\/|$)/, "results"],
	[/\/operations(?:\/|$)/, "operations"],
	[/\/alerts(?:\/|$)/, "alerts"],
	[/\/settings(?:\/|$)/, "settings"],
];

export function GeoShareLauncher() {
	const pathname = usePathname();
	const search = useSearchParams();
	const match = pathname.match(/^\/geo\/(\d+)(?:\/|$)/);
	if (!match || pathname.includes("/collaboration")) return null;
	const workspaceId = match[1];
	const actionId = pathname.includes("/actions") ? Number(search.get("action_id")) : 0;
	const params = new URLSearchParams();
	if (Number.isInteger(actionId) && actionId > 0) {
		params.set("context", "action");
		params.set("id", String(actionId));
		params.set("share_kind", "action");
		params.set("object_id", String(actionId));
	} else {
		const moduleKey = moduleKeys.find(([pattern]) => pattern.test(pathname))?.[1]
			?? (pathname === `/geo/${workspaceId}` ? "decision" : null);
		if (!moduleKey) return null;
		params.set("share_kind", "module");
		params.set("module", moduleKey);
	}
	return <Link
		className={styles.button}
		href={`/geo/${workspaceId}/collaboration?${params}` as Route}
		aria-label="转到协作"
		title="转到协作"
	>
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
			<path d="M7 12h10" /><path d="m13 8 4 4-4 4" /><path d="M19 5v14H5V5h8" />
		</svg>
	</Link>;
}
