"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, FolderOpen, Lightbulb, Lock, Pencil, Plus, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { Badge, EmptyState, PageHeader, Panel } from "@/components/ui/Panel";
import IdeaFiles, { IdeaMarkdown } from "@/components/business/IdeaFiles";
import { FileKindCounts, STATUS_LABEL, statusTone } from "@/components/business/fileKinds";
import { formatIsoDate } from "@/lib/date";
import {
  createIdea,
  getIdea,
  IDEA_STATUSES,
  listIdeas,
  updateIdeaFields,
  type IdeaCard,
  type IdeaDetail,
  type IdeaStatus,
} from "@/lib/businessApi";

// Board columns: Parked and Dropped share the last one.
const COLUMNS: { key: string; label: string; statuses: IdeaStatus[] }[] = [
  { key: "idea", label: "Idea", statuses: ["idea"] },
  { key: "exploring", label: "Exploring", statuses: ["exploring"] },
  { key: "validating", label: "Validating", statuses: ["validating"] },
  { key: "building", label: "Building", statuses: ["building"] },
  { key: "shelf", label: "Parked / Dropped", statuses: ["parked", "dropped"] },
];

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function parseTags(s: string): string[] {
  return s
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export default function BusinessPage() {
  return (
    <Suspense>
      <BusinessPageInner />
    </Suspense>
  );
}

function BusinessPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const slug = useSearchParams().get("i");

  const open = (s: string | null) => router.push(s ? `${pathname}?i=${encodeURIComponent(s)}` : pathname);

  return slug ? <IdeaDetailView key={slug} slug={slug} onBack={() => open(null)} /> : <Board onOpen={open} />;
}

function SortHint() {
  return (
    <p className="flex items-start gap-2 text-xs text-muted">
      <Sparkles size={13} className="mt-0.5 shrink-0 text-accent" />
      <span>
        Drop any file — decks, PDFs, sketches, spreadsheets, STLs, videos — with <span className="text-foreground">Sort with AI</span> and
        name the idea; it files into <span className="font-mono text-foreground">Business Ideas/&lt;Idea&gt;</span> and shows up here.
      </span>
    </p>
  );
}

function Board({ onOpen }: { onOpen: (slug: string) => void }) {
  const [ideas, setIdeas] = useState<IdeaCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  useEffect(() => {
    listIdeas()
      .then((r) => setIdeas(r.ideas))
      .catch((e) => {
        setIdeas([]);
        setError(errorText(e));
      });
  }, []);

  const byColumn = useMemo(() => {
    const m: Record<string, IdeaCard[]> = {};
    for (const c of COLUMNS) m[c.key] = (ideas ?? []).filter((i) => c.statuses.includes(i.status));
    return m;
  }, [ideas]);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <PageHeader
        title="Business Ideas"
        icon={Lightbulb}
        subtitle="Every idea, every file — notes, decks, sketches, models — in one place."
        actions={
          <Button variant={showNew ? "ghost" : "primary"} size="sm" onClick={() => setShowNew((v) => !v)}>
            <Plus size={14} /> {showNew ? "Close" : "New idea"}
          </Button>
        }
      />
      {showNew && <NewIdeaForm onCreated={(i) => onOpen(i.slug)} />}
      <SortHint />
      {error && <p className="break-words text-xs text-danger">{error}</p>}

      {ideas === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : ideas.length === 0 ? (
        <EmptyState icon={Lightbulb}>No ideas yet — start one with “New idea”, or drop files with Sort with AI.</EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5 lg:gap-3">
          {COLUMNS.map((c) => {
            const items = byColumn[c.key];
            return (
              <section key={c.key} className={items.length === 0 ? "hidden lg:block" : ""}>
                <h2 className="mb-2 flex items-center justify-between border-b border-line pb-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
                  {c.label}
                  <span className="text-muted">{items.length}</span>
                </h2>
                <div className="space-y-2">
                  {items.map((i) => (
                    <IdeaCardView key={i.slug} idea={i} onOpen={() => onOpen(i.slug)} />
                  ))}
                  {items.length === 0 && <p className="py-4 text-center font-mono text-[10px] text-muted/60">—</p>}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function IdeaCardView({ idea, onOpen }: { idea: IdeaCard; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="block w-full rounded-xl border border-line bg-surface/80 p-3 text-left shadow-panel transition-colors hover:border-accent/60"
    >
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1 break-words text-sm font-medium">{idea.title}</span>
        {idea.private && <Lock size={12} className="mt-0.5 shrink-0 text-warn" />}
      </div>
      {(idea.status === "parked" || idea.status === "dropped" || !idea.has_hub) && (
        <div className="mt-1 flex flex-wrap gap-1">
          {(idea.status === "parked" || idea.status === "dropped") && <Badge tone={statusTone(idea.status)}>{STATUS_LABEL[idea.status]}</Badge>}
          {!idea.has_hub && <Badge tone="muted">no hub note</Badge>}
        </div>
      )}
      {idea.summary && <p className="mt-1 line-clamp-3 break-words text-xs text-muted">{idea.summary}</p>}
      {idea.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {idea.tags.map((t) => (
            <span key={t} className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-muted">
              #{t}
            </span>
          ))}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <FileKindCounts counts={idea.file_counts} />
        {idea.last_edited && <span className="font-mono text-[10px] text-muted">{formatIsoDate(idea.last_edited)}</span>}
      </div>
    </button>
  );
}

function NewIdeaForm({ onCreated, initialTitle = "" }: { onCreated: (i: IdeaDetail) => void; initialTitle?: string }) {
  const [title, setTitle] = useState(initialTitle);
  const [summary, setSummary] = useState("");
  const [status, setStatus] = useState<IdeaStatus>("idea");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit() {
    const t = title.trim();
    if (!t) return;
    setBusy(true);
    setMessage(null);
    try {
      onCreated(await createIdea({ title: t, summary: summary.trim(), status, tags: parseTags(tags) }));
    } catch (e) {
      const msg = errorText(e);
      setMessage(/ 409 /.test(msg) ? `“${t}” already exists.` : msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={initialTitle ? "Create the hub note" : "New idea"} icon={Plus}>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Input placeholder="name (e.g. Solar Kiosk)" value={title} onChange={(e) => setTitle(e.target.value)} disabled={!!initialTitle} />
        <Input placeholder="one-line summary" value={summary} onChange={(e) => setSummary(e.target.value)} />
        <div className="flex flex-wrap gap-2">
          <Select value={status} onChange={(e) => setStatus(e.target.value as IdeaStatus)} className="w-auto">
            {IDEA_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </Select>
          <Input placeholder="tags, comma separated" value={tags} onChange={(e) => setTags(e.target.value)} className="w-auto min-w-0 flex-1" />
        </div>
        <div className="flex items-center gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={busy || !title.trim()}>
            {busy ? "Creating…" : "Create"}
          </Button>
          {message && <span className="break-words text-xs text-danger">{message}</span>}
        </div>
      </form>
    </Panel>
  );
}

function IdeaDetailView({ slug, onBack }: { slug: string; onBack: () => void }) {
  const [idea, setIdea] = useState<IdeaDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    getIdea(slug)
      .then(setIdea)
      .catch((e) => setError(errorText(e)));
  }, [slug]);

  async function save(update: Parameters<typeof updateIdeaFields>[1]) {
    setSaving(true);
    setError(null);
    try {
      setIdea(await updateIdeaFields(slug, update));
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setSaving(false);
    }
  }

  const back = (
    <button onClick={onBack} className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-accent">
      <ArrowLeft size={14} /> All ideas
    </button>
  );

  if (!idea) {
    return (
      <div className="mx-auto max-w-3xl space-y-3">
        {back}
        {error ? <p className="break-words text-xs text-danger">{error}</p> : <p className="text-sm text-muted">Loading…</p>}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {back}
      <PageHeader
        title={idea.title}
        icon={Lightbulb}
        subtitle={[idea.market, idea.created && `started ${formatIsoDate(idea.created)}`, idea.last_edited && `touched ${formatIsoDate(idea.last_edited)}`]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <Link
            href={`/kb/browse?path=${encodeURIComponent(idea.folder)}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1 text-xs hover:border-accent/60 hover:bg-accent/10"
          >
            <FolderOpen size={14} /> Browse folder
          </Link>
        }
      />
      {error && <p className="break-words text-xs text-danger">{error}</p>}

      {!idea.has_hub ? (
        <NewIdeaForm initialTitle={idea.title} onCreated={setIdea} />
      ) : (
        <Panel
          title="Overview"
          icon={Lightbulb}
          actions={
            !editing && (
              <button onClick={() => setEditing(true)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
                <Pencil size={12} /> Edit
              </button>
            )
          }
          bodyClassName="space-y-3"
        >
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Status">
            {IDEA_STATUSES.map((s) => (
              <button
                key={s}
                role="radio"
                aria-checked={idea.status === s}
                disabled={saving}
                onClick={() => idea.status !== s && save({ status: s })}
                className={
                  idea.status === s
                    ? "rounded-md border border-accent/60 bg-accent/15 px-2.5 py-1 text-xs font-medium text-accent shadow-glow"
                    : "rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-accent/40 hover:text-foreground"
                }
              >
                {STATUS_LABEL[s]}
              </button>
            ))}
          </div>
          {editing ? (
            <FieldsEditor idea={idea} saving={saving} onCancel={() => setEditing(false)} onSave={async (u) => (await save(u)) && setEditing(false)} />
          ) : (
            <>
              {idea.summary ? <p className="break-words text-sm">{idea.summary}</p> : <p className="text-xs text-muted">No summary yet.</p>}
              {idea.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {idea.tags.map((t) => (
                    <span key={t} className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-muted">
                      #{t}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
          {idea.body && (
            <div className="border-t border-line pt-3">
              <IdeaMarkdown folder={idea.folder} content={idea.body} />
            </div>
          )}
        </Panel>
      )}

      {idea.file_total === 0 && idea.links.length === 0 ? (
        <EmptyState icon={FolderOpen}>No files yet.</EmptyState>
      ) : (
        <IdeaFiles idea={idea} />
      )}
      <SortHint />
    </div>
  );
}

function FieldsEditor({
  idea,
  saving,
  onSave,
  onCancel,
}: {
  idea: IdeaDetail;
  saving: boolean;
  onSave: (u: { summary: string; market: string; tags: string[] }) => void;
  onCancel: () => void;
}) {
  const [summary, setSummary] = useState(idea.summary);
  const [market, setMarket] = useState(idea.market);
  const [tags, setTags] = useState(idea.tags.join(", "));
  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({ summary: summary.trim(), market: market.trim(), tags: parseTags(tags) });
      }}
    >
      <Textarea rows={2} placeholder="summary" value={summary} onChange={(e) => setSummary(e.target.value)} />
      <Input placeholder="market (e.g. small cafés, US)" value={market} onChange={(e) => setMarket(e.target.value)} />
      <Input placeholder="tags, comma separated" value={tags} onChange={(e) => setTags(e.target.value)} />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
