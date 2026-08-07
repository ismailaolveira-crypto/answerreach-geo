"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const cards = [
  {
    alt: "决策地图：模型、问题与轮次的蓝白观测矩阵和回答证据抽屉。",
    src: "/auth/login-card-decision-map-v1.png"
  },
  {
    alt: "信源地图：AI 回答连接多张来源 URL 卡片与原始工作件详情。",
    src: "/auth/login-card-source-map-v1.png"
  },
  {
    alt: "竞品对比：在同一问题和同一批次中并列比较品牌与竞品的引用证据。",
    src: "/auth/login-card-competitor-view-v1.png"
  },
  {
    alt: "问题库：按常用问题与临时问题管理采购问题，并查看单问题分析。",
    src: "/auth/login-card-question-library-v1.png"
  },
  {
    alt: "历史批次：查看观测批次的运行状态、模型问题轮次和原始记录。",
    src: "/auth/login-card-batch-history-v1.png"
  }
] as const;

export function LoginShowcaseCarousel() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const directionRef = useRef(1);
  const [activeIndex, setActiveIndex] = useState(2);
  const [offset, setOffset] = useState(0);
  const [paused, setPaused] = useState(false);

  const centerActiveCard = useCallback(() => {
    const viewport = viewportRef.current;
    const track = trackRef.current;
    const activeCard = track?.children.item(activeIndex) as HTMLElement | null;
    if (!viewport || !activeCard) return;

    setOffset(viewport.clientWidth / 2 - (activeCard.offsetLeft + activeCard.clientWidth / 2));
  }, [activeIndex]);

  useLayoutEffect(() => {
    centerActiveCard();
    const observer = new ResizeObserver(centerActiveCard);
    if (viewportRef.current) observer.observe(viewportRef.current);
    if (trackRef.current) observer.observe(trackRef.current);
    return () => observer.disconnect();
  }, [centerActiveCard]);

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (paused || reducedMotion.matches) return;

    const timer = window.setInterval(() => {
      setActiveIndex((current) => {
        if (current === cards.length - 1) directionRef.current = -1;
        if (current === 0) directionRef.current = 1;
        return current + directionRef.current;
      });
    }, 4200);

    return () => window.clearInterval(timer);
  }, [paused]);

  return (
    <section
      aria-label="春秋元泉 GEO 工作台能力预览"
      className="cq-auth-showcase"
      onFocusCapture={() => setPaused(true)}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <h1 className="cq-auth-sr-only">春秋元泉 GEO 工作台能力预览</h1>
      <div className="cq-auth-showcase-viewport" ref={viewportRef}>
        <div className="cq-auth-showcase-track" ref={trackRef} style={{ transform: `translate3d(${offset}px, 0, 0)` }}>
          {cards.map((card, index) => (
            <article className={`cq-auth-showcase-card${index === activeIndex ? " is-active" : ""}`} key={card.src}>
              <img alt={card.alt} src={card.src} />
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
