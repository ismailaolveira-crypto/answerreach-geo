"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname } from "next/navigation";
import { useEffect, useState, type SVGProps } from "react";

type IconName = "home" | "sources" | "compare" | "questions" | "actions" | "operations" | "providers" | "settings" | "chevron";

const ITEMS: Array<{ key: string; label: string; icon: IconName; href: (id: string) => string }> = [
	{ key: "overview", label: "决策地图", icon: "home", href: (id) => `/geo/${id}` },
	{ key: "sources", label: "信源地图", icon: "sources", href: (id) => `/geo/${id}/sources` },
	{ key: "competitors", label: "竞品对比", icon: "compare", href: (id) => `/geo/${id}/competitors` },
	{ key: "questions", label: "问题库", icon: "questions", href: (id) => `/geo/${id}/questions` },
	{ key: "actions", label: "优化行动", icon: "actions", href: (id) => `/geo/${id}/actions` },
	{ key: "operations", label: "运营状态", icon: "operations", href: (id) => `/geo/${id}/operations` },
	{ key: "providers", label: "模型与渠道", icon: "providers", href: () => "/admin/providers" },
];

function activeKey(pathname: string) {
	if (pathname.includes("/sources")) return "sources";
	if (pathname.includes("/competitors")) return "competitors";
	if (pathname.includes("/questions")) return "questions";
	if (pathname.includes("/actions")) return "actions";
	if (pathname.includes("/operations")) return "operations";
	if (pathname.includes("/settings")) return "settings";
	if (pathname.startsWith("/admin/providers")) return "providers";
	return "overview";
}

function NavIcon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
	const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.85, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
	return <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
		{name === "home" && <><path {...common} d="m4 11.2 8-6.5 8 6.5v8.1a1.7 1.7 0 0 1-1.7 1.7H5.7A1.7 1.7 0 0 1 4 19.3z" /><path {...common} d="M9.2 21v-5.6h5.6V21" /></>}
		{name === "sources" && <><circle {...common} cx="12" cy="12" r="4.4" /><path {...common} d="M12 3.5v2M12 18.5v2M20.5 12h-2M5.5 12h-2M18 6l-1.4 1.4M7.4 16.6 6 18M18 18l-1.4-1.4M7.4 7.4 6 6" /></>}
		{name === "compare" && <><path {...common} d="M4 8h13.5M14.5 4l4 4-4 4M20 16H6.5M9.5 12l-4 4 4 4" /></>}
		{name === "questions" && <><path {...common} d="M9.2 9a2.9 2.9 0 1 1 4.9 2.1c-1.6 1.4-2.1 1.8-2.1 3.4" /><path {...common} d="M12 18.5h.01" /></>}
		{name === "actions" && <><path {...common} d="M6 18 18 6M10 6h8v8" /></>}
		{name === "operations" && <><path {...common} d="M5 12h3l2-5 4 10 2-5h3" /></>}
		{name === "providers" && <><path {...common} d="m12 3 8 8-8 8-8-8z" /><path {...common} d="m4 11 8 8 8-8" /></>}
		{name === "settings" && <><circle {...common} cx="12" cy="12" r="3" /><path {...common} d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56v.08h-3v-.08a1.7 1.7 0 0 0-1.03-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15a1.7 1.7 0 0 0-1.56-1.03h-.08v-3h.08A1.7 1.7 0 0 0 7.06 9.94 1.7 1.7 0 0 0 6.72 8l-.06-.06 2.1-2.1.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4.6h3v.08a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.94 1.7 1.7 0 0 0 1.56 1.03h.08v3h-.08A1.7 1.7 0 0 0 19.4 15z" /></>}
		{name === "chevron" && <path {...common} d="m9 18 6-6-6-6" />}
	</svg>;
}

export function GeoFloatingSidebar() {
	const pathname = usePathname();
	const [expanded, setExpanded] = useState(true);

	useEffect(() => {
		const saved = window.localStorage.getItem("cq-geo-sidebar-expanded");
		if (saved !== null) setExpanded(saved === "true");
		else if (window.innerWidth < 920) setExpanded(false);
	}, []);

	if (!pathname.startsWith("/geo/") && !pathname.startsWith("/admin/providers")) return null;
	const workspaceId = pathname.match(/^\/geo\/([^/]+)/)?.[1] ?? "1";
	const current = activeKey(pathname);
	const questionAnalysisActive = /^\/geo\/[^/]+\/questions\/(analysis|\d+)/.test(pathname);
	const setSidebarExpanded = (next: boolean) => {
		setExpanded(next);
		window.localStorage.setItem("cq-geo-sidebar-expanded", String(next));
	};

	return <aside className={`geo-floating-sidebar${expanded ? " is-expanded" : ""}`} aria-label="春秋元泉 GEO 功能导航">
		<div className="geo-floating-head">
			<Link className="geo-floating-brand" href={`/geo/${workspaceId}`} aria-label="返回决策地图">
				<span className="geo-floating-mark">◇</span><b>春秋元泉 GEO</b>
			</Link>
			<button type="button" className="geo-floating-toggle" onClick={() => setSidebarExpanded(!expanded)} aria-expanded={expanded} aria-label={expanded ? "收起功能栏" : "展开功能栏"}>
				<NavIcon name="chevron" />
			</button>
		</div>
		<nav className="geo-floating-nav">
			{ITEMS.map((item) => <div key={item.key} className="geo-floating-nav-group">
				<Link href={item.href(workspaceId) as Route} className={current === item.key ? "is-active" : ""} aria-current={current === item.key ? "page" : undefined} title={!expanded ? item.label : undefined}>
					<span className="geo-floating-icon"><NavIcon name={item.icon} /></span><span className="geo-floating-label">{item.label}</span>
				</Link>
				{item.key === "questions" ? <Link className={`geo-floating-subnav${questionAnalysisActive ? " is-active" : ""}`} href={`/geo/${workspaceId}/questions/analysis` as Route} aria-current={questionAnalysisActive ? "page" : undefined} title={!expanded ? "问题分析" : undefined}><span className="geo-floating-subnav-mark" /><span className="geo-floating-label">问题分析</span></Link> : null}
			</div>)}
		</nav>
		<nav className="geo-floating-bottom-nav" aria-label="辅助导航">
			<Link href={`/geo/${workspaceId}/settings` as Route} className={current === "settings" ? "is-active" : ""} aria-current={current === "settings" ? "page" : undefined} title={!expanded ? "设置" : undefined}>
				<span className="geo-floating-icon"><NavIcon name="settings" /></span><span className="geo-floating-label">设置</span>
			</Link>
			<Link className="geo-floating-foot" href={`/geo/${workspaceId}/operations`} title={!expanded ? "查看运行状态" : undefined}>
				<span className="geo-floating-status is-neutral" aria-hidden="true" /><span className="geo-floating-label">查看运行状态</span>
			</Link>
		</nav>
	</aside>;
}
