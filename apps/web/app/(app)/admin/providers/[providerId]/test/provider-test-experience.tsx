"use client";

import { getProviderTestJobAction, queueProviderTestAction } from "@/app/actions";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

type InitialTest = {
  ok: boolean;
  latencyMs?: number | null;
  createdAt?: string | null;
  error?: string | null;
};

type Props = {
  providerId: string;
  promptText: string;
  disabled: boolean;
  initialTest?: InitialTest | null;
};

type TestState = "idle" | "queueing" | "pending" | "running" | "success" | "failed";

function readableError(value: string) {
  const text = value.replace(/^API request failed:\s*/i, "");
  if (/401|unauthorized|authentication|invalid.*key/i.test(text)) return "API Key 无效或已失效，请更换后重试。";
  if (/balance|arrearage|quota|余额|欠费/i.test(text)) return "账户余额或免费额度不足，请在模型控制台确认。";
  if (/timeout|timed out|超时/i.test(text)) return "模型联网搜索超时，可以稍后重新测试。";
  if (/tool.*not.*open|未开通|not enabled/i.test(text)) return "该模型的联网搜索能力尚未开通。";
  return text.slice(0, 220) || "渠道测试未通过，请检查配置后重试。";
}

export function ProviderTestExperience({ providerId, promptText, disabled, initialTest }: Props) {
  const router = useRouter();
  const [isStarting, startTransition] = useTransition();
  const [jobId, setJobId] = useState<number | null>(null);
  const [state, setState] = useState<TestState>("idle");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!startedAt || !["queueing", "pending", "running"].includes(state)) return;
    const timer = window.setInterval(() => setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000))), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt, state]);

  useEffect(() => {
    if (!jobId || !["pending", "running"].includes(state)) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const job = await getProviderTestJobAction(providerId, jobId);
        if (cancelled) return;
        if (job.status === "pending") {
          setState("pending");
        } else if (job.status === "running") {
          setState("running");
        } else if (job.status === "success") {
          const ok = job.payload_json.test_ok === true;
          setLatencyMs(typeof job.payload_json.latency_ms === "number" ? job.payload_json.latency_ms : null);
          setError(ok ? null : readableError(String(job.payload_json.error_message ?? "")));
          setState(ok ? "success" : "failed");
          router.refresh();
          return;
        } else if (job.status === "failed") {
          setError(readableError(job.error_message ?? "渠道测试任务执行失败。"));
          setState("failed");
          router.refresh();
          return;
        }
      } catch (pollError) {
        if (cancelled) return;
        setError(readableError(pollError instanceof Error ? pollError.message : String(pollError)));
        setState("failed");
        return;
      }
      timer = window.setTimeout(poll, 1500);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId, providerId, router, state]);

  const startTest = () => {
    setState("queueing");
    setStartedAt(Date.now());
    setElapsed(0);
    setLatencyMs(null);
    setError(null);
    startTransition(async () => {
      try {
        const job = await queueProviderTestAction(providerId, promptText);
        setJobId(job.id);
        setState(job.status === "running" ? "running" : "pending");
      } catch (startError) {
        setError(readableError(startError instanceof Error ? startError.message : String(startError)));
        setState("failed");
      }
    });
  };

  const active = isStarting || ["queueing", "pending", "running"].includes(state);
  const title = state === "queueing"
    ? "正在创建测试任务"
    : state === "pending"
      ? "已进入队列，等待执行"
      : state === "running"
        ? "正在执行真实联网搜索"
        : state === "success"
          ? "联网渠道验证成功"
          : state === "failed"
            ? "渠道测试未通过"
            : initialTest?.ok
              ? "最近一次测试成功"
              : initialTest
                ? "最近一次测试未通过"
                : "尚未进行渠道测试";
  const detail = active
    ? "页面可以继续使用或离开；完成后状态会自动更新。"
    : state === "success"
      ? `已验证鉴权、模型回答、联网搜索和引用来源${latencyMs ? `，耗时 ${(latencyMs / 1000).toFixed(1)} 秒` : ""}。`
      : state === "failed"
        ? error ?? "请检查配置后重新测试。"
        : initialTest?.ok
          ? `最近测试已通过${initialTest.latencyMs ? `，耗时 ${(initialTest.latencyMs / 1000).toFixed(1)} 秒` : ""}。`
          : initialTest?.error
            ? readableError(initialTest.error)
            : "保存 API Key 后，主动发起一次真实联网验证。";

  return <section className={`sy-channel-test-card sy-channel-test-experience is-${state}`} aria-live="polite">
    <div className="sy-test-copy">
      <span>2</span>
      <div>
        <h2>测试渠道</h2>
        <p>验证鉴权、模型回答、联网搜索事件与引用来源。测试不会阻塞配置页面。</p>
        <div className="sy-test-live-state">
          <i aria-hidden="true" />
          <div><b>{title}</b><small>{detail}</small></div>
        </div>
        {active ? <div className="sy-test-progress" aria-label="渠道测试进行中"><span /></div> : null}
      </div>
    </div>
    <div className="sy-test-actions">
      {active ? <small>已用时 {elapsed} 秒</small> : null}
      <button className="sy-channel-test-button" type="button" disabled={disabled || active} onClick={startTest}>
        {active ? "后台测试中…" : state === "failed" || initialTest ? "重新测试" : "开始测试"}
      </button>
    </div>
  </section>;
}
