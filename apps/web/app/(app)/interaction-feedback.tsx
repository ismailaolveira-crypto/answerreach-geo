"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export function InteractionFeedback() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, setPending] = useState(false);
  const delayRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const activeRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    function clearPending() {
      if (delayRef.current) {
        window.clearTimeout(delayRef.current);
        delayRef.current = null;
      }
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      document.body.classList.remove("interaction-pending");
      activeRef.current?.removeAttribute("data-pending-click");
      activeRef.current = null;
      setPending(false);
    }

    clearPending();
    return clearPending;
  }, [pathname, searchParams]);

  useEffect(() => {
    function showPending(target: HTMLElement, timeoutMs: number) {
      if (delayRef.current) window.clearTimeout(delayRef.current);
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
      }
      activeRef.current?.removeAttribute("data-pending-click");
      delayRef.current = window.setTimeout(() => {
        delayRef.current = null;
        activeRef.current = target;
        target.setAttribute("data-pending-click", "true");
        document.body.classList.add("interaction-pending");
        setPending(true);
        timerRef.current = window.setTimeout(() => {
          document.body.classList.remove("interaction-pending");
          target.removeAttribute("data-pending-click");
          if (activeRef.current === target) activeRef.current = null;
          setPending(false);
        }, timeoutMs);
      }, 180);
    }

    function handleClick(event: MouseEvent) {
      if (!(event.target instanceof HTMLElement)) return;
      const link = event.target.closest("a") as HTMLAnchorElement | null;
      if (!link || link.hasAttribute("download") || link.target === "_blank") return;
      const href = link.getAttribute("href") ?? "";
      if (!href || href.startsWith("#") || href.startsWith("blob:") || href.startsWith("mailto:") || href.startsWith("tel:")) return;
      const destination = new URL(href, window.location.href);
      if (destination.origin !== window.location.origin) return;
      if (`${destination.pathname}${destination.search}` === `${window.location.pathname}${window.location.search}`) return;
      showPending(link, 5000);
    }

    window.addEventListener("click", handleClick, true);
    return () => {
      window.removeEventListener("click", handleClick, true);
      if (delayRef.current) window.clearTimeout(delayRef.current);
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <>
      <div className="interaction-bar" aria-hidden={!pending} />
      <div className="interaction-toast" role="status" aria-live="polite">
        {pending ? "正在打开..." : ""}
      </div>
    </>
  );
}
