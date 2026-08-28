"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

const FEEDBACK_DELAY_MS = 220;
const FEEDBACK_MAX_MS = 3000;

export function InteractionFeedback() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, setPending] = useState(false);
  const delayRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const locationWatchRef = useRef<number | null>(null);
  const activeRef = useRef<HTMLElement | null>(null);

  const clearPending = useCallback((updateState = true) => {
    if (delayRef.current !== null) {
      window.clearTimeout(delayRef.current);
      delayRef.current = null;
    }
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (locationWatchRef.current !== null) {
      window.clearInterval(locationWatchRef.current);
      locationWatchRef.current = null;
    }
    // Remove the legacy body state as well so an older hot-reloaded bundle
    // can never leave the application looking permanently busy.
    document.body.classList.remove("interaction-pending");
    activeRef.current?.removeAttribute("data-pending-click");
    activeRef.current = null;
    if (updateState) setPending(false);
  }, []);

  useEffect(() => {
    clearPending();
  }, [clearPending, pathname, searchParams]);

  useEffect(() => {
    function showPending(target: HTMLElement, destination: URL) {
      clearPending();
      delayRef.current = window.setTimeout(() => {
        delayRef.current = null;
        activeRef.current = target;
        target.setAttribute("data-pending-click", "true");
        setPending(true);

        const destinationPath = `${destination.pathname}${destination.search}`;
        locationWatchRef.current = window.setInterval(() => {
          const currentPath = `${window.location.pathname}${window.location.search}`;
          if (currentPath === destinationPath) clearPending();
        }, 80);

        // Navigation feedback must be advisory, never a global lock. If a
        // route fails, the user can immediately retry or choose another page.
        timerRef.current = window.setTimeout(clearPending, FEEDBACK_MAX_MS);
      }, FEEDBACK_DELAY_MS);
    }

    function handleClick(event: MouseEvent) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (!(event.target instanceof HTMLElement)) return;
      const link = event.target.closest("a") as HTMLAnchorElement | null;
      if (!link || link.hasAttribute("download") || link.target === "_blank" || link.dataset.noNavigationFeedback === "true") return;
      const href = link.getAttribute("href") ?? "";
      if (!href || href.startsWith("#") || href.startsWith("blob:") || href.startsWith("mailto:") || href.startsWith("tel:")) return;
      const destination = new URL(href, window.location.href);
      if (destination.origin !== window.location.origin) return;
      if (`${destination.pathname}${destination.search}` === `${window.location.pathname}${window.location.search}`) return;
      showPending(link, destination);
    }

    const handleNavigationSettled = () => clearPending();

    window.addEventListener("click", handleClick, true);
    window.addEventListener("pageshow", handleNavigationSettled);
    window.addEventListener("popstate", handleNavigationSettled);
    window.addEventListener("hashchange", handleNavigationSettled);
    return () => {
      window.removeEventListener("click", handleClick, true);
      window.removeEventListener("pageshow", handleNavigationSettled);
      window.removeEventListener("popstate", handleNavigationSettled);
      window.removeEventListener("hashchange", handleNavigationSettled);
      clearPending(false);
    };
  }, [clearPending]);

  return (
    <>
      <div className={`interaction-bar${pending ? " is-visible" : ""}`} aria-hidden={!pending} />
      <div className={`interaction-toast${pending ? " is-visible" : ""}`} role="status" aria-live="polite">
        {pending ? "正在打开..." : ""}
      </div>
    </>
  );
}
