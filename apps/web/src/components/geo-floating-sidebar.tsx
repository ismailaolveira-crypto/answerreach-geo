"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type SVGProps } from "react";
import { preserveGeoScopeInHref } from "@/lib/geo-global-scope";

type IconName =
	| "agent"
	| "home"
	| "insights"
	| "sources"
	| "compare"
	| "questions"
	| "actions"
	| "collaboration"
	| "results"
	| "content"
	| "operations"
	| "providers"
	| "settings"
	| "chevron"
	| "close";

type SidebarLink = {
	key: string;
	label: string;
	icon?: IconName;
	href: (workspaceId: string) => string;
};

const INSIGHT_LINKS: SidebarLink[] = [
	{ key: "decision", label: "决策洞察", href: (id) => id ? `/geo/${id}/insights/decision` : "/" },
	{ key: "sources", label: "信源洞察", href: (id) => id ? `/geo/${id}/sources` : "/" },
	{ key: "competitors", label: "竞品洞察", href: (id) => id ? `/geo/${id}/competitors` : "/" },
	{ key: "questions", label: "问题洞察", href: (id) => id ? `/geo/${id}/questions` : "/" },
];

const PRIMARY_LINKS: SidebarLink[] = [
	{ key: "agent", label: "Agent 工作台", icon: "agent", href: (id) => id ? `/geo/${id}/agent` : "/" },
	{ key: "dashboard", label: "经营驾驶舱", icon: "home", href: (id) => id ? `/geo/${id}` : "/" },
	{ key: "actions", label: "优化行动", icon: "actions", href: (id) => id ? `/geo/${id}/actions` : "/" },
	{ key: "collaboration", label: "协作", icon: "collaboration", href: (id) => id ? `/geo/${id}/collaboration` : "/" },
	{ key: "content", label: "内容", icon: "content", href: (id) => id ? `/geo/${id}/content` : "/" },
	{ key: "results", label: "效果与 ROI", icon: "results", href: (id) => id ? `/geo/${id}/results` : "/" },
];

const MANAGEMENT_LINKS: SidebarLink[] = [
	{ key: "alerts", label: "观测与告警", href: (id) => id ? `/geo/${id}/alerts` : "/" },
	{ key: "operations", label: "运营状态", href: (id) => id ? `/geo/${id}/operations` : "/" },
	{ key: "providers", label: "模型与渠道", href: (id) => id ? `/admin/providers?workspace=${encodeURIComponent(id)}` : "/admin/providers" },
	{ key: "settings", label: "设置", href: (id) => id ? `/geo/${id}/settings` : "/" },
];

type ActiveNavigation = {
	section: "agent" | "dashboard" | "insights" | "actions" | "collaboration" | "content" | "results" | "management";
	child: string | null;
};

export function resolveGeoNavigation(pathname: string): ActiveNavigation {
	if (pathname.startsWith("/admin/providers")) return { section: "management", child: "providers" };
	if (pathname.includes("/alerts")) return { section: "management", child: "alerts" };
	if (pathname.includes("/operations")) return { section: "management", child: "operations" };
	if (pathname.includes("/settings")) return { section: "management", child: "settings" };
	if (pathname.includes("/insights/decision")) return { section: "insights", child: "decision" };
	if (pathname.includes("/sources")) return { section: "insights", child: "sources" };
	if (pathname.includes("/competitors")) return { section: "insights", child: "competitors" };
	if (pathname.includes("/questions")) return { section: "insights", child: "questions" };
	if (pathname.includes("/actions/agent") || /^\/geo\/[^/]+\/agent(?:\/|$)/.test(pathname)) return { section: "agent", child: null };
	if (pathname.includes("/actions")) return { section: "actions", child: null };
	if (pathname.includes("/collaboration")) return { section: "collaboration", child: null };
	if (pathname.includes("/content")) return { section: "content", child: null };
	if (pathname.includes("/results")) return { section: "results", child: null };
	return { section: "dashboard", child: null };
}

function NavIcon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
	const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.85, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
	return <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
		{name === "agent" && <><path {...common} d="M12 3.5c.7 4.1 2.4 5.8 6.5 6.5-4.1.7-5.8 2.4-6.5 6.5-.7-4.1-2.4-5.8-6.5-6.5 4.1-.7 5.8-2.4 6.5-6.5Z" /><path {...common} d="M18.2 15.8c.25 1.45.85 2.05 2.3 2.3-1.45.25-2.05.85-2.3 2.3-.25-1.45-.85-2.05-2.3-2.3 1.45-.25 2.05-.85 2.3-2.3Z" /></>}
		{name === "home" && <><path {...common} d="m4 11.2 8-6.5 8 6.5v8.1a1.7 1.7 0 0 1-1.7 1.7H5.7A1.7 1.7 0 0 1 4 19.3z" /><path {...common} d="M9.2 21v-5.6h5.6V21" /></>}
		{name === "insights" && <><circle {...common} cx="10.8" cy="10.8" r="6.3" /><path {...common} d="m15.5 15.5 4.2 4.2" /></>}
		{name === "sources" && <><circle {...common} cx="12" cy="12" r="4.4" /><path {...common} d="M12 3.5v2M12 18.5v2M20.5 12h-2M5.5 12h-2M18 6l-1.4 1.4M7.4 16.6 6 18M18 18l-1.4-1.4M7.4 7.4 6 6" /></>}
		{name === "compare" && <><path {...common} d="M4 8h13.5M14.5 4l4 4-4 4M20 16H6.5M9.5 12l-4 4 4 4" /></>}
		{name === "questions" && <><path {...common} d="M9.2 9a2.9 2.9 0 1 1 4.9 2.1c-1.6 1.4-2.1 1.8-2.1 3.4" /><path {...common} d="M12 18.5h.01" /></>}
		{name === "actions" && <><path {...common} d="M6 18 18 6M10 6h8v8" /></>}
		{name === "collaboration" && <><path {...common} d="M5.2 6.2h9.6a2.2 2.2 0 0 1 2.2 2.2v4.3a2.2 2.2 0 0 1-2.2 2.2H9l-3.8 2.9v-3.2A2.2 2.2 0 0 1 3 12.4v-4a2.2 2.2 0 0 1 2.2-2.2Z" /><path {...common} d="M17 9.2h1.8a2.2 2.2 0 0 1 2.2 2.2v3.2a2.2 2.2 0 0 1-2.2 2.2H18v2.5l-3.2-2.5" /></>}
		{name === "results" && <><path {...common} d="M4 19.5h16" /><path {...common} d="M6.5 16v-4M11.5 16V8.5M16.5 16V5" /><path {...common} d="m6.5 8.5 4-3 4 1.5 3-3" /></>}
		{name === "content" && <><rect {...common} x="5" y="3.5" width="14" height="17" rx="2" /><path {...common} d="M8.5 8h7M8.5 12h7M8.5 16h4.5" /></>}
		{name === "operations" && <><path {...common} d="M5 12h3l2-5 4 10 2-5h3" /></>}
		{name === "providers" && <><path {...common} d="m12 3 8 8-8 8-8-8z" /><path {...common} d="m4 11 8 8 8-8" /></>}
		{name === "settings" && <><circle {...common} cx="12" cy="12" r="3" /><path {...common} d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56v.08h-3v-.08a1.7 1.7 0 0 0-1.03-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15a1.7 1.7 0 0 0-1.56-1.03h-.08v-3h.08A1.7 1.7 0 0 0 7.06 9.94 1.7 1.7 0 0 0 6.72 8l-.06-.06 2.1-2.1.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4.6h3v.08a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.94 1.7 1.7 0 0 0 1.56 1.03h.08v3h-.08A1.7 1.7 0 0 0 19.4 15z" /></>}
		{name === "chevron" && <path {...common} d="m9 18 6-6-6-6" />}
		{name === "close" && <><path {...common} d="m6 6 12 12" /><path {...common} d="M18 6 6 18" /></>}
	</svg>;
}

export function GeoFloatingSidebar({ workspaces = [] }: { workspaces?: Array<{ id: number; name: string }> }) {
	const pathname = usePathname();
	const router = useRouter();
	const searchParams = useSearchParams();
	const closeButtonRef = useRef<HTMLButtonElement>(null);
	const active = resolveGeoNavigation(pathname);
	const [expanded, setExpanded] = useState(true);
	const [insightsOpen, setInsightsOpen] = useState(active.section === "insights");
	const [managementOpen, setManagementOpen] = useState(active.section === "management");

	useEffect(() => {
		const saved = window.localStorage.getItem("cq-geo-sidebar-expanded");
		if (window.innerWidth < 700) setExpanded(false);
		else if (saved !== null) setExpanded(saved === "true");
		else if (window.innerWidth < 920) setExpanded(false);
	}, []);

	useEffect(() => {
		if (active.section === "insights") setInsightsOpen(true);
		if (active.section === "management") setManagementOpen(true);
	}, [active.section]);

	useEffect(() => {
		if (!expanded || window.innerWidth >= 700) return;
		const previousOverflow = document.body.style.overflow;
		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			setExpanded(false);
			window.localStorage.setItem("cq-geo-sidebar-expanded", "false");
		};
		document.body.style.overflow = "hidden";
		document.addEventListener("keydown", handleKeyDown);
		window.requestAnimationFrame(() => closeButtonRef.current?.focus());
		return () => {
			document.body.style.overflow = previousOverflow;
			document.removeEventListener("keydown", handleKeyDown);
		};
	}, [expanded]);

	if (!pathname.startsWith("/geo/") && !pathname.startsWith("/admin/providers")) return null;
	const pathWorkspaceId = pathname.match(/^\/geo\/([^/]+)/)?.[1];
	const queryWorkspaceId = searchParams.get("workspace") ?? "";
	const workspaceId = pathWorkspaceId ?? (/^\d+$/.test(queryWorkspaceId) ? queryWorkspaceId : "");
	const workspaceHome = workspaceId ? `/geo/${workspaceId}` : "/";
	const currentScopeParams = new URLSearchParams(searchParams.toString());
	const scopedHref = (href: string) => preserveGeoScopeInHref(href, currentScopeParams) as Route;
	const workspaceNameCounts = new Map<string, number>();
	for (const workspace of workspaces) workspaceNameCounts.set(workspace.name, (workspaceNameCounts.get(workspace.name) ?? 0) + 1);
	const questionAnalysisActive = /^\/geo\/[^/]+\/questions\/(analysis|\d+)/.test(pathname);

	const setSidebarExpanded = (next: boolean) => {
		setExpanded(next);
		window.localStorage.setItem("cq-geo-sidebar-expanded", String(next));
	};
	const closeAfterMobileNavigation = () => {
		if (window.innerWidth < 700) setSidebarExpanded(false);
	};
	const toggleGroup = (group: "insights" | "management") => {
		if (!expanded) setSidebarExpanded(true);
		if (group === "insights") setInsightsOpen((current) => !current || !expanded);
		else setManagementOpen((current) => !current || !expanded);
	};

	const renderPrimaryLink = (item: SidebarLink) => {
		const itemActive = active.section === item.key;
		return <div key={item.key} className={`geo-floating-nav-group${itemActive ? " is-active-group" : ""}`}>
			<Link href={scopedHref(item.href(workspaceId))} className={`geo-floating-nav-item${itemActive ? " is-active" : ""}`} aria-current={itemActive ? "page" : undefined} title={!expanded ? item.label : undefined} onClick={closeAfterMobileNavigation}>
				<span className="geo-floating-icon"><NavIcon name={item.icon ?? "home"} /></span><span className="geo-floating-label">{item.label}</span><span className="geo-floating-route-chevron"><NavIcon name="chevron" /></span>
			</Link>
		</div>;
	};

	return <>
		{expanded ? <button type="button" className="geo-floating-mobile-scrim" onClick={() => setSidebarExpanded(false)} aria-label="关闭导航面板" tabIndex={-1} /> : null}
		<aside id="geo-primary-navigation" className={`geo-floating-sidebar${expanded ? " is-expanded" : ""}`} aria-label="入答 AnswerReach 功能导航">
			<div className="geo-floating-head">
				{expanded ? <>
					<Link className="geo-floating-brand" href={scopedHref(workspaceHome)} aria-label={workspaceId ? "返回经营驾驶舱" : "返回工作区"}>
						<img className="geo-floating-mark" alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" /><b>入答 <small>AnswerReach</small></b>
					</Link>
					<button ref={closeButtonRef} type="button" className="geo-floating-toggle" onClick={() => setSidebarExpanded(false)} aria-expanded="true" aria-controls="geo-primary-navigation" aria-label="收起功能栏">
						<span className="geo-floating-toggle-desktop"><NavIcon name="chevron" /></span><span className="geo-floating-toggle-mobile"><NavIcon name="close" /></span>
					</button>
				</> : <button type="button" className="geo-floating-collapsed-toggle" onClick={() => setSidebarExpanded(true)} aria-expanded="false" aria-controls="geo-primary-navigation" aria-label="展开功能栏">
					<img className="geo-floating-mark" alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" /><span className="geo-floating-collapsed-chevron"><NavIcon name="chevron" /></span>
				</button>}
			</div>
			{expanded && workspaces.length ? <label className="geo-floating-workspace-switcher"><span>当前工作区</span><select value={workspaceId || String(workspaces[0].id)} onChange={(event) => router.push(`/geo/${event.target.value}` as Route)}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}{(workspaceNameCounts.get(workspace.name) ?? 0) > 1 ? ` · #${workspace.id}` : ""}</option>)}</select></label> : null}
			<nav className="geo-floating-nav" aria-label="主导航">
				{renderPrimaryLink(PRIMARY_LINKS[0])}
				{renderPrimaryLink(PRIMARY_LINKS[1])}
				<div className={`geo-floating-nav-group${active.section === "insights" ? " is-active-group" : ""}`}>
					<button type="button" className={`geo-floating-parent${active.section === "insights" ? " is-active" : ""}`} onClick={() => toggleGroup("insights")} aria-expanded={insightsOpen} aria-controls="geo-insight-navigation" title={!expanded ? "洞察" : undefined}>
						<span className="geo-floating-icon"><NavIcon name="insights" /></span><span className="geo-floating-label">洞察</span><span className={`geo-floating-group-chevron${insightsOpen ? " is-open" : ""}`}><NavIcon name="chevron" /></span>
					</button>
					{expanded && insightsOpen ? <div id="geo-insight-navigation" className="geo-floating-child-list">
						{INSIGHT_LINKS.map((item) => {
							const itemActive = active.section === "insights" && active.child === item.key;
							return <div key={item.key}>
				<Link href={scopedHref(item.href(workspaceId))} className={`geo-floating-child-link${itemActive ? " is-active" : ""}`} aria-current={itemActive ? "page" : undefined} onClick={closeAfterMobileNavigation}>
									<span>{item.label}</span><NavIcon name="chevron" />
								</Link>
				{item.key === "questions" && itemActive && workspaceId ? <Link className={`geo-floating-subnav${questionAnalysisActive ? " is-active" : ""}`} href={scopedHref(`/geo/${workspaceId}/questions/analysis`)} aria-current={questionAnalysisActive ? "page" : undefined} onClick={closeAfterMobileNavigation}><span className="geo-floating-subnav-mark" /><span className="geo-floating-label">问题分析</span></Link> : null}
							</div>;
						})}
					</div> : null}
				</div>
				{PRIMARY_LINKS.slice(2).map(renderPrimaryLink)}
				<div className={`geo-floating-nav-group${active.section === "management" ? " is-active-group" : ""}`}>
					<button type="button" className={`geo-floating-parent${active.section === "management" ? " is-active" : ""}`} onClick={() => toggleGroup("management")} aria-expanded={managementOpen} aria-controls="geo-management-navigation" title={!expanded ? "管理" : undefined}>
						<span className="geo-floating-icon"><NavIcon name="settings" /></span><span className="geo-floating-label">管理</span><span className={`geo-floating-group-chevron${managementOpen ? " is-open" : ""}`}><NavIcon name="chevron" /></span>
					</button>
					{expanded && managementOpen ? <div id="geo-management-navigation" className="geo-floating-child-list">
						{MANAGEMENT_LINKS.map((item) => {
							const itemActive = active.section === "management" && active.child === item.key;
							return <Link key={item.key} href={item.href(workspaceId).startsWith("/geo/") ? scopedHref(item.href(workspaceId)) : item.href(workspaceId) as Route} className={`geo-floating-child-link${itemActive ? " is-active" : ""}`} aria-current={itemActive ? "page" : undefined} onClick={closeAfterMobileNavigation}><span>{item.label}</span><NavIcon name="chevron" /></Link>;
						})}
					</div> : null}
				</div>
			</nav>
		</aside>
	</>;
}
