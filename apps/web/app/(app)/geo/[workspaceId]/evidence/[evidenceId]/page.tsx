import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { BrandLogo } from "@/components/brand-logo";
import { DetailsCollapseButton } from "@/components/details-collapse-button";
import { getCleanroomDecisionMap, getCleanroomEvidence, type CleanroomEvidence } from "@/lib/cleanroom-v1-api";

type Props = {
  params: Promise<{ workspaceId: string; evidenceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const STATUS: Record<string, { label: string; tone: string; icon: string }> = {
  absent: { label: "未出现", tone: "quiet", icon: "×" }, mentioned: { label: "提及", tone: "blue", icon: "◌" }, shortlisted: { label: "候选", tone: "green", icon: "○" }, recommended: { label: "推荐", tone: "orange", icon: "♧" }, cited: { label: "引用", tone: "violet", icon: "✦" }, negative: { label: "负面", tone: "red", icon: "!" },
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function sourceUrl(source: Record<string, unknown>) {
  if (typeof source.url !== "string") return null;
  try {
    const url = new URL(source.url);
    url.hash = "";
    return url.toString();
  } catch {
    return source.url;
  }
}

function sourceIdentity(value: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value.includes("://") ? value : `https://${value}`);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    url.hash = "";
    url.hostname = url.hostname.replace(/^www\./, "").toLowerCase();
    if ((url.protocol === "http:" && url.port === "80") || (url.protocol === "https:" && url.port === "443")) url.port = "";
    url.pathname = url.pathname === "/" ? "/" : url.pathname.replace(/\/+$/, "") || "/";
    const query = Array.from(url.searchParams.entries()).sort(([leftKey, leftValue], [rightKey, rightValue]) => leftKey.localeCompare(rightKey) || leftValue.localeCompare(rightValue));
    url.search = "";
    for (const [key, sourceValue] of query) url.searchParams.append(key, sourceValue);
    return url.toString();
  } catch {
    return null;
  }
}

function uniqueSources(sample: CleanroomEvidence) {
  return Array.from(new Map(sample.source_items.map((source) => [sourceIdentity(sourceUrl(source)) ?? JSON.stringify(source), source])).values());
}

function plainText(value: string) {
  return value
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```\w*\n?|```/g, ""))
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[`*_~]/g, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function tableCells(value: string) {
  return value.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => plainText(cell.trim()));
}

function isTableRow(value: string) {
  return value.includes("|") && tableCells(value).length > 1;
}

function isTableDivider(value: string) {
  return isTableRow(value) && tableCells(value).every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, "")));
}

function readableAnswer(value: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  const flushParagraph = () => {
    if (paragraph.length) {
      nodes.push(<p key={`p-${nodes.length}`}>{plainText(paragraph.join(" "))}</p>);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      nodes.push(<ul key={`l-${nodes.length}`}>{list.map((item, index) => <li key={`${index}-${item.slice(0, 24)}`}>{plainText(item)}</li>)}</ul>);
      list = [];
    }
  };

  const lines = value.replace(/\r\n/g, "\n").split("\n");
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const rawLine = lines[lineIndex];
    const line = rawLine.trim();
    if (!line || /^[-*_]{3,}$/.test(line)) {
      flushParagraph();
      flushList();
      continue;
    }
    if (isTableRow(line) && isTableDivider(lines[lineIndex + 1]?.trim() ?? "")) {
      flushParagraph();
      flushList();
      const headers = tableCells(line);
      const rows: string[][] = [];
      lineIndex += 2;
      while (lineIndex < lines.length && isTableRow(lines[lineIndex].trim())) {
        const row = lines[lineIndex].trim();
        if (!isTableDivider(row)) {
          const cells = tableCells(row);
          rows.push(headers.map((_, columnIndex) => cells[columnIndex] ?? ""));
        }
        lineIndex += 1;
      }
      nodes.push(<div className="sy-answer-table-wrap" key={`table-${nodes.length}`}><table className="sy-answer-table"><thead><tr>{headers.map((header, index) => <th key={`${index}-${header}`}>{header || "—"}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={`row-${rowIndex}`}>{row.map((cell, columnIndex) => <td key={`${rowIndex}-${columnIndex}`}>{cell || "—"}</td>)}</tr>)}</tbody></table></div>);
      lineIndex -= 1;
      continue;
    }
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    const bullet = line.match(/^(?:[-*+]\s+|\d+[.)]\s+)(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      nodes.push(<h3 key={`h-${nodes.length}`}>{plainText(heading[1])}</h3>);
      continue;
    }
    if (bullet) {
      flushParagraph();
      list.push(bullet[1]);
      continue;
    }
    flushList();
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  return nodes.length ? nodes : [<p key="empty">暂无可展示的回答内容。</p>];
}

function displayDomain(value: string) {
  return value.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/$/, "");
}

function collectionMethodLabel(value: string) {
  if (value === "web_ui") return "网页端真实采样";
  if (value === "official_api_web_search") return "官方 API · 联网搜索";
  if (value === "aggregate_api_web_search") return "聚合 API · 联网搜索";
  return value;
}

function EvidenceSampleCard({ sample, fallbackIndex, focusedSource }: { sample: CleanroomEvidence; fallbackIndex: number; focusedSource?: string | null }) {
  const allSources = uniqueSources(sample);
  const focusedSources = focusedSource
    ? allSources.filter((source) => sourceIdentity(sourceUrl(source)) === focusedSource)
    : [];
  const sources = focusedSources.length ? focusedSources : allSources;
  const isSourceFocused = focusedSources.length > 0;
  const answerLength = sample.answer_text.replace(/\s/g, "").length;
  const storedRepeatIndex = Number(sample.sampling_environment.repeat_index);
  const repeatIndex = Number.isFinite(storedRepeatIndex) && storedRepeatIndex > 0 ? storedRepeatIndex : fallbackIndex;
  const sampleStatus = STATUS[sample.brand_status] ?? STATUS.absent;
  const sourceSection = <section className="sy-proof-section sy-citation-section"><header><span className="is-link">↗</span><div><b>{isSourceFocused ? "当前引用信源" : "引用来源"}</b><small>{isSourceFocused ? "该信源与下方这张原回答一一绑定，可直接打开核验。" : `${allSources.length} 个与第 ${repeatIndex} 次回答同时归档的独立来源`}</small></div></header><div className={`sy-source-grid${isSourceFocused ? " is-source-focused" : ""}`}>{sources.length ? sources.map((source, index) => { const url = sourceUrl(source); let inferredDomain = "未识别来源"; try { if (url) inferredDomain = new URL(url).hostname; } catch {} const domain = typeof source.domain === "string" ? source.domain : typeof source.source === "string" ? source.source : inferredDomain; const rawTitle = typeof source.title === "string" ? source.title.trim() : ""; const title = rawTitle && !/^[\s\-–—·#\d.]+$/.test(rawTitle) ? rawTitle : domain; const shownDomain = displayDomain(domain); return <a key={url ?? `${title}-${index}`} className={isSourceFocused ? "is-source-focus" : undefined} href={url ?? undefined} target={url ? "_blank" : undefined} rel="noreferrer"><span className="sy-source-mark"><b>{String(index + 1).padStart(2, "0")}</b></span><div><b>{title}</b><small>{shownDomain}</small>{isSourceFocused ? <em className="sy-source-focus-tag">信源地图所选</em> : null}</div><i aria-label="在新窗口打开">↗</i></a>; }) : <p>该回答没有可解析的引用来源。</p>}</div></section>;

  return <details className="sy-proof-disclosure" open={isSourceFocused}>
    <summary><span className="sy-proof-icon"><b>{String(repeatIndex).padStart(2, "0")}</b></span><span className="sy-proof-copy"><b>第 {repeatIndex} 次回答 <i>·</i> {sample.model_label}</b><small><span>{answerLength.toLocaleString("zh-CN")} 字</span><i>·</i><span>{allSources.length} 个来源</span><i>·</i><span>完整归档</span></small></span><span className={`sy-sample-status is-${sampleStatus.tone}`}>{sampleStatus.label}</span><em>{isSourceFocused ? "查看对应信源" : "查看完整证据"}</em><i>⌄</i></summary>
    <div className="sy-proof-body">
      <div className="sy-sample-meta"><span>观测时间 <b>{formatDate(sample.captured_at)}</b></span><span>联网证据 <b>{sample.collection_method === "official_api_web_search" || sample.collection_method === "aggregate_api_web_search" ? "已归档" : "待核验"}</b></span><span>工件 <b>{sample.raw_artifact_uri || sample.screenshot_uri ? "完整" : "缺失"}</b></span></div>
      {isSourceFocused ? sourceSection : null}
      <section className="sy-proof-section"><header><span>Aa</span><div><b>{isSourceFocused ? "对应原回答" : "回答原文"}</b><small>{isSourceFocused ? "这张回答与上方所选信源同一次归档。" : "已清除 Markdown 标记，保留原回答的内容结构"}</small></div></header><article className="sy-answer-text">{readableAnswer(sample.answer_text)}</article></section>
      {!isSourceFocused ? sourceSection : null}
      <DetailsCollapseButton label="收起这次完整证据" />
    </div>
  </details>;
}

export default async function EvidenceDetail({ params, searchParams }: Props) {
  const { workspaceId, evidenceId } = await params;
  const query = await searchParams;
  const sourceQuery = Array.isArray(query.source) ? query.source[0] : query.source;
  const [map, evidenceRows] = await Promise.all([getCleanroomDecisionMap(workspaceId), getCleanroomEvidence(workspaceId)]);
  const evidence = evidenceRows.find((item) => item.id === Number(evidenceId));
  if (!evidence) notFound();
  const question = map.questions.find((item) => item.id === evidence.question_plan_id);
  const groupId = typeof evidence.sampling_environment.observation_group_id === "string"
    ? evidence.sampling_environment.observation_group_id
    : null;
  const sampleGroup = (groupId
    ? evidenceRows.filter((item) => item.sampling_environment.observation_group_id === groupId)
    : [evidence]
  ).sort((left, right) => {
    const leftIndex = Number(left.sampling_environment.repeat_index) || 1;
    const rightIndex = Number(right.sampling_environment.repeat_index) || 1;
    return leftIndex - rightIndex;
  });
  const focusedSource = sourceIdentity(sourceQuery ?? null);
  const hasFocusedSource = Boolean(focusedSource && uniqueSources(evidence).some((source) => sourceIdentity(sourceUrl(source)) === focusedSource));
  const displayedSamples = hasFocusedSource ? [evidence] : sampleGroup;
  const totalSources = displayedSamples.reduce((sum, item) => sum + item.source_items.length, 0);
  const archivedCount = displayedSamples.filter((item) => item.raw_artifact_uri || item.screenshot_uri).length;
  const focusedSourceRecord = hasFocusedSource ? uniqueSources(evidence).find((source) => sourceIdentity(sourceUrl(source)) === focusedSource) : undefined;
  const focusedSourceLabel = focusedSourceRecord ? displayDomain(sourceUrl(focusedSourceRecord) ?? "已锁定来源") : null;
  return <div className="sy-page"><header className="sy-topbar"><Link className="sy-brand" href={`/geo/${workspaceId}`}><img alt="" aria-hidden="true" src="/brand/answerreach-mark.svg" /><b>入答 AnswerReach</b></Link><Link className="sy-back" href={`/geo/${workspaceId}`}>← 返回决策地图</Link></header><main className="sy-detail-main">
    <div className="sy-detail-meta" aria-label="本组观测摘要">
      <article><span>最近成功观测</span><b>{formatDate(evidence.captured_at)}</b></article>
      <article><span>{hasFocusedSource ? "已锁定回答" : "本组样本"}</span><b>{hasFocusedSource ? "1 张原始回答卡" : `${sampleGroup.length} 次独立回答`}</b></article>
      <article><span>证据工件</span><b className={archivedCount === displayedSamples.length ? "is-good" : "is-warn"}>{archivedCount}/{displayedSamples.length} 完整</b></article>
    </div>
    <section className="sy-evidence-card sy-evidence-glass-card"><header><div className="sy-evidence-card-heading"><p>{hasFocusedSource ? "信源地图 · 单条引用核验" : "本轮证据 · 同一问题重复观测"}</p><h1>{question?.question_text ?? "已归档问题"}</h1></div><span className="sy-group-count"><b>{displayedSamples.length}</b> {hasFocusedSource ? "条回答" : "次观测"}</span></header><dl className="sy-evidence-facts"><div className="sy-evidence-fact"><dt>模型</dt><dd><BrandLogo brand={evidence.model_key} label={evidence.model_label} /><span>{evidence.model_label}</span></dd></div><div className="sy-evidence-fact"><dt>独立回答</dt><dd>{hasFocusedSource ? "当前引用对应回答" : `${sampleGroup.length} / ${Number(evidence.sampling_environment.repeat_count) || sampleGroup.length} 次`}</dd></div><div className="sy-evidence-fact"><dt>{hasFocusedSource ? "已锁定信源" : "采集方式"}</dt><dd>{hasFocusedSource ? focusedSourceLabel : collectionMethodLabel(evidence.collection_method)}</dd></div></dl><hr />
      <div className="sy-proof-stack">
        {displayedSamples.map((sample, index) => <EvidenceSampleCard key={sample.id} sample={sample} fallbackIndex={index + 1} focusedSource={hasFocusedSource ? focusedSource : null} />)}
      </div>
      <div className="sy-evidence-quality"><span>{hasFocusedSource ? "对应回答" : "本组回答"} <b>{displayedSamples.length} 次</b></span><span>{hasFocusedSource ? "已锁定信源" : "引用来源"} <b>{hasFocusedSource ? 1 : totalSources} 条</b></span><span>完整工件 <b>{archivedCount}/{displayedSamples.length}</b></span></div>
      <Link className="sy-primary sy-detail-action" href={`/geo/${workspaceId}/actions?evidence=${evidence.id}`}>创建优化行动</Link>
    </section>
  </main></div>;
}
