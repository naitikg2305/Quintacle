"use client";

import { useEffect, useState } from "react";
import { Brain, Trash2, TriangleAlert } from "lucide-react";
import { deleteSoftFact, getSoftRecord, SoftFact } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { EmptyState, PageHeader, Panel } from "@/components/ui/Panel";

export default function SoftRecordPage() {
  const [facts, setFacts] = useState<SoftFact[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSoftRecord()
      .then(setFacts)
      .catch((e) => {
        setFacts([]);
        setError(e instanceof Error ? e.message : String(e));
      });
  }, []);

  async function remove(fact: SoftFact) {
    const before = facts;
    setError(null);
    setFacts((cur) => (cur ?? []).filter((f) => f.id !== fact.id)); // optimistic
    try {
      await deleteSoftFact(fact.id);
    } catch (e) {
      setFacts(before); // roll back
      setError(`Couldn't delete: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Chat memory"
        icon={Brain}
        subtitle="Short facts pulled from your recent chats. Used only in casual mode, never saved as knowledge unless you press Record that."
      />
      {error && (
        <div role="alert" className="mb-3 flex items-center gap-1.5 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          <TriangleAlert size={13} /> {error}
        </div>
      )}
      {facts === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : facts.length === 0 ? (
        <EmptyState icon={Brain}>Nothing remembered yet — chats you keep will add short facts here</EmptyState>
      ) : (
        <Panel title={`${facts.length} remembered`} bodyClassName="p-0">
          <ul className="divide-y divide-line">
            {facts.map((f) => (
              <li key={f.id} className="flex items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">{f.date}</p>
                  <p className="text-sm">{f.text}</p>
                  <p className="mt-0.5 break-all text-xs text-muted">from chat: {f.transcript}</p>
                </div>
                <Button size="sm" onClick={() => remove(f)} aria-label={`Delete: ${f.text}`}>
                  <Trash2 size={14} /> Delete
                </Button>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
