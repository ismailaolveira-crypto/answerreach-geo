"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { SimpleIcon } from "simple-icons";
import { siAlibabacloud, siBaidu, siCsdn, siGithub, siJuejin, siZhihu } from "simple-icons/icons";
import type { SourceMapItem } from "@/lib/cleanroom-v1-api";
import styles from "./source-map.module.css";

type View = "board" | "relations" | "list";
type Tier = SourceMapItem["tier"];

const INITIAL_TIER_ITEMS = 6;

const TIERS: Array<{ key: Tier; label: string; range: string; note: string }> = [
  { key: "core", label: "核心影响", range: "权重 70–100", note: "高频、跨模型、跨问题稳定出现" },
  { key: "high", label: "高价值", range: "权重 50–69", note: "覆盖稳定，值得持续经营" },
  { key: "growth", label: "成长机会", range: "权重 30–49", note: "已有信号，但覆盖面仍有限" },
  { key: "unverified", label: "待验证", range: "权重 0–29", note: "证据较少，暂不做强判断" },
];

const BRAND_ICONS: Record<string, SimpleIcon> = {
  zhihu: siZhihu,
  csdn: siCsdn,
  github: siGithub,
  juejin: siJuejin,
  aliyun: siAlibabacloud,
  baidu: siBaidu,
};

const SOURCE_NAMES: Array<[RegExp, string, string, string, string?]> = [
  [/zhuanlan\.zhihu\.com|zhihu\.com/, "知乎", "知识社区", "zhihu"],
  [/blog\.csdn\.net|csdn\.net/, "CSDN", "技术社区", "csdn"],
  [/51cto\.com/, "51CTO", "技术社区", "favicon", "https://www.51cto.com/favicon.ico"],
  [/juejin\.cn/, "掘金", "技术社区", "juejin"],
  [/segmentfault\.com/, "SegmentFault", "技术社区", "favicon", "https://segmentfault.com/favicon.ico"],
  [/github\.com/, "GitHub", "代码社区", "github"],
  [/cnblogs\.com/, "博客园", "技术社区", "favicon", "https://www.cnblogs.com/favicon.ico"],
  [/aliyun\.com/, "阿里云", "云厂商内容", "aliyun"],
  [/volcengine\.com/, "火山引擎", "云厂商内容", "favicon", "https://www.volcengine.com/favicon.ico"],
  [/tencent\.com/, "腾讯云", "云厂商内容", "favicon", "https://cloud.tencent.com/favicon.ico"],
  [/baidu\.com/, "百度智能云", "云厂商内容", "baidu"],
  [/microsoft\.com/, "Microsoft Learn", "官方文档", "favicon", "https://learn.microsoft.com/favicon.ico"],
  [/ibm\.com/, "IBM", "官方文档", "favicon", "https://www.ibm.com/favicon.ico"],
  [/ichunqiu\.com/, "春秋元泉官网", "自有阵地", "favicon", "https://icqtoken.ichunqiu.com/favicon.ico"],
];

function meta(source: SourceMapItem) {
  const found = SOURCE_NAMES.find(([pattern]) => pattern.test(source.label));
  if (found) return { name: found[1], category: found[2], icon: found[3], logoUrl: found[4] };
  return { name: source.label, category: "行业信源", icon: "website", logoUrl: undefined };
}

function SourceMark({ item }: { item: SourceMapItem }) {
  const [logoFailed, setLogoFailed] = useState(false);
  const source = meta(item);
  const icon = BRAND_ICONS[source.icon];
  if (icon) return <span className={styles.sourceMark} title={`${source.name} 官方品牌标识`}>
    <svg role="img" aria-label={`${source.name} 官方标识`} viewBox="0 0 24 24"><path fill={`#${icon.hex}`} d={icon.path} /></svg>
  </span>;
  if (source.logoUrl && !logoFailed) return <span className={styles.sourceMark} title={`${source.name} 官方网站标识`}>
    <img src={source.logoUrl} alt={`${source.name} 官方网站标识`} referrerPolicy="no-referrer" onError={() => setLogoFailed(true)} />
  </span>;
  return <span className={`${styles.sourceMark} ${styles.genericMark}`} title="网站信源">
    <svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" /><path d="M3.8 12h16.4M12 3.5c2.2 2.3 3.4 5.1 3.4 8.5S14.2 18.2 12 20.5M12 3.5C9.8 5.8 8.6 8.6 8.6 12s1.2 6.2 3.4 8.5" /></svg>
  </span>;
}

function EvidenceLink({ workspaceId, item }: { workspaceId: string; item: SourceMapItem }) {
  const reference = item.evidence_references[0];
  if (!reference) return <span className={styles.noEvidence}>暂无证据入口</span>;
  return <Link className={styles.evidenceAction} href={`/geo/${workspaceId}/evidence/${reference.evidence_id}?source=${encodeURIComponent(reference.source_url)}`}>
    查看证据 <span aria-hidden="true">→</span>
  </Link>;
}

function SourceCard({
  workspaceId,
  item,
  selected,
  related,
  onSelect,
}: {
  workspaceId: string;
  item: SourceMapItem;
  selected: boolean;
  related: boolean;
  onSelect: (key: string) => void;
}) {
  const source = meta(item);
  return <article className={`${styles.sourceCard} ${styles[`tier_${item.tier}`]}${selected ? ` ${styles.selected}` : ""}${related ? ` ${styles.related}` : ""}`}>
    <button type="button" className={styles.cardSelect} onClick={() => onSelect(item.key)} aria-pressed={selected} aria-label={`聚焦 ${source.name}`}>
      <SourceMark item={item} />
      <span className={styles.sourceIdentity}><b>{source.name}</b><small>{source.category} · {item.label}</small></span>
      <span className={styles.score}><b>{item.influence_score}</b><small>{item.tier_label}</small></span>
    </button>

    <dl className={styles.cardMetrics}>
      <div><dt>引用</dt><dd>{item.citation_count}</dd></div>
      <div><dt>回答</dt><dd>{item.answer_count}</dd></div>
      <div><dt>模型</dt><dd>{item.model_count}</dd></div>
      <div><dt>问题</dt><dd>{item.question_count}</dd></div>
    </dl>
    <div className={styles.scoreTrack}><i style={{ width: `${item.influence_score}%` }} /></div>

    <div className={styles.relationships}>
      <span>主要关系</span>
      <div>{item.related_sources.slice(0, 2).map((relation) => <button type="button" key={relation.key} onClick={() => onSelect(relation.key)} title={`共同出现在 ${relation.shared_answer_count} 条回答`}>
        {meta({ ...item, label: relation.label }).name} · {relation.strength === "strong" ? "强" : relation.strength === "medium" ? "中" : "弱"}
      </button>)}</div>
      <small>{item.related_sources[0] ? `最高共同出现 ${item.related_sources[0].shared_answer_count} 条回答` : "暂无稳定共同引用关系"}</small>
    </div>

    <footer>
      <span className={item.brand_absent_answer_count ? styles.gap : styles.quietGap}>
        {item.brand_absent_answer_count ? `◉ ${item.brand_absent_answer_count} 条回答未出现品牌` : "当前回答均已识别品牌"}
      </span>
      <EvidenceLink workspaceId={workspaceId} item={item} />
    </footer>

    <details className={styles.scoreDetail}>
      <summary>为什么是 {item.influence_score} 分 <span aria-hidden="true">⌄</span></summary>
      <p>{item.classification_reason}</p>
      <dl>
        <div><dt>引用频率</dt><dd>{item.score_factors.citation_frequency}/35</dd></div>
        <div><dt>回答覆盖</dt><dd>{item.score_factors.answer_reach}/25</dd></div>
        <div><dt>模型覆盖</dt><dd>{item.score_factors.model_breadth}/20</dd></div>
        <div><dt>问题覆盖</dt><dd>{item.score_factors.question_breadth}/20</dd></div>
      </dl>
    </details>
  </article>;
}

export function SourceBoard({
  workspaceId,
  items,
  topSourceKey,
}: {
  workspaceId: string;
  items: SourceMapItem[];
  topSourceKey: string | null;
}) {
  const [view, setView] = useState<View>("board");
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(topSourceKey);
  const [expandedTiers, setExpandedTiers] = useState<Set<Tier>>(() => new Set());
  const selected = items.find((item) => item.key === selectedKey) ?? null;
  const relatedKeys = useMemo(() => new Set(selected?.related_sources.map((item) => item.key) ?? []), [selected]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("zh-CN");
    if (!needle) return items;
    return items.filter((item) => `${meta(item).name} ${item.label}`.toLocaleLowerCase("zh-CN").includes(needle));
  }, [items, query]);

  const select = (key: string) => {
    const clearing = selectedKey === key;
    setSelectedKey(clearing ? null : key);
    if (clearing) return;
    const target = items.find((item) => item.key === key);
    if (!target) return;
    setExpandedTiers((current) => {
      if (current.has(target.tier)) return current;
      const next = new Set(current);
      next.add(target.tier);
      return next;
    });
  };

  const toggleTier = (tier: Tier) => setExpandedTiers((current) => {
    const next = new Set(current);
    if (next.has(tier)) next.delete(tier);
    else next.add(tier);
    return next;
  });

  return <section className={styles.boardShell}>
    <header className={styles.boardControls}>
      <label className={styles.search}><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索信源" aria-label="搜索信源" /></label>
      <nav aria-label="信源视图">
        {(["board", "relations", "list"] as View[]).map((key) => <button type="button" key={key} className={view === key ? styles.activeView : undefined} onClick={() => setView(key)}>
          {key === "board" ? "看板" : key === "relations" ? "关系" : "列表"}
        </button>)}
      </nav>
    </header>

    {selected ? <div className={styles.focusBar}>
      <span aria-hidden="true">◎</span><b>正在聚焦：{meta(selected).name}</b>
      <p>强关系 {selected.related_sources.filter((item) => item.strength === "strong").length} · 中关系 {selected.related_sources.filter((item) => item.strength === "medium").length}</p>
      <div>{selected.related_sources.slice(0, 3).map((relation) => <button type="button" key={relation.key} onClick={() => select(relation.key)}>{meta({ ...selected, label: relation.label }).name}</button>)}</div>
      <button type="button" className={styles.clearFocus} onClick={() => setSelectedKey(null)}>清除聚焦</button>
    </div> : <div className={styles.focusBar}><span aria-hidden="true">◎</span><b>关系聚焦</b><p>点击任意信源卡片，只看与它共同被引用的信源。</p></div>}

    {view === "board" ? <div className={styles.board}>
      {TIERS.map((tier, tierIndex) => {
        const tierItems = filtered.filter((item) => item.tier === tier.key);
        const expanded = expandedTiers.has(tier.key);
        const visibleItems = query.trim() || expanded ? tierItems : tierItems.slice(0, INITIAL_TIER_ITEMS);
        const hiddenCount = tierItems.length - visibleItems.length;
        return <section className={`${styles.boardColumn} ${styles[`column_${tier.key}`]}`} key={tier.key}>
          <header>
            <div className={styles.tierHeading}><span>{String(tierIndex + 1).padStart(2, "0")}</span><div><h2>{tier.label}</h2><p>{tier.range}</p></div></div>
            <b>{tierItems.length}</b>
            <small>{tier.note}</small>
          </header>
          <div className={styles.cardStack}>
            {visibleItems.map((item) => <SourceCard
              workspaceId={workspaceId}
              item={item}
              key={item.key}
              selected={selectedKey === item.key}
              related={relatedKeys.has(item.key)}
              onSelect={select}
            />)}
            {!tierItems.length ? <p className={styles.emptyTier}>当前筛选没有这一档信源</p> : null}
          </div>
          {!query.trim() && tierItems.length > INITIAL_TIER_ITEMS ? <button
            type="button"
            className={styles.tierToggle}
            aria-expanded={expanded}
            onClick={() => toggleTier(tier.key)}
          >{expanded ? "收起这一层" : `展开其余 ${hiddenCount} 个`} <span aria-hidden="true">{expanded ? "↑" : "↓"}</span></button> : null}
        </section>;
      })}
    </div> : null}

    {view === "relations" ? <div className={styles.relationView}>
      <section>
        <p>当前中心信源</p>
        <h2>{selected ? meta(selected).name : "请先选择一个信源"}</h2>
        <span>{selected ? `${selected.influence_score} 分 · ${selected.tier_label}` : "看板中点击卡片即可聚焦"}</span>
        {selected ? <div className={styles.centerScore}><i style={{ width: `${selected.influence_score}%` }} /></div> : null}
      </section>
      <div className={styles.relationList}>
        {selected?.related_sources.length ? selected.related_sources.map((relation, index) => <button type="button" key={relation.key} onClick={() => select(relation.key)}>
          <span>{String(index + 1).padStart(2, "0")}</span>
          <div><b>{meta({ ...selected, label: relation.label }).name}</b><small>{relation.label}</small></div>
          <dl><div><dt>共同回答</dt><dd>{relation.shared_answer_count}</dd></div><div><dt>模型</dt><dd>{relation.shared_model_count}</dd></div><div><dt>问题</dt><dd>{relation.shared_question_count}</dd></div></dl>
          <em className={styles[`relation_${relation.strength}`]}>{relation.strength === "strong" ? "强关系" : relation.strength === "medium" ? "中关系" : "弱关系"}</em>
          <i aria-hidden="true">→</i>
        </button>) : <p className={styles.noRelations}>当前信源还没有可稳定判断的共同引用关系。</p>}
      </div>
    </div> : null}

    {view === "list" ? <div className={styles.listView}>
      <table><thead><tr><th>信源</th><th>档位</th><th>权重</th><th>引用</th><th>回答</th><th>模型</th><th>问题</th><th>品牌缺席</th><th>证据</th></tr></thead>
        <tbody>{filtered.map((item) => <tr key={item.key}>
          <td><button type="button" onClick={() => select(item.key)}><SourceMark item={item} /><span><b>{meta(item).name}</b><small>{item.label}</small></span></button></td>
          <td><span className={`${styles.listTier} ${styles[`listTier_${item.tier}`]}`}>{item.tier_label}</span></td>
          <td><b>{item.influence_score}</b></td><td>{item.citation_count}</td><td>{item.answer_count}</td><td>{item.model_count}</td><td>{item.question_count}</td><td>{item.brand_absent_answer_count}</td>
          <td><EvidenceLink workspaceId={workspaceId} item={item} /></td>
        </tr>)}</tbody>
      </table>
    </div> : null}

  </section>;
}
