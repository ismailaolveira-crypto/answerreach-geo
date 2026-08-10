"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BrandLogo } from "@/components/brand-logo";
import type {
  OfficialApiObservationBatch,
  OfficialApiObservationBatchGroup,
  OfficialApiObservationTask,
} from "@/lib/cleanroom-v1-api";
import styles from "./observation-batch-progress.module.css";

const SETTLED = new Set(["success", "partial", "failed"]);

type ObservationStatus = OfficialApiObservationTask["status"];

type ObservationNode = {
  status: ObservationStatus;
  task?: OfficialApiObservationTask;
};

const SPECTRAL_PALETTES = [
  { start: "#16c7d9", end: "#1f5ef5" },
  { start: "#4f5ff4", end: "#c341e8" },
  { start: "#00b894", end: "#1787e8" },
  { start: "#2f80ed", end: "#7b61ff" },
  { start: "#7b5cff", end: "#ec4899" },
  { start: "#0ea5e9", end: "#14b8a6" },
] as const;

const KNOWN_PROVIDER_PALETTE: Record<string, number> = {
  qwen: 0,
  qianwen: 0,
  glm: 1,
  deepseek: 2,
  kimi: 3,
  doubao: 4,
  hunyuan: 5,
};

const NODE_STATUS_LABELS: Record<ObservationStatus, string> = {
  pending: "等待中",
  running: "运行中",
  success: "成功",
  failed: "失败",
};

function summary(batch: OfficialApiObservationBatch) {
  if (batch.status === "success") return "本批次真实观测已全部完成";
  if (batch.status === "partial") return "本批次已结束，部分观测需要重试";
  if (batch.status === "failed") return "本批次未获得有效结果";
  if (!batch.dispatch_enabled) return "历史批次已保留，不会再执行";
  if (batch.running) return "正在采集真实联网结果";
  return "任务已排队，等待采集服务";
}

function conciseProviderLabel(label: string) {
  return label.split("·", 1)[0]?.trim() || label;
}

function paletteForProvider(key: string) {
  const knownPalette = KNOWN_PROVIDER_PALETTE[key.toLowerCase()];
  if (knownPalette !== undefined) return SPECTRAL_PALETTES[knownPalette];
  const fingerprint = Array.from(key).reduce(
    (total, character) => total + (character.codePointAt(0) ?? 0),
    0,
  );
  return SPECTRAL_PALETTES[fingerprint % SPECTRAL_PALETTES.length];
}

function interpolateHex(start: string, end: string, amount: number) {
  const read = (value: string, offset: number) =>
    Number.parseInt(value.slice(offset, offset + 2), 16);
  const channel = (from: number, to: number) =>
    Math.round(from + (to - from) * amount)
      .toString(16)
      .padStart(2, "0");
  return `#${channel(read(start, 1), read(end, 1))}${channel(read(start, 3), read(end, 3))}${channel(read(start, 5), read(end, 5))}`;
}

function observationNodes(
  group: OfficialApiObservationBatchGroup,
  tasks: OfficialApiObservationTask[],
): ObservationNode[] {
  const groupTasks = tasks
    .filter((task) => task.provider_id === group.id)
    .sort(
      (left, right) =>
        left.question_plan_id - right.question_plan_id ||
        left.repeat_index - right.repeat_index ||
        left.job_id - right.job_id,
    );

  // The detail endpoint normally returns every task in the small dashboard
  // batch. If a future batch exceeds its task page, preserve the authoritative
  // aggregate counts instead of inventing a fixed provider/round template.
  const aggregateFallback: ObservationStatus[] = [
    ...Array<ObservationStatus>(group.succeeded).fill("success"),
    ...Array<ObservationStatus>(group.failed).fill("failed"),
    ...Array<ObservationStatus>(group.running).fill("running"),
    ...Array<ObservationStatus>(group.pending).fill("pending"),
  ];

  return Array.from({ length: group.total }, (_, index) => ({
    status: groupTasks[index]?.status ?? aggregateFallback[index] ?? "pending",
    task: groupTasks[index],
  }));
}

function badgeLabel(batch: OfficialApiObservationBatch) {
  if (batch.status === "success") return "全部完成";
  if (batch.status === "partial") return `${batch.failed} 条需重试`;
  if (batch.status === "failed") return "本批次失败";
  if (!batch.dispatch_enabled) return "历史记录";
  if (batch.running) return `正在观测 ${batch.running} 条`;
  return `等待 ${batch.pending} 条`;
}

function nodeClass(status: ObservationStatus) {
  if (status === "success") return styles.nodeSuccess;
  if (status === "failed") return styles.nodeFailed;
  if (status === "running") return styles.nodeRunning;
  return styles.nodePending;
}

function nodeSymbol(status: ObservationStatus) {
  if (status === "success") return "✓";
  if (status === "failed") return "!";
  return "";
}

export default function ObservationBatchProgress({
  workspaceId,
  initialBatch,
}: {
  workspaceId: string;
  initialBatch: OfficialApiObservationBatch;
}) {
  const router = useRouter();
  const [batch, setBatch] = useState(initialBatch);
  const [pollError, setPollError] = useState("");
  const refreshed = useRef(false);
  const completed = batch.succeeded + batch.failed;
  const isRunning = batch.running > 0;
  const isHistorical = !batch.dispatch_enabled && !SETTLED.has(batch.status);
  const isQueued = !isHistorical && !isRunning && batch.pending > 0 && !SETTLED.has(batch.status);
  const cardMotionClass = isRunning
    ? styles.cardRunning
    : batch.status === "success"
      ? styles.cardComplete
      : styles.cardResting;
  const borderGradientId = `batch-spectral-border-${batch.batch_id}`;

  useEffect(() => {
    // Progress is already updated locally from the lightweight batch endpoint.
    // Refreshing the entire server-rendered dashboard after every completed
    // provider call made the composer stall repeatedly during larger batches.
    // Recalculate KPI/result sections once, only after the batch settles.
    if (SETTLED.has(batch.status) || isHistorical) {
      if (!refreshed.current) {
        refreshed.current = true;
        router.refresh();
      }
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `/api/geo/${workspaceId}/observation-batches/${batch.batch_id}`,
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error("进度同步暂时中断");
        setBatch((await response.json()) as OfficialApiObservationBatch);
        setPollError("");
      } catch (error) {
        setPollError(
          error instanceof Error ? error.message : "进度同步暂时中断",
        );
      }
    }, pollError ? 3000 : 1200);
    return () => window.clearTimeout(timer);
  }, [batch, isHistorical, pollError, router, workspaceId]);

  return (
    <section
      className={`${styles.card} ${styles[`status_${batch.status}`]} ${cardMotionClass}`}
      role="status"
      aria-live="polite"
    >
      <svg
        className={styles.spectralBorder}
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient id={borderGradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#25d7dd" />
            <stop offset="42%" stopColor="#2c73ff" />
            <stop offset="72%" stopColor="#7557ff" />
            <stop offset="100%" stopColor="#ec55df" />
          </linearGradient>
        </defs>
        <rect
          className={styles.spectralBorderGlow}
          x="1.5"
          y="1.5"
          width="calc(100% - 3px)"
          height="calc(100% - 3px)"
          rx="20.5"
          pathLength="100"
          stroke={`url(#${borderGradientId})`}
          vectorEffect="non-scaling-stroke"
        />
        <rect
          className={styles.spectralBorderLine}
          x="1.5"
          y="1.5"
          width="calc(100% - 3px)"
          height="calc(100% - 3px)"
          rx="20.5"
          pathLength="100"
          stroke={`url(#${borderGradientId})`}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <header className={styles.header}>
        <div className={styles.heading}>
          <span>批次 #{batch.batch_id}</span>
          <h2>{summary(batch)}</h2>
          <p>
            {batch.provider_count} 个模型 · {batch.question_count} 个问题 · 每个模型 {batch.repeat_count} 轮
          </p>
        </div>
        <div className={styles.completion}>
          <strong>
            {completed} <small>/ {batch.total}</small>
          </strong>
          <span className={styles.badge}>
            <i aria-hidden="true">{batch.status === "success" ? "✓" : ""}</i>
            {badgeLabel(batch)}
          </span>
        </div>
      </header>

      <div className={styles.columnLabels} aria-hidden="true">
        <span>模型</span>
        <span>真实观测（每个节点代表 1 条真实观测）</span>
        <span>完成</span>
      </div>

      <div className={styles.providerRows}>
        {batch.provider_groups.map((group) => {
          const nodes = observationNodes(group, batch.tasks);
          const done = group.succeeded + group.failed;
          const active = done + group.running;
          const activePercent = group.total
            ? Math.round((active / group.total) * 100)
            : 0;
          const label = conciseProviderLabel(group.label);
          const palette = paletteForProvider(group.key);
          const railStyle = {
            "--rail-start": palette.start,
            "--rail-end": palette.end,
          } as CSSProperties;

          return (
            <article className={styles.providerRow} key={group.id} style={railStyle}>
              <div className={styles.providerIdentity}>
                <BrandLogo brand={group.key} label={label} className={styles.logo} />
                <b title={group.label}>{label}</b>
              </div>
              <div
                className={styles.rail}
                role="progressbar"
                aria-label={`${label} 完成进度`}
                aria-valuemin={0}
                aria-valuemax={group.total}
                aria-valuenow={done}
              >
                <span className={styles.railTrack} aria-hidden="true">
                  <i style={{ width: `${activePercent}%` }} />
                </span>
                <div
                  className={styles.nodes}
                  style={{
                    gridTemplateColumns: `repeat(${Math.max(nodes.length, 1)}, minmax(0, 1fr))`,
                  }}
                >
                  {nodes.map((node, index) => {
                    const position = nodes.length > 1 ? index / (nodes.length - 1) : 0;
                    const nodeColor = interpolateHex(
                      palette.start,
                      palette.end,
                      position,
                    );
                    const taskLabel = node.task
                      ? `${node.task.question_label} · 第 ${node.task.repeat_index} 次`
                      : `第 ${index + 1} 条观测`;
                    const title = `${taskLabel} · ${NODE_STATUS_LABELS[node.status]}`;
                    const nodeStyle = {
                      "--node-color": nodeColor,
                    } as CSSProperties;

                    return (
                      <span className={styles.nodeSlot} key={node.task?.job_id ?? index}>
                        <span
                          className={`${styles.node} ${nodeClass(node.status)}`}
                          style={nodeStyle}
                          title={title}
                          role="img"
                          aria-label={title}
                        >
                          {nodeSymbol(node.status)}
                        </span>
                        <small aria-hidden="true">
                          {String(index + 1).padStart(2, "0")}
                        </small>
                      </span>
                    );
                  })}
                </div>
              </div>
              <strong className={styles.providerTally}>
                {done} <small>/ {group.total}</small>
              </strong>
            </article>
          );
        })}
      </div>

      {isRunning || isQueued ? (
        <div className={`${styles.liveNotice} ${isQueued ? styles.queued : ""}`}>
          <i aria-hidden="true" />
          <div>
            <b>{isRunning ? "正在检测" : "等待采集服务"}</b>
            <small>
              {isRunning
                ? `${batch.running} 条任务正在请求模型并校验回答、来源与搜索证据`
                : "任务已写入队列，后台采集服务启动后会自动继续"}
            </small>
          </div>
        </div>
      ) : null}

      {isHistorical ? (
        <div className={`${styles.liveNotice} ${styles.queued}`}>
          <i aria-hidden="true" />
          <div>
            <b>历史批次仅保留记录</b>
            <small>本批次不具备恢复或再执行入口；只有当前页面新选择并点击开始的范围才会执行</small>
          </div>
        </div>
      ) : null}

      {pollError ? (
        <p className={styles.pollWarning}>
          {pollError}，系统会自动重试，不影响后台任务。
        </p>
      ) : null}

      <footer className={styles.footer}>
        <div>
          <span>
            {SETTLED.has(batch.status)
              ? "结果已归档 · 可逐条回看来源、搜索事件与原始证据"
              : isHistorical
                ? "历史批次只读保留 · 不会被 Worker 领取"
                : "观测正在后台执行 · 页面会自动刷新真实状态"}
          </span>
          <small>
            成功 {batch.succeeded} · 运行中 {batch.running} · 等待 {batch.pending} · 失败 {batch.failed}
          </small>
        </div>
        <Link
          href={`/geo/${workspaceId}/batches/${batch.batch_id}` as Route}
          aria-label={`查看批次 ${batch.batch_id} 任务矩阵`}
        >
          查看任务矩阵 <span aria-hidden="true">→</span>
        </Link>
      </footer>
    </section>
  );
}
