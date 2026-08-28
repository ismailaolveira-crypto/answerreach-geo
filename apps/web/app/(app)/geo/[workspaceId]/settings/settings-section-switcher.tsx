"use client";

import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import styles from "./settings.module.css";

type SettingsSection = "basics" | "collaboration" | "facts" | "agent";

const TABS: Array<{ id: SettingsSection; label: string; note: string }> = [
	{ id: "basics", label: "基本信息", note: "品牌与运行入口" },
	{ id: "collaboration", label: "成员与设备", note: "权限与 Local Agent" },
	{ id: "facts", label: "品牌事实", note: "Agent 可用依据" },
	{ id: "agent", label: "Agent 与交付", note: "Codex 与 GEO 文章助手" },
];

function sectionFromHash(): SettingsSection {
	if (typeof window === "undefined") return "basics";
	const value = window.location.hash.replace(/^#/, "");
	if (value === "brand-facts" || value === "facts") return "facts";
	return TABS.some((tab) => tab.id === value) ? value as SettingsSection : "basics";
}

export function SettingsSectionSwitcher({
	basics,
	collaboration,
	facts,
	agent,
}: {
	basics: ReactNode;
	collaboration: ReactNode;
	facts: ReactNode;
	agent: ReactNode;
}) {
	const [active, setActive] = useState<SettingsSection>("basics");
	const panels: Record<SettingsSection, ReactNode> = { basics, collaboration, facts, agent };
	useEffect(() => {
		const sync = () => setActive(sectionFromHash());
		sync();
		window.addEventListener("hashchange", sync);
		return () => window.removeEventListener("hashchange", sync);
	}, []);
	const selectTab = (id: SettingsSection) => {
		setActive(id);
		window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${id}`);
	};
	const moveTabFocus = (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
		let nextIndex = currentIndex;
		if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % TABS.length;
		else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + TABS.length) % TABS.length;
		else if (event.key === "Home") nextIndex = 0;
		else if (event.key === "End") nextIndex = TABS.length - 1;
		else return;
		event.preventDefault();
		const nextTab = TABS[nextIndex];
		selectTab(nextTab.id);
		document.getElementById(`settings-tab-${nextTab.id}`)?.focus();
	};

	return <>
		<div className={styles.sectionTabs} role="tablist" aria-label="工作区设置分区">
			{TABS.map((tab, index) => <button
				key={tab.id}
				type="button"
				role="tab"
				id={`settings-tab-${tab.id}`}
				aria-selected={active === tab.id}
				aria-controls={`settings-panel-${tab.id}`}
				tabIndex={active === tab.id ? 0 : -1}
				className={active === tab.id ? styles.sectionTabActive : undefined}
				onClick={() => selectTab(tab.id)}
				onKeyDown={(event) => moveTabFocus(event, index)}
			>
				<span>{tab.label}</span>
				<small>{tab.note}</small>
			</button>)}
		</div>
		{TABS.map((tab) => <section
			key={tab.id}
			role="tabpanel"
			id={`settings-panel-${tab.id}`}
			aria-labelledby={`settings-tab-${tab.id}`}
			hidden={active !== tab.id}
			className={styles.sectionPanel}
		>
			{panels[tab.id]}
		</section>)}
	</>;
}
