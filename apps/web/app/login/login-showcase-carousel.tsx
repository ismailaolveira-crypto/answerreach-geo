"use client";

import { type TransitionEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const cards = [
  {
    alt: "决策地图：模型、问题与轮次的蓝白观测矩阵和回答证据抽屉。",
    label: "决策地图",
    src: "/auth/login-card-decision-map-v1.png"
  },
  {
    alt: "信源地图：AI 回答连接多张来源 URL 卡片与原始工作件详情。",
    label: "信源地图",
    src: "/auth/login-card-source-map-v1.png"
  },
  {
    alt: "竞品对比：在同一问题和同一批次中并列比较品牌与竞品的引用证据。",
    label: "竞品对比",
    src: "/auth/login-card-competitor-view-v1.png"
  },
  {
    alt: "问题库：按常用问题与临时问题管理采购问题，并查看单问题分析。",
    label: "问题库",
    src: "/auth/login-card-question-library-v1.png"
  },
  {
    alt: "历史批次：查看观测批次的运行状态、模型问题轮次和原始记录。",
    label: "历史批次",
    src: "/auth/login-card-batch-history-v1.png"
  }
] as const;

const FIRST_ADVANCE_DELAY_MS = 1500;
const AUTO_ADVANCE_DELAY_MS = 2800;
const INITIAL_CARD_INDEX = 2;
const FIRST_REAL_CARD_POSITION = 1;
const TRAILING_FIRST_CLONE_POSITION = cards.length + 1;

const carouselCards = [
  { card: cards[cards.length - 1], clone: true, key: "leading-last" },
  ...cards.map((card) => ({ card, clone: false, key: card.src })),
  { card: cards[0], clone: true, key: "trailing-first" },
  { card: cards[1], clone: true, key: "trailing-second" }
] as const;

export function LoginShowcaseCarousel() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const hasAutoAdvancedRef = useRef(false);
  const wrapFrameRef = useRef<number | undefined>(undefined);
  const [position, setPosition] = useState(INITIAL_CARD_INDEX + FIRST_REAL_CARD_POSITION);
  const [isReady, setIsReady] = useState(false);
  const [isWrapping, setIsWrapping] = useState(false);
  const [offset, setOffset] = useState(0);
  const [paused, setPaused] = useState(false);
  const [scheduleVersion, setScheduleVersion] = useState(0);

  const activeIndex = ((position - FIRST_REAL_CARD_POSITION) % cards.length + cards.length) % cards.length;

  const centerActiveCard = useCallback(() => {
    const viewport = viewportRef.current;
    const track = trackRef.current;
    const activeCard = track?.children.item(position) as HTMLElement | null;
    if (!viewport || !activeCard) return;

    setOffset(viewport.clientWidth / 2 - (activeCard.offsetLeft + activeCard.clientWidth / 2));
  }, [position]);

  useLayoutEffect(() => {
    centerActiveCard();
    const observer = new ResizeObserver(centerActiveCard);
    if (viewportRef.current) observer.observe(viewportRef.current);
    if (trackRef.current) observer.observe(trackRef.current);
    return () => observer.disconnect();
  }, [centerActiveCard]);

  useEffect(() => {
    const readyFrame = window.requestAnimationFrame(() => setIsReady(true));
    return () => window.cancelAnimationFrame(readyFrame);
  }, []);

  useEffect(() => {
    return () => {
      if (wrapFrameRef.current !== undefined) window.cancelAnimationFrame(wrapFrameRef.current);
    };
  }, []);

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (paused || reducedMotion.matches) return;

    const advance = () => {
      setPosition((current) => current >= TRAILING_FIRST_CLONE_POSITION ? FIRST_REAL_CARD_POSITION : current + 1);
    };

    let interval: number | undefined;
    const timer = window.setTimeout(() => {
      hasAutoAdvancedRef.current = true;
      advance();
      interval = window.setInterval(advance, AUTO_ADVANCE_DELAY_MS);
    }, hasAutoAdvancedRef.current ? AUTO_ADVANCE_DELAY_MS : FIRST_ADVANCE_DELAY_MS);

    return () => {
      window.clearTimeout(timer);
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [paused, scheduleVersion]);

  const selectCard = (index: number) => {
    hasAutoAdvancedRef.current = true;
    setPosition(index + FIRST_REAL_CARD_POSITION);
    setPaused(false);
    setScheduleVersion((current) => current + 1);
  };

  const finishCircularWrap = (event: TransitionEvent<HTMLDivElement>) => {
    if (event.target !== trackRef.current || event.propertyName !== "transform" || position !== TRAILING_FIRST_CLONE_POSITION) {
      return;
    }

    setIsWrapping(true);
    setPosition(FIRST_REAL_CARD_POSITION);
    wrapFrameRef.current = window.requestAnimationFrame(() => {
      wrapFrameRef.current = window.requestAnimationFrame(() => setIsWrapping(false));
    });
  };

  return (
    <section
      aria-label="春秋元泉 GEO 工作台能力预览"
      className={`cq-auth-showcase${isReady ? " is-ready" : ""}${isWrapping ? " is-wrapping" : ""}`}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setPaused(false);
      }}
      onFocusCapture={() => setPaused(true)}
    >
      <h1 className="cq-auth-sr-only">春秋元泉 GEO 工作台能力预览</h1>
      <div className="cq-auth-showcase-viewport" ref={viewportRef}>
        <div
          className="cq-auth-showcase-track"
          onTransitionEnd={finishCircularWrap}
          ref={trackRef}
          style={{ transform: `translate3d(${offset}px, 0, 0)` }}
        >
          {carouselCards.map(({ card, clone, key }, renderIndex) => {
            const logicalIndex = clone ? -1 : renderIndex - FIRST_REAL_CARD_POSITION;
            const isVisuallyActive = renderIndex === position;

            if (clone) {
              return (
                <div aria-hidden="true" className={`cq-auth-showcase-card is-clone${isVisuallyActive ? " is-active" : ""}`} key={key}>
                  <img alt="" src={card.src} />
                </div>
              );
            }

            return (
              <button
                aria-label={`定位到${card.label}`}
                aria-pressed={logicalIndex === activeIndex}
                className={`cq-auth-showcase-card${isVisuallyActive ? " is-active" : ""}`}
                key={key}
                onClick={() => selectCard(logicalIndex)}
                type="button"
              >
                <img alt={card.alt} src={card.src} />
              </button>
            );
          })}
        </div>
      </div>
      <p aria-live="polite" className="cq-auth-sr-only">当前展示：{cards[activeIndex].label}</p>
    </section>
  );
}
