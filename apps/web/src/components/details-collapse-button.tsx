"use client";

import type { MouseEvent } from "react";

type Props = {
	label: string;
};

export function DetailsCollapseButton({ label }: Props) {
	function collapseDetails(event: MouseEvent<HTMLButtonElement>) {
		const details = event.currentTarget.closest("details");
		const summary = details?.querySelector(":scope > summary");
		if (!(details instanceof HTMLDetailsElement) || !(summary instanceof HTMLElement)) return;

		details.open = false;
		window.requestAnimationFrame(() => {
			summary.focus({ preventScroll: true });
			summary.scrollIntoView({
				behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
				block: "center",
			});
		});
	}

	return <div className="sy-details-collapse">
		<button type="button" onClick={collapseDetails}>
			<span aria-hidden="true">↑</span>{label}
		</button>
	</div>;
}
