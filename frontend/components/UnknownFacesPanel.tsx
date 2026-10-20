"use client";

import { useEffect, useState } from "react";
import { User, X } from "lucide-react";
import { listPeople, tagUnknownFace } from "@/lib/api";
import { PendingFace } from "@/lib/entries";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";

// The "who is this?" tag flow, moved verbatim from the Drop page (next-wave
// §9 — chat absorbs drop): a saved photo's unrecognized faces come back on
// the commit response; each one can be tagged (an existing person or a new
// name) or dismissed. Tagging is never required for the save — the photo is
// already committed by the time this panel appears. The faces queue itself
// lives in the host page (it's fed by its Save); everything else is here.
export default function UnknownFacesPanel({
  faces,
  setFaces,
}: {
  faces: PendingFace[];
  setFaces: React.Dispatch<React.SetStateAction<PendingFace[]>>;
}) {
  const [peopleNames, setPeopleNames] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    if (faces.length > 0) listPeople().then((ps) => setPeopleNames(ps.map((p) => p.name)));
  }, [faces.length]);

  function updateFace(i: number, patch: Partial<PendingFace>) {
    setFaces((prev) => prev.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  }

  function dismissFace(i: number) {
    setFaces((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function tagFace(i: number) {
    const face = faces[i];
    const name = (face.pick || face.newName).trim();
    if (!name) return;
    setBusy(true);
    setStatus("tagging...");
    try {
      const result = await tagUnknownFace(face.embeddingId, name, face.photo);
      dismissFace(i);
      setStatus(
        `tagged ${result.person_name}${result.created_person ? " (new person)" : ""}${
          result.journal_updated ? " — journal updated" : ""
        }`
      );
      if (result.created_person) setPeopleNames((prev) => [...prev, result.person_name]);
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  if (faces.length === 0) return null;

  return (
    <Panel title={`Unknown faces (${faces.length})`} className={cn("border-accent/40")}>
      <div className="space-y-3">
        <p className="text-xs text-muted">
          Someone in a saved photo wasn&apos;t recognized. Tell me who they are — pick a person or type a new name —
          and they get connected to the photo and that day&apos;s journal. Or dismiss; the photo is already saved.
        </p>
        {faces.map((face, i) => (
          <div key={`${face.embeddingId}-${i}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-2">
            <User size={15} className="shrink-0 text-accent" />
            <span className="text-xs text-muted">
              in &quot;{face.photoTitle}&quot;
              {face.suggestedName ? ` — maybe ${face.suggestedName}?` : ""}
            </span>
            <select
              value={face.pick}
              onChange={(e) => updateFace(i, { pick: e.target.value })}
              className="rounded-lg border border-line bg-transparent px-2 py-1 text-sm"
            >
              <option value="">new person…</option>
              {peopleNames.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            {!face.pick && (
              <Input
                placeholder="their name"
                value={face.newName}
                onChange={(e) => updateFace(i, { newName: e.target.value })}
                className="w-36 py-1 text-sm"
              />
            )}
            <Button variant="primary" onClick={() => tagFace(i)} disabled={busy || !(face.pick || face.newName.trim())}>
              Tag
            </Button>
            <Button variant="ghost" onClick={() => dismissFace(i)} aria-label="Dismiss unknown face">
              <X size={14} />
            </Button>
          </div>
        ))}
        {status && <p className="text-xs text-muted">{status}</p>}
      </div>
    </Panel>
  );
}
