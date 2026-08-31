"use client";

import { useMemo, useState } from "react";
import { SubmitButton } from "@/app/(app)/submit-button";

type ProviderOption = {
  id: number;
  name: string;
  provider_type: string;
  cost_rule?: Record<string, unknown>;
  collection_ready?: boolean;
};

type QuestionOption = {
  id: number;
  question_text: string;
};

type KeywordOption = {
  id: number;
  keyword: string;
};

type Props = {
  action: (formData: FormData) => void | Promise<void>;
  providers: ProviderOption[];
  questions: QuestionOption[];
  keywords: KeywordOption[];
};

const ESTIMATED_COMPLETION_TOKENS_PER_CALL = 900;

function estimateTokens(text: string) {
  return Math.max(1, Math.round(text.length / 2));
}

function numberValue(value: unknown) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatCost(value: number, currency: string) {
  if (value <= 0) return "未配置成本";
  return `${currency} ${value.toFixed(value < 0.01 ? 6 : 4)}`;
}

export function CrawlLaunchForm({ action, providers, questions, keywords }: Props) {
  const [providerId, setProviderId] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [keywordId, setKeywordId] = useState("");

  const estimate = useMemo(() => {
    const selectedProvider = providers.find((provider) => String(provider.id) === providerId);
    const realProviderCount = selectedProvider && selectedProvider.provider_type !== "mock" ? 1 : 0;
    const hasExplicitScope = Boolean(questionId || keywordId);
    const selectedQuestions = hasExplicitScope
      ? questionId
        ? questions.filter((question) => String(question.id) === questionId)
        : []
      : questions;
    const selectedKeywords = hasExplicitScope
      ? keywordId
        ? keywords.filter((keyword) => String(keyword.id) === keywordId)
        : []
      : keywords;
    const keywordPromptTexts = selectedKeywords.flatMap((keyword) => [
      `${keyword.keyword}相关服务商怎么选？`,
      `企业服务领域里，${keyword.keyword}有哪些值得关注的解决方案或服务商？`,
      `企业在采购${keyword.keyword}服务时，应该重点比较哪些能力和案例？`
    ]);
    const promptTexts = [...selectedQuestions.map((question) => question.question_text), ...keywordPromptTexts];
    const questionCount = selectedQuestions.length;
    const keywordCount = selectedKeywords.length;
    const keywordPromptCount = keywordPromptTexts.length;
    const promptCount = promptTexts.length;
    const providerCount = 1;
    const promptTokens = promptTexts.reduce((sum, prompt) => sum + estimateTokens(prompt), 0);
    const completionTokens = promptCount * ESTIMATED_COMPLETION_TOKENS_PER_CALL;
    const totalTokens = promptTokens + completionTokens;
    const costRule = selectedProvider?.cost_rule ?? {};
    const currency = String(costRule.currency ?? "USD");
    const inputPer1k = numberValue(costRule.input_per_1k);
    const outputPer1k = numberValue(costRule.output_per_1k);
    const estimatedCost = promptTokens / 1000 * inputPer1k + completionTokens / 1000 * outputPer1k;
    const costConfigured = inputPer1k > 0 || outputPer1k > 0;
    const warnings: string[] = [];

    if (!hasExplicitScope && promptCount > 0) {
      warnings.push("未选择问题或关键词时会跑完整项目范围。");
    }
    if (hasExplicitScope && questionId && !keywordId) {
      warnings.push("只跑已选问题，不会顺带跑全部关键词。");
    }
    if (hasExplicitScope && keywordId && !questionId) {
      warnings.push("只跑已选关键词，不会顺带跑全部问题。");
    }
    if (realProviderCount > 0) {
      warnings.push("已选择真实模型渠道，会产生实际 API 调用。");
      if (!costConfigured) {
        warnings.push("该真实模型渠道未配置输入/输出单价，预计成本会按 0 展示。");
      }
    }
    if (promptCount * providerCount >= 20) {
      warnings.push("调用量较高，建议先抽样验证。");
    }

    return {
      providerName: selectedProvider?.name ?? "默认 Mock GEO Search",
      realProviderCount,
      questionCount,
      keywordCount,
      keywordPromptCount,
      promptCount,
      totalCallCount: promptCount * providerCount,
      promptTokens,
      completionTokens,
      totalTokens,
      estimatedCost,
      currency,
      costConfigured,
      warnings
    };
  }, [keywordId, keywords, providerId, providers, questionId, questions]);

  return (
    <form action={action} className="crawl-launch-form">
      <div className="inline-form crawl-launch-controls">
        {providers.length > 0 ? (
          <select
            name="provider_ids"
            aria-label="采集渠道"
            value={providerId}
            onChange={(event) => setProviderId(event.target.value)}
          >
            <option value="">默认 Mock 渠道</option>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name}
                {provider.provider_type !== "mock"
                  ? provider.collection_ready
                    ? "｜真实可采集"
                    : "｜需先测试"
                  : "｜Mock"}
              </option>
            ))}
          </select>
        ) : null}
        {questions.length > 0 ? (
          <select
            name="target_question_ids"
            aria-label="目标问题"
            value={questionId}
            onChange={(event) => setQuestionId(event.target.value)}
          >
            <option value="">{keywordId ? "不选问题" : "全部问题"}</option>
            {questions.map((question) => (
              <option key={question.id} value={question.id}>
                {question.question_text}
              </option>
            ))}
          </select>
        ) : null}
        {keywords.length > 0 ? (
          <select
            name="keyword_ids"
            aria-label="关键词"
            value={keywordId}
            onChange={(event) => setKeywordId(event.target.value)}
          >
            <option value="">{questionId ? "不选关键词" : "全部关键词"}</option>
            {keywords.map((keyword) => (
              <option key={keyword.id} value={keyword.id}>
                {keyword.keyword}
              </option>
            ))}
          </select>
        ) : null}
        <input
          name="max_estimated_cost"
          type="number"
          min="0"
          step="0.000001"
          placeholder="单次预算上限"
          aria-label="单次预算上限"
        />
        <SubmitButton pendingText="采集中...">发起搜索采集</SubmitButton>
      </div>
      <div className={estimate.realProviderCount > 0 ? "crawl-estimate paid" : "crawl-estimate"}>
        <span>预计 {estimate.totalCallCount} 次模型调用</span>
        <span>预计 {estimate.totalTokens.toLocaleString("zh-CN")} tokens</span>
        <span>预计成本 {formatCost(estimate.estimatedCost, estimate.currency)}</span>
        <span>
          {estimate.questionCount} 个问题 / {estimate.keywordCount} 个关键词
        </span>
        {estimate.keywordCount > 0 ? <span>关键词扩展 {estimate.keywordPromptCount} 个问题变体</span> : null}
        <span>{estimate.providerName}</span>
      </div>
      {estimate.warnings.length > 0 ? (
        <div className="mini-list crawl-estimate-warnings">
          {estimate.warnings.map((warning) => (
            <small key={warning}>{warning}</small>
          ))}
        </div>
      ) : null}
    </form>
  );
}
