"use client";

import { useState } from "react";
import { ChevronRight, FolderGit2, MapPin, Search, X } from "lucide-react";
import { Input } from "@/components/ui/Field";
import { Segmented } from "@/components/ui/Segmented";
import { cn } from "@/lib/cn";
import type { KnowledgeTag, KnowledgeTopic } from "@/lib/knowledgeApi";

export type KnowledgeSort = "recent" | "az" | "topic";

const TAG_PREVIEW = 14;

function Chip({ active, onClick, children, title }: { active: boolean; onClick: () => void; children: React.ReactNode; title?: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors",
        active ? "border-accent/60 bg-accent/15 text-accent shadow-glow" : "border-line text-muted hover:border-accent/40 hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}

const Count = ({ n }: { n: number }) => <span className="font-mono text-[10px] opacity-70">{n}</span>;

/** The topic path from the root to `topic` (each a KnowledgeTopic). */
export function topicChain(topics: KnowledgeTopic[], topic: string): KnowledgeTopic[] {
  const chain: KnowledgeTopic[] = [];
  let level = topics;
  const parts = topic ? topic.split("/") : [];
  for (let i = 0; i < parts.length; i++) {
    const want = parts.slice(0, i + 1).join("/");
    const hit = level.find((t) => t.topic === want);
    if (!hit) break;
    chain.push(hit);
    level = hit.children;
  }
  return chain;
}

// Dynamic filter bar: topic chips come from the folder tree the backend
// derived this request (drill into nested folders), tag chips from
// frontmatter tags + graph-linked hubs. Nothing here is a fixed list.
export function FilterBar({
  topics,
  tags,
  total,
  topic,
  tag,
  q,
  sort,
  onTopic,
  onTag,
  onQ,
  onSort,
}: {
  topics: KnowledgeTopic[];
  tags: KnowledgeTag[];
  total: number;
  topic: string;
  tag: string;
  q: string;
  sort: KnowledgeSort;
  onTopic: (t: string) => void;
  onTag: (t: string) => void;
  onQ: (q: string) => void;
  onSort: (s: KnowledgeSort) => void;
}) {
  const [allTags, setAllTags] = useState(false);
  const chain = topicChain(topics, topic);
  const deepest = chain[chain.length - 1];
  const childLevel = deepest ? deepest.children : [];
  const shownTags = allTags ? tags : tags.slice(0, TAG_PREVIEW);

  return (
    <div className="space-y-3 rounded-xl border border-line bg-surface/80 p-3 shadow-panel">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 basis-56">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <Input value={q} onChange={(e) => onQ(e.target.value)} placeholder="Search knowledge…" className="pl-8 pr-8" aria-label="Search knowledge" />
          {q && (
            <button onClick={() => onQ("")} aria-label="Clear search" className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted hover:text-foreground">
              <X size={13} />
            </button>
          )}
        </div>
        <Segmented<KnowledgeSort>
          value={sort}
          onChange={onSort}
          options={[
            { value: "recent", label: "Recent" },
            { value: "az", label: "A–Z" },
            { value: "topic", label: "By topic" },
          ]}
        />
      </div>

      <div>
        <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Topics</p>
        <div className="flex flex-wrap gap-1.5">
          <Chip active={!topic} onClick={() => onTopic("")}>
            All <Count n={total} />
          </Chip>
          {topics.map((t) => (
            <Chip key={t.topic} active={chain[0]?.topic === t.topic} onClick={() => onTopic(chain[0]?.topic === t.topic && chain.length === 1 ? "" : t.topic)} title={t.description || t.label}>
              {t.name} <Count n={t.count} />
            </Chip>
          ))}
        </div>
        {chain.length > 0 && (childLevel.length > 0 || chain.length > 1) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 border-l-2 border-accent/30 pl-2">
            {chain.map((c, i) => (
              <span key={c.topic} className="inline-flex items-center gap-1 text-xs">
                {i > 0 && <ChevronRight size={12} className="text-muted" />}
                <button onClick={() => onTopic(c.topic)} className={cn("hover:underline", i === chain.length - 1 ? "text-accent" : "text-muted")}>
                  {c.name}
                </button>
              </span>
            ))}
            {childLevel.map((c) => (
              <Chip key={c.topic} active={false} onClick={() => onTopic(c.topic)} title={c.description || c.label}>
                <ChevronRight size={11} /> {c.name} <Count n={c.count} />
              </Chip>
            ))}
          </div>
        )}
        {deepest?.description && <p className="mt-2 text-xs text-muted">{deepest.description}</p>}
      </div>

      {tags.length > 0 && (
        <div>
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Tags</p>
          <div className="flex flex-wrap gap-1.5">
            {shownTags.map((t) => (
              <Chip key={`${t.kind}:${t.tag}`} active={tag.toLowerCase() === t.tag.toLowerCase()} onClick={() => onTag(tag.toLowerCase() === t.tag.toLowerCase() ? "" : t.tag)}>
                {t.kind === "place" ? <MapPin size={11} /> : t.kind === "project" ? <FolderGit2 size={11} /> : <span className="opacity-60">#</span>}
                {t.tag} <Count n={t.count} />
              </Chip>
            ))}
            {tags.length > TAG_PREVIEW && (
              <button onClick={() => setAllTags(!allTags)} className="px-1 text-xs text-accent hover:underline">
                {allTags ? "fewer" : `+${tags.length - TAG_PREVIEW} more`}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
