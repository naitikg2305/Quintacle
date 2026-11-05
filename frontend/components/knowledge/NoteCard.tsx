"use client";

import { Lock, Paperclip } from "lucide-react";
import { formatIsoDate } from "@/lib/date";
import type { KnowledgeNoteRow } from "@/lib/knowledgeApi";

// One note in the grid — the website's "title + summary" row, as a HUD card.
export function NoteCard({ note, onOpen, onTopic }: { note: KnowledgeNoteRow; onOpen: () => void; onTopic: (t: string) => void }) {
  return (
    <article
      className="group flex min-w-0 flex-col gap-2 rounded-xl border border-line bg-surface/80 p-4 shadow-panel transition-colors hover:border-accent/50 hover:bg-accent/5"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {note.topic ? (
          <button
            onClick={() => onTopic(note.topic)}
            className="max-w-full truncate rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent hover:bg-accent/20"
            title={`Filter: ${note.topic_label}`}
          >
            {note.topic_label}
          </button>
        ) : (
          <span className="rounded-md border border-line bg-white/5 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted">
            General
          </span>
        )}
        {note.private && (
          <span className="inline-flex items-center gap-1 rounded-md border border-warn/40 bg-warn/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-warn" title="Private — never sent to a cloud model">
            <Lock size={10} /> private
          </span>
        )}
        {note.has_assets && <Paperclip size={12} className="text-muted" aria-label="Has attachments" />}
      </div>
      <button onClick={onOpen} className="text-left">
        <h3 className="text-base font-semibold leading-snug tracking-tight text-foreground group-hover:text-accent">{note.title}</h3>
        {note.summary && <p className="mt-1 line-clamp-3 text-sm text-muted">{note.summary}</p>}
      </button>
      <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-[11px] text-muted">
        <span className="font-mono">{formatIsoDate(note.edited)}</span>
        {[...note.tags, ...note.hubs.map((h) => h.label)].slice(0, 4).map((t) => (
          <span key={t} className="text-accent/70">#{t}</span>
        ))}
      </div>
    </article>
  );
}
