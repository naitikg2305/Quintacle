"use client";

import { useState } from "react";
import { ImagePlus, Paperclip, Plus } from "lucide-react";
import { addKBEntryAsset, pushKBEntry, sortKBEntry } from "@/lib/api";
import { DropSession } from "@/lib/entries";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";

// The "Still going" keep-adding session, moved verbatim from the Drop page
// (next-wave §9 — chat absorbs drop). After a single-note drop commits, the
// entry stays open for more rounds — a lecture, a live-evolving trip record —
// instead of forcing a fresh drop (and a fresh AI classification) for every
// new sentence or photo. Folds more text in via the same merge-update
// /kb/sort Browse's "add to this note" uses, and attaches more files via the
// same endpoint Browse uses to add a photo to an existing entry.
export default function StillGoingPanel({ session, onEnd }: { session: DropSession; onEnd: () => void }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function foldIntoSession() {
    if (!text.trim()) return;
    setBusy(true);
    setStatus("adding...");
    try {
      const suggestion = await sortKBEntry(text.trim(), { folder: session.folder, slug: session.slug });
      await pushKBEntry(suggestion);
      setText("");
      setStatus("added");
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  async function attachToSession() {
    if (!file) return;
    setBusy(true);
    setStatus("attaching...");
    try {
      await addKBEntryAsset(session.folder, session.slug, file);
      setFile(null);
      setStatus("attached");
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  return (
    <Panel title={`Still going — "${session.title}"`} className={cn("border-accent/40")}>
      <div className="space-y-3">
        <p className="text-xs text-muted">
          A lecture, a live trip record, anything you keep adding to — fold in more text or attach more photos
          without starting a new drop. Each round saves straight into this entry.
        </p>
        <Textarea
          rows={3}
          placeholder="More notes to fold into this entry..."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" onClick={foldIntoSession} disabled={busy || !text.trim()}>
            <Plus size={15} /> Add to note
          </Button>
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-line-strong px-4 py-2 text-sm transition-colors hover:border-accent/60 hover:bg-accent/10">
            <Paperclip size={15} /> {file ? file.name : "Choose attachment"}
            <input
              type="file"
              accept="image/*,video/*,.pdf,.docx,.stl"
              capture="environment"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {file && (
            <Button onClick={attachToSession} disabled={busy}>
              <ImagePlus size={15} /> Attach
            </Button>
          )}
          <Button variant="ghost" onClick={onEnd}>
            Done
          </Button>
        </div>
        {status && <p className="text-xs text-muted">{status}</p>}
      </div>
    </Panel>
  );
}
