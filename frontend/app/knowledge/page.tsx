"use client";

// Knowledge (2026-11-05) — the PersonalWebsite's /knowledge page, inside the
// HUD: every note under the KB's Knowledge/ tree as a card grid with a
// dynamic filter bar (topics = the folder tree, tags = frontmatter tags +
// graph-linked hubs, both derived by GET /knowledge at request time).
// Reading view is `?n=<folder>/<slug>` (static-export friendly, no dynamic
// route). Owner surface: private notes are listed with a lock badge.

import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { GraduationCap } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/ui/Panel";
import { FilterBar, type KnowledgeSort } from "@/components/knowledge/FilterBar";
import { NoteCard } from "@/components/knowledge/NoteCard";
import { NoteReader } from "@/components/knowledge/NoteReader";
import { getKnowledge, noteParam, splitNoteParam, type KnowledgeIndex, type KnowledgeNoteRow } from "@/lib/knowledgeApi";

export default function KnowledgePage() {
  return (
    <Suspense>
      <KnowledgeInner />
    </Suspense>
  );
}

function KnowledgeInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const open = splitNoteParam(searchParams.get("n") ?? "");

  const [index, setIndex] = useState<KnowledgeIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [topic, setTopic] = useState(searchParams.get("topic") ?? "");
  const [tag, setTag] = useState(searchParams.get("tag") ?? "");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<string[] | null>(null); // ranked ids for q
  const [sort, setSort] = useState<KnowledgeSort>("recent");

  useEffect(() => {
    getKnowledge()
      .then(setIndex)
      .catch((e) => setError(String(e)));
  }, []);

  // Server-side search (retrieval index restricted to knowledge/ + substring
  // fallback), debounced; topic/tag narrowing stays client-side.
  useEffect(() => {
    const query = q.trim();
    if (!query) return;
    let live = true;
    const t = setTimeout(() => {
      getKnowledge({ q: query })
        .then((r) => live && setHits(r.notes.map((n) => n.id)))
        .catch(() => live && setHits([]));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [q]);

  const notes = useMemo(() => {
    if (!index) return [];
    let list = index.notes;
    if (topic) list = list.filter((n) => n.topic === topic || n.topic.startsWith(`${topic}/`));
    if (tag) {
      const want = tag.toLowerCase();
      list = list.filter((n) => n.tags.some((t) => t.toLowerCase() === want) || n.hubs.some((h) => h.label.toLowerCase() === want));
    }
    if (q.trim() && hits) {
      const order = new Map(hits.map((id, i) => [id, i]));
      return list.filter((n) => order.has(n.id)).sort((a, b) => order.get(a.id)! - order.get(b.id)!);
    }
    if (sort === "az") return [...list].sort((a, b) => a.title.localeCompare(b.title));
    if (sort === "topic") return [...list].sort((a, b) => a.topic_label.localeCompare(b.topic_label) || a.title.localeCompare(b.title));
    return list; // server order: edited desc
  }, [index, topic, tag, q, hits, sort]);

  function openNote(folder: string, slug: string) {
    router.push(`${pathname}?n=${encodeURIComponent(noteParam(folder, slug))}`);
    window.scrollTo({ top: 0 });
  }
  function closeNote() {
    router.push(pathname);
  }
  function pickTopic(t: string) {
    setTopic(t);
    if (open) closeNote();
  }

  if (open) {
    return (
      <div className="mx-auto max-w-3xl">
        <NoteReader folder={open.folder} slug={open.slug} onBack={closeNote} onTopic={pickTopic} onOpen={openNote} />
      </div>
    );
  }

  const groups: [string, KnowledgeNoteRow[]][] = [];
  if (sort === "topic" && !q.trim()) {
    for (const n of notes) {
      const key = n.topic_label || "General";
      const last = groups[groups.length - 1];
      if (last && last[0] === key) last[1].push(n);
      else groups.push([key, [n]]);
    }
  }

  const grid = (list: KnowledgeNoteRow[]) => (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {list.map((n) => (
        <NoteCard key={n.id} note={n} onOpen={() => openNote(n.folder, n.slug)} onTopic={setTopic} />
      ))}
    </div>
  );

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <PageHeader
        title="Knowledge"
        icon={GraduationCap}
        subtitle={index?.charter || "Things learned — lectures, tech notes, research, whatever comes next — written up so they can be found again."}
      />
      {error && <EmptyState>Couldn&apos;t load knowledge notes. {error}</EmptyState>}
      {index && (
        <>
          <FilterBar
            topics={index.topics}
            tags={index.tags}
            total={index.total}
            topic={topic}
            tag={tag}
            q={q}
            sort={sort}
            onTopic={setTopic}
            onTag={setTag}
            onQ={(v) => {
              setQ(v);
              if (!v.trim()) setHits(null);
            }}
            onSort={setSort}
          />
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
            {q.trim() && hits === null ? "searching…" : `${notes.length} of ${index.total} notes`}
          </p>
          {notes.length === 0 ? (
            <EmptyState icon={GraduationCap}>
              {index.total === 0 ? "No knowledge notes yet — drop something into Knowledge/ and it shows up here." : "Nothing matches these filters."}
            </EmptyState>
          ) : groups.length > 0 ? (
            <div className="space-y-6">
              {groups.map(([label, list]) => (
                <section key={label} className="space-y-2">
                  <h2 className="border-b border-line pb-1 font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
                    {label} <span className="text-muted">· {list.length}</span>
                  </h2>
                  {grid(list)}
                </section>
              ))}
            </div>
          ) : (
            grid(notes)
          )}
        </>
      )}
    </div>
  );
}
