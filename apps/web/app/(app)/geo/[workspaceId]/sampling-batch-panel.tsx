"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { SubmitButton } from "@/app/(app)/submit-button";
import { BrandLogo } from "@/components/brand-logo";
import type { CleanroomEvidence, CleanroomQuestion, QueueWorkerStatus } from "@/lib/cleanroom-v1-api";
import styles from "./sampling-batch-panel.module.css";

const MAX_MODELS = 5;
const MAX_QUESTIONS = 10;
const MAX_REPEATS = 100;

export type ObservationProvider = {
  key: string;
  label: string;
  status: "ready" | "needs_key" | "unverified" | "coming_soon";
  statusLabel: string;
  providerId?: number | null;
};

type QuestionOption = { value: string; text: string; editable: boolean };

export type ObservationSelectionSnapshot = {
  batchId: number;
  providerIds: number[];
  questions: Array<{ id: number; text: string }>;
  repeatCount: number;
};

export default function SamplingBatchPanel({
  workspaceId, questions, providers, workerStatus, lastEvidence, initialSelection, runAction, updateQuestionAction,
}: {
  workspaceId: string;
  questions: CleanroomQuestion[];
  providers: ObservationProvider[];
  workerStatus: QueueWorkerStatus | null;
  lastEvidence?: CleanroomEvidence | null;
  initialSelection?: ObservationSelectionSnapshot;
  runAction: (formData: FormData) => Promise<void>;
  updateQuestionAction: (questionId: number, questionText: string) => Promise<{ ok: boolean; error?: string }>;
}) {
  const router = useRouter();
  const [isEditing, startEditing] = useTransition();
  const recommendedQuestions = useMemo<QuestionOption[]>(() => {
    const items = (initialSelection?.questions ?? []).map((question) => ({
      value: String(question.id), text: question.text, editable: true,
    }));
    for (const question of questions) {
      if (!items.some((item) => item.value === String(question.id))) {
        items.push({ value: String(question.id), text: question.question_text, editable: true });
      }
    }
    const fallbacks = [
      "企业级大模型治理平台怎么选？",
      "Token 统一管控平台哪家好？",
      "国内有哪些支持私有化部署的平台？",
      "如何统一管理多模型 API 密钥和成本？",
      "企业选择 AI 安全治理平台要看哪些能力？",
    ];
    for (const text of fallbacks) {
      if (items.length >= MAX_QUESTIONS) break;
      if (!items.some((item) => item.text === text)) {
        items.push({ value: `suggested:${items.length + 1}`, text, editable: false });
      }
    }
    return items;
  }, [initialSelection, questions]);
  const readyProviders = providers.filter((item) => item.status === "ready" && item.providerId);
  const [selectedProviderIds, setSelectedProviderIds] = useState<number[]>(() => [
    ...new Set((initialSelection?.providerIds ?? []).filter((id) => id > 0)),
  ].slice(0, MAX_MODELS));
  const [selectedQuestionValues, setSelectedQuestionValues] = useState<string[]>(() => [
    ...new Set((initialSelection?.questions ?? []).map((question) => String(question.id))),
  ].slice(0, MAX_QUESTIONS));
  const [customQuestion, setCustomQuestion] = useState("");
  const [customQuestionOpen, setCustomQuestionOpen] = useState(false);
  const [repeatCount, setRepeatCount] = useState(() => Math.min(MAX_REPEATS, Math.max(1, initialSelection?.repeatCount ?? 5)));
  const [editingQuestion, setEditingQuestion] = useState<QuestionOption | null>(null);
  const [editingText, setEditingText] = useState("");
  const [editError, setEditError] = useState("");
  const selectedQuestions = recommendedQuestions.filter((item) => selectedQuestionValues.includes(item.value));
  const customCandidate = customQuestion.trim().length >= 4;
  const customIncluded = customCandidate && selectedQuestions.length < MAX_QUESTIONS;
  const questionCount = Math.min(MAX_QUESTIONS, selectedQuestions.length + (customIncluded ? 1 : 0));
  const totalTasks = selectedProviderIds.length * questionCount * repeatCount;
  const sourceCount = lastEvidence?.source_items.length ?? 0;
  const selectedProviders = providers.filter((item) => item.providerId && selectedProviderIds.includes(item.providerId));

  useEffect(() => {
    if (workerStatus?.online) return;
    const timer = window.setInterval(() => router.refresh(), 15_000);
    return () => window.clearInterval(timer);
  }, [router, workerStatus?.online]);

  function toggleProvider(provider: ObservationProvider) {
    if (!provider.providerId) return;
    setSelectedProviderIds((current) => {
      if (current.includes(provider.providerId!)) return current.filter((id) => id !== provider.providerId);
      if (provider.status !== "ready" || current.length >= MAX_MODELS) return current;
      return [...current, provider.providerId!];
    });
  }

  function toggleQuestion(value: string) {
    setSelectedQuestionValues((current) => current.includes(value)
      ? current.filter((item) => item !== value)
      : current.length + (customIncluded ? 1 : 0) < MAX_QUESTIONS ? [...current, value] : current);
  }

  function saveQuestion() {
    if (!editingQuestion?.editable || editingText.trim().length < 4) {
      setEditError("常用问题至少需要 4 个字");
      return;
    }
    const questionId = Number(editingQuestion.value);
    startEditing(async () => {
      const result = await updateQuestionAction(questionId, editingText.trim());
      if (!result.ok) {
        setEditError(result.error || "保存失败");
        return;
      }
      setEditingQuestion(null);
      setEditError("");
      router.refresh();
    });
  }

  return <section className={styles.composer}>
    <header className={styles.heading}>
      <div>
        <span className={styles.eyebrow}>模型观测中心</span>
        <h2>创建一次真实联网观测</h2>
        <p>选择模型、问题与次数，任务数量会实时更新。</p>
      </div>
      <Link className={styles.channelLink} href={`/admin/providers?workspace=${workspaceId}` as Route}>模型与渠道 <span aria-hidden="true">↗</span></Link>
    </header>

    <form action={runAction} className={styles.form}>
      <input type="hidden" name="provider_ids" value={JSON.stringify(selectedProviderIds)} />
      <input type="hidden" name="selected_questions" value={JSON.stringify(selectedQuestions)} />
      <input type="hidden" name="repeat_count" value={repeatCount} />

      <div className={styles.builder}>
        <div className={styles.configuration}>
          <section className={styles.step}>
            <header className={styles.stepHeading}>
              <span className={styles.stepNumber}>1</span>
              <h3>选择观测模型</h3>
              <small>已选 {selectedProviderIds.length} / {MAX_MODELS}</small>
            </header>
            <div className={styles.modelSelection}>
              {selectedProviders.map((provider) => <div className={styles.modelChip} key={provider.key}>
                <BrandLogo brand={provider.key} label={provider.label} />
                <span>{provider.label}</span>
                <button type="button" aria-label={`移除${provider.label}`} onClick={() => toggleProvider(provider)}>×</button>
              </div>)}
              <details className={styles.picker}>
                <summary><span aria-hidden="true">＋</span> 选择模型</summary>
                <div className={styles.pickerMenu}>
                  <header><span>{readyProviders.length} 个模型当前可用</span><button type="button" onClick={() => setSelectedProviderIds(readyProviders.slice(0, MAX_MODELS).map((item) => item.providerId!))}>全选可用</button></header>
                  {providers.map((provider) => {
                    const selected = Boolean(provider.providerId && selectedProviderIds.includes(provider.providerId));
                    const selectable = provider.status === "ready" && Boolean(provider.providerId);
                    return <button type="button" className={selected ? styles.selectedMenuItem : ""} onClick={() => toggleProvider(provider)} disabled={!selectable} key={provider.key}>
                      <BrandLogo brand={provider.key} label={provider.label} />
                      <span><b>{provider.label}</b><small>{provider.statusLabel}</small></span>
                      <i>{selected ? "✓" : selectable ? "" : "需配置"}</i>
                    </button>;
                  })}
                </div>
              </details>
            </div>
            <p className={styles.helpText}>最多可选 {MAX_MODELS} 个模型，任务会对每个已选模型分别观测。</p>
          </section>

          <section className={styles.step}>
            <header className={styles.stepHeading}>
              <span className={styles.stepNumber}>2</span>
              <h3>选择观测问题</h3>
              <small>已选 {questionCount} / {MAX_QUESTIONS}</small>
            </header>
            <div className={styles.selectedQuestions}>
              {selectedQuestions.length ? selectedQuestions.map((question) => <div className={styles.selectedQuestion} key={question.value}>
                <span>{question.text}</span>
                <button type="button" aria-label={`移除问题：${question.text}`} onClick={() => toggleQuestion(question.value)}>×</button>
              </div>) : <p className={styles.emptySelection}>尚未选择常用问题</p>}
            </div>

            {customQuestionOpen ? <div className={styles.customQuestion}>
              <label htmlFor="observation-custom-question">临时问题 <small>可选</small></label>
              <div><input id="observation-custom-question" name="custom_question" value={customQuestion} placeholder="输入本次临时观测的问题" onChange={(event) => setCustomQuestion(event.target.value)} autoFocus /><button type="button" aria-label="移除临时问题" onClick={() => { setCustomQuestion(""); setCustomQuestionOpen(false); }}>×</button></div>
              {customQuestion && !customCandidate ? <p>临时问题至少输入 4 个字</p> : null}
              {customCandidate && !customIncluded ? <p>本批次最多 {MAX_QUESTIONS} 个问题，请先取消一个常用问题</p> : null}
            </div> : <input type="hidden" name="custom_question" value="" />}

            <div className={styles.questionActions}>
              <details className={`${styles.picker} ${styles.questionPicker}`}>
                <summary><span aria-hidden="true">＋</span> 选择常用问题</summary>
                <div className={`${styles.pickerMenu} ${styles.questionMenu}`}>
                  <header><span>常用问题库</span><button type="button" onClick={() => setSelectedQuestionValues(recommendedQuestions.slice(0, customIncluded ? MAX_QUESTIONS - 1 : MAX_QUESTIONS).map((item) => item.value))}>全选</button></header>
                  {recommendedQuestions.map((question) => {
                    const selected = selectedQuestionValues.includes(question.value);
                    return <div className={`${styles.questionOption} ${selected ? styles.selectedOption : ""}`} key={question.value}>
                      <button type="button" className={styles.questionToggle} onClick={() => toggleQuestion(question.value)}><i>{selected ? "✓" : ""}</i><span>{question.text}</span></button>
                      {question.editable ? <button type="button" className={styles.questionEdit} aria-label={`编辑：${question.text}`} onClick={() => { setEditingQuestion(question); setEditingText(question.text); setEditError(""); }}>编辑</button> : null}
                    </div>;
                  })}
                </div>
              </details>
              <button type="button" className={styles.secondaryAction} onClick={() => setCustomQuestionOpen(true)} disabled={customQuestionOpen}><span aria-hidden="true">＋</span> 添加临时问题</button>
            </div>
          </section>

          <section className={`${styles.step} ${styles.repeatStep}`}>
            <header className={styles.stepHeading}>
              <span className={styles.stepNumber}>3</span>
              <h3>每题运行次数</h3>
            </header>
            <div className={styles.repeatRow}>
              <div className={styles.stepper} aria-label="每题运行次数">
                <button type="button" aria-label="减少运行次数" onClick={() => setRepeatCount((value) => Math.max(1, value - 1))} disabled={repeatCount === 1}>−</button>
                <label><input aria-label="每题运行次数" type="number" min={1} max={MAX_REPEATS} value={repeatCount} onChange={(event) => setRepeatCount(Math.min(MAX_REPEATS, Math.max(1, Number(event.target.value) || 1)))} /><small>次</small></label>
                <button type="button" aria-label="增加运行次数" onClick={() => setRepeatCount((value) => Math.min(MAX_REPEATS, value + 1))} disabled={repeatCount === MAX_REPEATS}>＋</button>
              </div>
              <p>每个模型对每个问题独立运行指定次数。</p>
            </div>
          </section>
        </div>

        <aside className={styles.receipt} data-ready={totalTasks > 0} aria-live="polite" aria-atomic="true">
          <span className={styles.receiptLabel}>本次观测任务</span>
          <div className={styles.total}>
            <strong key={totalTasks}>{totalTasks}</strong>
            <span>条真实观测</span>
          </div>
          <p className={styles.equation}>{selectedProviderIds.length} 个模型 <i>×</i> {questionCount} 个问题 <i>×</i> {repeatCount} 次</p>
          <div className={styles.spectralRail} aria-hidden="true"><span /><span /><span /><span /><span /></div>
          <div className={`${styles.workerGate} ${workerStatus?.online ? styles.workerOnline : styles.workerOffline}`} data-worker-online={workerStatus?.online ? "true" : "false"}>
            <i aria-hidden="true" />
            <span><b>{workerStatus?.online ? "采集服务在线" : "采集服务离线"}</b><small>{workerStatus?.online ? `${workerStatus.worker_count} 个进程 · 可并发 ${workerStatus.concurrency} 条` : "当前不会创建任务，恢复后页面会自动更新"}</small></span>
            {!workerStatus?.online ? <button type="button" onClick={() => router.refresh()}>立即检查</button> : null}
          </div>
          <SubmitButton className={styles.submit} pendingText="正在提交真实任务…" disabled={!selectedProviderIds.length || !questionCount || !workerStatus?.online}>
            {!workerStatus?.online ? "等待采集服务上线" : totalTasks ? `提交 ${totalTasks} 条真实观测` : "请先选择模型和问题"}
          </SubmitButton>
          <p className={styles.backgroundNote}>{workerStatus?.online ? totalTasks > 125 ? `大批量任务会按当前 ${workerStatus.concurrency} 条并发分批执行，不会同时请求 ${totalTasks} 次` : "提交后先进入队列；采集服务领取后才显示运行中" : "任务不会丢失或假装运行；请先恢复当前仓库采集服务"}</p>
          <div className={styles.lastEvidence} data-has-evidence={Boolean(lastEvidence)}><span aria-hidden="true">{lastEvidence ? "✓" : "·"}</span><p>{lastEvidence ? `上次观测成功 · ${lastEvidence.model_label} · ${sourceCount} 个来源` : "等待第一条通过联网门禁的真实证据"}</p></div>
        </aside>
      </div>
    </form>

    {editingQuestion ? <div className="sy-question-editor" role="dialog" aria-modal="true" aria-labelledby="question-editor-title">
      <div>
        <header><div><small>常用问题</small><h3 id="question-editor-title">编辑问题</h3></div><button type="button" aria-label="关闭" onClick={() => setEditingQuestion(null)}>×</button></header>
        <textarea value={editingText} onChange={(event) => setEditingText(event.target.value)} autoFocus />
        {editError ? <p>{editError}</p> : null}
        <footer><button type="button" onClick={() => setEditingQuestion(null)}>取消</button><button type="button" className="is-primary" onClick={saveQuestion} disabled={isEditing}>{isEditing ? "保存中…" : "保存常用问题"}</button></footer>
      </div>
    </div> : null}

  </section>;
}
