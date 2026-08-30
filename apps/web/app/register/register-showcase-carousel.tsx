"use client";

import { type PointerEvent, useEffect, useRef, useState } from "react";

const slides = [
  { asset: "/auth/register-batch-showcase-v3.png", crop: "batches", label: "观测批次", note: "任务状态与原始记录" },
  { asset: "/auth/register-question-library-v3.png", crop: "questions", label: "问题库", note: "常用问题与单题分析" },
  { asset: "/auth/register-model-compare-v3.png", crop: "comparison", label: "模型对比", note: "回答概览与引用证据" },
  { asset: "/auth/register-decision-map-v3.png", crop: "decisions", label: "决策地图", note: "问题与模型推荐矩阵" },
  { asset: "/auth/register-source-evidence-v3.png", crop: "sources", label: "来源证据", note: "权威来源与引用关系" },
] as const;

const INITIAL_INDEX = 0;
const FIRST_ADVANCE_DELAY_MS = 1200;
const AUTO_ADVANCE_DELAY_MS = 2800;

export function RegisterShowcaseCarousel() {
  const rootRef = useRef<HTMLDivElement>(null);
  const gestureRef = useRef({ lastTime: 0, lastX: 0, moved: false, startX: 0, velocity: 0 });
  const hasAdvancedRef = useRef(false);
  const [activeIndex, setActiveIndex] = useState(INITIAL_INDEX);
  const [dragging, setDragging] = useState(false);
  const [paused, setPaused] = useState(false);
  const [scheduleVersion, setScheduleVersion] = useState(0);

  const move = (direction: -1 | 1) => {
    hasAdvancedRef.current = true;
    setActiveIndex((current) => (current + direction + slides.length) % slides.length);
    setScheduleVersion((current) => current + 1);
  };

  const select = (index: number) => {
    if (gestureRef.current.moved) {
      gestureRef.current.moved = false;
      return;
    }
    if (index === activeIndex) return;
    hasAdvancedRef.current = true;
    setActiveIndex(index);
    setScheduleVersion((current) => current + 1);
  };

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (paused || dragging || reducedMotion.matches) return;

    const timer = window.setTimeout(() => {
      hasAdvancedRef.current = true;
      setActiveIndex((current) => (current + 1) % slides.length);
      setScheduleVersion((current) => current + 1);
    }, hasAdvancedRef.current ? AUTO_ADVANCE_DELAY_MS : FIRST_ADVANCE_DELAY_MS);

    return () => window.clearTimeout(timer);
  }, [dragging, paused, scheduleVersion]);

  const setDragOffset = (value: number) => {
    rootRef.current?.style.setProperty("--cq-register-drag-x", `${value}px`);
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest(".cq-register-showcase-controls")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    gestureRef.current = { lastTime: event.timeStamp, lastX: event.clientX, moved: false, startX: event.clientX, velocity: 0 };
    setDragging(true);
    setPaused(true);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const gesture = gestureRef.current;
    const deltaTime = Math.max(1, event.timeStamp - gesture.lastTime);
    gesture.velocity = ((event.clientX - gesture.lastX) / deltaTime) * 1000;
    gesture.lastTime = event.timeStamp;
    gesture.lastX = event.clientX;
    const rawOffset = event.clientX - gesture.startX;
    if (Math.abs(rawOffset) > 8) gesture.moved = true;
    const resistedOffset = Math.sign(rawOffset) * Math.min(Math.abs(rawOffset), 180);
    setDragOffset(resistedOffset);
  };

  const finishGesture = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const gesture = gestureRef.current;
    const distance = event.clientX - gesture.startX;
    const projectedDistance = distance + gesture.velocity * .16;
    setDragging(false);
    setPaused(false);
    setDragOffset(0);

    if (Math.abs(projectedDistance) >= 46) move(projectedDistance < 0 ? 1 : -1);
    else setScheduleVersion((current) => current + 1);
  };

  return (
    <div
      aria-label="GEO 产品能力循环预览"
      className={`cq-register-showcase-carousel${dragging ? " is-dragging" : ""}`}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setPaused(false);
      }}
      onFocusCapture={() => setPaused(true)}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onPointerCancel={finishGesture}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishGesture}
      ref={rootRef}
      role="region"
    >
      <div className="cq-register-showcase-deck">
        {slides.map((slide, index) => {
          const distance = (index - activeIndex + slides.length) % slides.length;
          const position = distance === 0 ? "center" : distance === 1 ? "right" : distance === 2 ? "far-right" : distance === slides.length - 1 ? "left" : "far-left";
          return (
            <button
              aria-label={`${slide.label}：${slide.note}`}
              aria-pressed={index === activeIndex}
              className={`cq-register-showcase-slide is-${position} crop-${slide.crop}`}
              key={slide.crop}
              onClick={() => select(index)}
              type="button"
            >
              <span aria-hidden="true" className="cq-register-showcase-slide-brand">
                <img alt="" src="/brand/answerreach-mark.svg" />
                <b>入答 <em>AnswerReach</em></b>
              </span>
              <span className="cq-register-showcase-slide-image" style={{ backgroundImage: `url("${slide.asset}")` }} />
              <span className="cq-register-showcase-slide-copy"><b>{slide.label}</b><small>{slide.note}</small></span>
            </button>
          );
        })}
      </div>

      <div className="cq-register-showcase-controls">
        <button aria-label="上一张" onClick={() => move(-1)} type="button">←</button>
        <div aria-hidden="true">{slides.map((slide, index) => <i className={index === activeIndex ? "is-active" : ""} key={slide.crop} />)}</div>
        <button aria-label="下一张" onClick={() => move(1)} type="button">→</button>
      </div>
      <p aria-live="polite" className="cq-auth-sr-only">当前展示：{slides[activeIndex].label}</p>
    </div>
  );
}
