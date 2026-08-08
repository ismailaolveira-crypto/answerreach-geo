"use client";

import Link from "next/link";
import { Fragment, useState } from "react";
import { DetailsCollapseButton } from "@/components/details-collapse-button";
import type {
  CleanroomCompetitorComparison,
  CompetitorBrandStat,
  CompetitorEvidenceSnippet,
} from "@/lib/cleanroom-v1-api";
import styles from "./competitor-comparison.module.css";

type ActionDiagnostic = CleanroomCompetitorComparison["action_diagnostics"][number];

type SignalGroup = {
  signalCount: number;
  questionIds: Set<number>;
  modelKeys: Set<string>;
  items: ActionDiagnostic[];
};

function formatNumber(value: number) {
  return value.toLocaleString("zh-CN");
}

function explicitPositionLabel(brand: CompetitorBrandStat) {
  return brand.explicit_average_position == null ? "—" : String(brand.explicit_average_position);
}

function evidenceLabel(row: CompetitorEvidenceSnippet) {
  if (row.win_reason_type === "explicit_rank_ahead") return "明确排序在前";
  if (row.win_reason_type === "selected_baseline_absent") return "竞品入选、我们缺席";
  if (row.status === "recommended") return "明确推荐";
  if (row.status === "shortlisted") return "进入候选";
  if (row.status === "negative") return "负面语境";
  return "普通提及";
}

function cleanEvidenceExcerpt(value?: string) {
  if (!value) return "原回答中已命中该品牌，查看原回答与关联引用。";
  const cleaned = value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/#{1,6}/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/[>*_`~|]/g, " ")
    .replace(/-{2,}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > 180 ? `${cleaned.slice(0, 180)}…` : cleaned;
}

function EvidenceDisclosure({ workspaceId, rows }: { workspaceId: string; rows: CompetitorEvidenceSnippet[] }) {
  if (!rows.length) return <span className={styles.zeroEvidence}>真实 0</span>;
  return <details className={styles.evidenceDisclosure}>
    <summary>查看 {Math.min(rows.length, 8)} 条对应证据</summary>
    <div>{rows.slice(0, 8).map((row) => <article key={`${row.brand_key}-${row.evidence_id}`}>
      <header><b>{row.model_label}</b><span>{evidenceLabel(row)}</span></header>
      <dl><div><dt>对应问题</dt><dd>{row.question}</dd></div><div><dt>命中摘要</dt><dd>{cleanEvidenceExcerpt(row.context_snippet)}</dd></div></dl>
      <Link href={`/geo/${workspaceId}/evidence/${row.evidence_id}`}>查看原回答和关联引用 <span aria-hidden="true">↗</span></Link>
    </article>)}<DetailsCollapseButton label="收起对应证据" /></div>
  </details>;
}

function buildSignalGroups(items: ActionDiagnostic[]) {
  return items.reduce((groups, item) => {
    const group = groups.get(item.competitor_key) ?? {
      signalCount: 0,
      questionIds: new Set<number>(),
      modelKeys: new Set<string>(),
      items: [],
    } satisfies SignalGroup;
    group.signalCount += item.wins_over_baseline;
    group.questionIds.add(item.question_plan_id);
    group.modelKeys.add(item.model_key);
    group.items.push(item);
    groups.set(item.competitor_key, group);
    return groups;
  }, new Map<string, SignalGroup>());
}

function SignalDrawer({ workspaceId, brand, group }: { workspaceId: string; brand: CompetitorBrandStat; group: SignalGroup }) {
  return <div className={styles.rankingSignalDrawer} aria-label={`${brand.canonical_name} 对比信号详情`}>
    <header>
      <span>对比信号 · {group.signalCount}</span>
      <div><h3>{brand.canonical_name} 在 {group.questionIds.size} 个问题中出现需要复核的比较</h3><p>只展示同一回答内可回看的真实对比，不代表整体胜率。</p></div>
    </header>
    <div className={styles.signalTimeline}>
      {group.items.map((item) => {
        const signedGap = item.mention_gap > 0 ? `+${item.mention_gap}` : String(item.mention_gap);
        const evidence = item.evidence[0];
        return <article key={`${item.competitor_key}-${item.model_key}-${item.question_plan_id}`}>
          <div className={styles.signalTimelineHead}><b>{item.model_label}</b><span>{item.reason_label}</span></div>
          <dl>
            <div><dt>对应问题</dt><dd>{item.question}</dd></div>
            <div><dt>量化差值</dt><dd>竞品 {item.competitor_hit_count} 次，春秋元泉 {item.baseline_hit_count} 次，差值 {signedGap}。</dd></div>
            <div><dt>原回答摘要</dt><dd>{evidence ? cleanEvidenceExcerpt(evidence.context_snippet) : "该信号没有可展示的单条证据摘要。"}</dd></div>
          </dl>
          {evidence ? <Link href={`/geo/${workspaceId}/evidence/${evidence.evidence_id}`}>查看原回答和关联引用 <span aria-hidden="true">↗</span></Link> : null}
        </article>;
      })}
    </div>
  </div>;
}

export function CompetitorRanking({
  workspaceId,
  brands,
  actionDiagnostics = [],
}: {
  workspaceId: string;
  brands: CompetitorBrandStat[];
  actionDiagnostics?: ActionDiagnostic[];
}) {
  const [openBrandKey, setOpenBrandKey] = useState<string | null>(null);
  const baseline = brands.find((brand) => brand.is_baseline);
  const competitors = brands.filter((brand) => !brand.is_baseline).sort((left, right) =>
    right.mention_rate - left.mention_rate
    || right.hit_answer_count - left.hit_answer_count
    || right.wins_over_baseline - left.wins_over_baseline
    || left.canonical_name.localeCompare(right.canonical_name, "zh-CN"));
  const rows = baseline ? [baseline, ...competitors] : competitors;
  const signalGroups = buildSignalGroups(actionDiagnostics);

  function toggleSignal(brandKey: string) {
    setOpenBrandKey((current) => current === brandKey ? null : brandKey);
  }

  return <>
    <div className={styles.tableWrap}>
      <table className={styles.rankingTable}>
        <thead><tr><th>排名</th><th>竞品</th><th>出现率</th><th>对比信号</th><th>Top 3</th><th>平均位置</th><th>覆盖模型</th><th>证据</th></tr></thead>
        <tbody>{rows.map((brand) => {
          const rank = brand.is_baseline ? "我" : competitors.indexOf(brand) + 1;
          const signalGroup = signalGroups.get(brand.key);
          const isOpen = openBrandKey === brand.key;
          return <Fragment key={brand.key}>
            <tr data-baseline={brand.is_baseline || undefined} data-signal-open={isOpen || undefined}>
              <td><i className={styles.rankNumber}>{rank}</i></td>
              <th><b>{brand.canonical_name}</b><small>{brand.is_baseline ? "基准品牌" : `固定追踪 · ${brand.hit_answer_count} 条`}</small></th>
              <td><strong>{brand.mention_rate}%</strong><small>{brand.hit_answer_count}/{brand.sample_answer_count} 条回答</small></td>
              <td>{brand.is_baseline ? <><strong>—</strong><small>作为比较基准</small></> : signalGroup ? <button type="button" className={styles.signalTrigger} onClick={() => toggleSignal(brand.key)} aria-expanded={isOpen} aria-controls={`signal-drawer-${brand.key}`}><strong>{formatNumber(signalGroup.signalCount)} 次</strong><small>{signalGroup.questionIds.size} 问题 · 点击回看 <i aria-hidden="true">⌄</i></small></button> : <><strong>0 次</strong><small>{brand.comparable_answers} 条可比较</small></>}</td>
              <td>{brand.top3_rate}%</td>
              <td>{explicitPositionLabel(brand)}<small>{brand.explicit_rank_observation_count} 条有排名</small></td>
              <td>{brand.model_count}</td>
              <td><EvidenceDisclosure workspaceId={workspaceId} rows={brand.evidence} /></td>
            </tr>
            {signalGroup && isOpen ? <tr className={styles.rankingSignalRow}><td colSpan={8}><div id={`signal-drawer-${brand.key}`}><SignalDrawer workspaceId={workspaceId} brand={brand} group={signalGroup} /></div></td></tr> : null}
          </Fragment>;
        })}</tbody>
      </table>
    </div>

    <div className={styles.mobileRanking} aria-label="竞品真实回答排行榜">
      {rows.map((brand) => {
        const rank = brand.is_baseline ? "我" : competitors.indexOf(brand) + 1;
        const signalGroup = signalGroups.get(brand.key);
        const isOpen = openBrandKey === brand.key;
        return <article key={brand.key} data-baseline={brand.is_baseline || undefined}>
          <header><i className={styles.rankNumber}>{rank}</i><span><b>{brand.canonical_name}</b><small>{brand.is_baseline ? "基准品牌（我们）" : "固定追踪竞品"}</small></span><strong>{brand.mention_rate}%<small>{brand.hit_answer_count}/{brand.sample_answer_count} 条</small></strong></header>
          <dl><div><dt>对比信号</dt><dd>{brand.is_baseline ? "—" : signalGroup ? <button type="button" className={styles.signalTrigger} onClick={() => toggleSignal(brand.key)} aria-expanded={isOpen}>{signalGroup.signalCount} 次 <i aria-hidden="true">⌄</i></button> : "0 次"}</dd></div><div><dt>Top 3</dt><dd>{brand.top3_rate}%</dd></div><div><dt>平均位置</dt><dd>{explicitPositionLabel(brand)}</dd></div><div><dt>覆盖</dt><dd>{brand.model_count} 模型</dd></div></dl>
          {signalGroup && isOpen ? <SignalDrawer workspaceId={workspaceId} brand={brand} group={signalGroup} /> : null}
          <EvidenceDisclosure workspaceId={workspaceId} rows={brand.evidence} />
        </article>;
      })}
    </div>
  </>;
}
