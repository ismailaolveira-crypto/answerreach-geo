"use client";

import { useMemo, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { SubmitButton } from "@/app/(app)/submit-button";
import { BrandLogo } from "@/components/brand-logo";
import type { CleanroomEvidence, CleanroomQuestion } from "@/lib/cleanroom-v1-api";

export type ObservationProvider = {
  key: string;
  label: string;
  status: "ready" | "needs_key" | "unverified" | "coming_soon";
  statusLabel: string;
  providerId?: number | null;
};

type QuestionOption = { value: string; text: string; editable: boolean };

export default function SamplingBatchPanel({
  workspaceId, questions, providers, lastEvidence, runAction, updateQuestionAction,
}: {
  workspaceId: string;
  questions: CleanroomQuestion[];
  providers: ObservationProvider[];
  lastEvidence?: CleanroomEvidence | null;
  runAction: (formData: FormData) => Promise<void>;
  updateQuestionAction: (questionId: number, questionText: string) => Promise<{ ok: boolean; error?: string }>;
}) {
  const router = useRouter();
  const [isEditing, startEditing] = useTransition();
  const recommendedQuestions = useMemo<QuestionOption[]>(() => {
    const items = questions.slice(0, 5).map((question) => ({
      value: String(question.id), text: question.question_text, editable: true,
    }));
    const fallbacks = [
      "企业级大模型治理平台怎么选？",
      "Token 统一管控平台哪家好？",
      "国内有哪些支持私有化部署的平台？",
      "如何统一管理多模型 API 密钥和成本？",
      "企业选择 AI 安全治理平台要看哪些能力？",
    ];
    for (const text of fallbacks) {
      if (items.length >= 5) break;
      if (!items.some((item) => item.text === text)) {
        items.push({ value: `suggested:${items.length + 1}`, text, editable: false });
      }
    }
    return items;
  }, [questions]);
  const readyProviders = providers.filter((item) => item.status === "ready" && item.providerId);
  const [selectedProviderIds, setSelectedProviderIds] = useState<number[]>([]);
  const [selectedQuestionValues, setSelectedQuestionValues] = useState<string[]>([]);
  const [customQuestion, setCustomQuestion] = useState("");
  const [repeatCount, setRepeatCount] = useState(5);
  const [editingQuestion, setEditingQuestion] = useState<QuestionOption | null>(null);
  const [editingText, setEditingText] = useState("");
  const [editError, setEditError] = useState("");
  const selectedQuestions = recommendedQuestions.filter((item) => selectedQuestionValues.includes(item.value));
  const customCandidate = customQuestion.trim().length >= 4;
  const customIncluded = customCandidate && selectedQuestions.length < 5;
  const questionCount = Math.min(5, selectedQuestions.length + (customIncluded ? 1 : 0));
  const totalTasks = selectedProviderIds.length * questionCount * repeatCount;
  const sourceCount = lastEvidence?.source_items.length ?? 0;
  const selectedProviderNames = readyProviders.filter((item) => selectedProviderIds.includes(item.providerId!)).map((item) => item.label);

  function toggleProvider(provider: ObservationProvider) {
    if (provider.status !== "ready" || !provider.providerId) return;
    setSelectedProviderIds((current) => current.includes(provider.providerId!)
      ? current.filter((id) => id !== provider.providerId)
      : current.length < 5 ? [...current, provider.providerId!] : current);
  }

  function toggleQuestion(value: string) {
    setSelectedQuestionValues((current) => current.includes(value)
      ? current.filter((item) => item !== value)
      : current.length + (customIncluded ? 1 : 0) < 5 ? [...current, value] : current);
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

  return <section className="sy-live-run sy-observation-composer" aria-live="polite">
    <header className="sy-observation-heading">
      <div className="sy-live-run-copy">
        <span>模型观测中心</span>
        <h2>组合一次真实联网观测</h2>
        <p>选择模型、问题与次数。提交前显示的数量，就是后台实际创建的任务矩阵。</p>
      </div>
      <Link className="sy-channel-manager-link" href="/admin/providers">模型与渠道 <span>→</span></Link>
    </header>

    <form action={runAction} className="sy-batch-form">
      <input type="hidden" name="provider_ids" value={JSON.stringify(selectedProviderIds)} />
      <input type="hidden" name="selected_questions" value={JSON.stringify(selectedQuestions)} />
      <input type="hidden" name="repeat_count" value={repeatCount} />

      <div className="sy-compact-pickers">
        <div className="sy-picker-field">
          <label>观测模型 <small>最多 5 个</small></label>
          <details className="sy-multi-select">
            <summary><span>{selectedProviderNames.length ? selectedProviderNames.join("、") : "选择已连接模型"}</span><b>{selectedProviderIds.length ? `${selectedProviderIds.length} 个` : "请选择"}</b></summary>
            <div className="sy-multi-menu">
              <header><span>{readyProviders.length} 个模型当前可用</span><button type="button" onClick={() => setSelectedProviderIds(readyProviders.slice(0, 5).map((item) => item.providerId!))}>全选可用</button></header>
              {providers.map((provider) => {
                const selected = Boolean(provider.providerId && selectedProviderIds.includes(provider.providerId));
                const selectable = provider.status === "ready" && Boolean(provider.providerId);
                return <button type="button" className={selected ? "is-selected" : ""} onClick={() => toggleProvider(provider)} disabled={!selectable} key={provider.key}>
                  <BrandLogo brand={provider.key} label={provider.label} />
                  <span><b>{provider.label}</b><small>{provider.statusLabel}</small></span>
                  <i>{selected ? "✓" : selectable ? "" : "需配置"}</i>
                </button>;
              })}
            </div>
          </details>
        </div>

        <div className="sy-picker-field">
          <label>常用问题 <small>可多选、可编辑</small></label>
          <details className="sy-multi-select">
            <summary><span>{selectedQuestions.length ? selectedQuestions.map((item) => item.text).join("、") : "选择常用问题"}</span><b>{selectedQuestions.length ? `${selectedQuestions.length} 个` : "请选择"}</b></summary>
            <div className="sy-multi-menu sy-question-menu">
              <header><span>常用问题库</span><button type="button" onClick={() => setSelectedQuestionValues(recommendedQuestions.slice(0, 5).map((item) => item.value))}>全选</button></header>
              {recommendedQuestions.map((question) => {
                const selected = selectedQuestionValues.includes(question.value);
                return <div className={`sy-question-option ${selected ? "is-selected" : ""}`} key={question.value}>
                  <button type="button" className="sy-question-toggle" onClick={() => toggleQuestion(question.value)}><i>{selected ? "✓" : ""}</i><span>{question.text}</span></button>
                  {question.editable ? <button type="button" className="sy-question-edit" aria-label={`编辑：${question.text}`} onClick={() => { setEditingQuestion(question); setEditingText(question.text); setEditError(""); }}>编辑</button> : null}
                </div>;
              })}
            </div>
          </details>
        </div>

        <label className="sy-picker-field sy-custom-question-compact">
          <span>临时问题 <small>可选</small></span>
          <input name="custom_question" value={customQuestion} placeholder="输入本次临时观测的问题" onChange={(event) => setCustomQuestion(event.target.value)} />
        </label>
      </div>

      {customQuestion && !customCandidate ? <p className="sy-inline-hint">临时问题至少输入 4 个字</p> : null}
      {customCandidate && !customIncluded ? <p className="sy-inline-hint">本批次最多 5 个问题，请先取消一个常用问题</p> : null}

      <div className="sy-batch-submit-row">
        <div className="sy-batch-equation" aria-label="任务数量">
          <span><b>{selectedProviderIds.length}</b> 个模型</span><i>×</i><span><b>{questionCount}</b> 个问题</span><i>×</i><span><b>{repeatCount}</b> 次</span><strong>= {totalTasks} 条真实观测</strong>
        </div>
        <label className="sy-repeat-control"><span>每题运行次数</span><span><button type="button" aria-label="减少运行次数" onClick={() => setRepeatCount((value) => Math.max(1, value - 1))}>−</button><b>{repeatCount}</b><button type="button" aria-label="增加运行次数" onClick={() => setRepeatCount((value) => Math.min(5, value + 1))}>＋</button></span></label>
        <SubmitButton className="sy-primary" pendingText="正在创建真实任务…" disabled={!selectedProviderIds.length || !questionCount}>开始 {totalTasks} 条观测</SubmitButton>
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

    <footer className="sy-observation-meta">
      <small>{lastEvidence ? `最近成功：${lastEvidence.model_label} · ${sourceCount} 个来源 · 原始工件已归档` : "等待第一条通过联网门禁的真实证据"}</small>
      <span>任务提交后可离开页面，后台会继续执行</span>
    </footer>
  </section>;
}
