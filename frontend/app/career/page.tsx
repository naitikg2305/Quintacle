"use client";

import { useEffect, useState } from "react";
import { Briefcase, Check, FileText, GitBranch, Globe, Play, Save, Trash2, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { Badge, EmptyState, PageHeader, Panel } from "@/components/ui/Panel";
import {
  CareerDraftBullet,
  CareerGroup,
  CareerHub,
  CareerProvider,
  CareerRecordStatus,
  CareerRun,
  CareerSaveBody,
  generateWebsite,
  getCareerRecord,
  getWebsiteStatus,
  importCareerRecord,
  listCareerHubs,
  rejectWebsiteCandidate,
  runCareerRecord,
  runWebsite,
  saveCareerRecord,
  updateCareerHub,
  WebsiteCandidate,
  WebsiteResult,
  WebsiteRun,
  WebsiteStatus,
} from "@/lib/api";
import { todayIso } from "@/lib/date";

const NEW_ENTRY = "__new__";

// One editable group per hub: where its bullets go + the bullets themselves.
type GroupDraft = {
  group: CareerGroup;
  target: string; // entry id, NEW_ENTRY, or "" (not chosen yet)
  newSection: number;
  newTitle: string;
  bullets: CareerDraftBullet[];
};

function ProviderSelect({ value, onChange }: { value: CareerProvider; onChange: (p: CareerProvider) => void }) {
  return (
    <Select className="w-auto" value={value} onChange={(e) => onChange(e.target.value as CareerProvider)} aria-label="Model provider">
      <option value="auto">auto (local first)</option>
      <option value="local">local only</option>
      <option value="cloud">cloud</option>
    </Select>
  );
}

function Sources({ b }: { b: CareerDraftBullet }) {
  if (!b.sources.length) return null;
  return (
    <details className="mt-1 text-xs text-muted">
      <summary className="cursor-pointer">sources ({b.sources.length})</summary>
      <ul className="mt-1 space-y-0.5 border-l border-line pl-2">
        {b.sources.map((s) => (
          <li key={s.n}>
            <span className="font-mono">{s.date}</span> {s.text}
          </li>
        ))}
      </ul>
    </details>
  );
}

// --- Career record panel ------------------------------------------------------

function RecordPanel() {
  const [status, setStatus] = useState<CareerRecordStatus | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [start, setStart] = useState("");
  const [includeToday, setIncludeToday] = useState(false);
  const [provider, setProvider] = useState<CareerProvider>("auto");
  const [run, setRun] = useState<CareerRun | null>(null);
  const [drafts, setDrafts] = useState<GroupDraft[]>([]);

  const load = () =>
    getCareerRecord()
      .then(setStatus)
      .catch((e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  const entries = status?.entries ?? [];
  const sections = status?.sections ?? [];

  async function onImport(file: File) {
    setBusy(true);
    setError("");
    try {
      await importCareerRecord(await file.text());
      setNotice(`Imported ${file.name} as ${status?.record_folder}/${status?.record_title}.`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onRun() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const r = await runCareerRecord({ start: start || undefined, include_today: includeToday, provider });
      setRun(r);
      const lastSection = sections.length ? sections[sections.length - 1].num : 7;
      setDrafts(
        r.groups.map((g) => ({
          group: g,
          target: g.mapping.entry_id ?? "",
          newSection: lastSection,
          newTitle: "",
          bullets: g.bullets,
        }))
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function patch(i: number, change: Partial<GroupDraft>) {
    setDrafts((ds) => ds.map((d, j) => (j === i ? { ...d, ...change } : d)));
  }
  function patchBullet(i: number, k: number, change: Partial<CareerDraftBullet>) {
    setDrafts((ds) =>
      ds.map((d, j) => (j === i ? { ...d, bullets: d.bullets.map((b, m) => (m === k ? { ...b, ...change } : b)) } : d))
    );
  }
  function dropBullet(i: number, k: number) {
    setDrafts((ds) => ds.map((d, j) => (j === i ? { ...d, bullets: d.bullets.filter((_, m) => m !== k) } : d)));
  }

  const unresolved = drafts.filter(
    (d) => d.bullets.some((b) => b.text.trim()) && (!d.target || (d.target === NEW_ENTRY && !d.newTitle.trim()))
  );

  async function onSave() {
    if (!run?.through) return;
    const body: CareerSaveBody = { through: run.through, base_hash: run.base_hash, bullets: [], new_entries: [], mappings: [] };
    for (const d of drafts) {
      const kept = d.bullets.filter((b) => b.text.trim()).map((b) => ({ section: b.section, text: b.text.trim(), date: b.date }));
      if (d.target === NEW_ENTRY) {
        if (kept.length)
          body.new_entries.push({
            section: d.newSection,
            title: d.newTitle.trim(),
            hub_folder: d.group.hub.folder,
            hub_slug: d.group.hub.slug,
            bullets: kept,
          });
        continue;
      }
      if (!d.target) continue;
      body.bullets.push(...kept.map((b) => ({ ...b, entry_id: d.target })));
      if (d.group.mapping.entry_id !== d.target)
        body.mappings.push({ hub_folder: d.group.hub.folder, hub_slug: d.group.hub.slug, entry_id: d.target });
    }
    setBusy(true);
    setError("");
    try {
      const res = await saveCareerRecord(body);
      setNotice(
        `Saved ${res.appended} bullet(s)${res.new_entries.length ? `, new entries ${res.new_entries.join(", ")}` : ""}. Covered through ${res.covered_through}.`
      );
      setRun(null);
      setDrafts([]);
      setStart("");
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Career record" icon={FileText}>
      {error && <p className="mb-3 break-words text-sm text-danger">{error}</p>}
      {notice && <p className="mb-3 text-sm text-ok">{notice}</p>}
      {!status ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : !status.exists ? (
        <div className="space-y-3 text-sm">
          <p className="text-muted">
            No record note at <span className="font-mono">{status.record_folder}/{status.record_title}</span> yet. Pick your master
            record markdown file to import it as that note (it is never overwritten by an import afterwards).
          </p>
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-line-strong px-3 py-2 text-sm hover:bg-accent/10">
            <Upload size={14} /> Import record file
            <input
              type="file"
              accept=".md,.markdown,.txt"
              className="hidden"
              disabled={busy}
              onChange={(e) => e.target.files?.[0] && onImport(e.target.files[0])}
            />
          </label>
        </div>
      ) : status.private ? (
        <p className="text-sm text-warn">The record note is marked private, so the updater can&apos;t use it.</p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3 text-sm">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Covered through</p>
              <p className="font-mono">{status.covered_through ?? "never"}</p>
            </div>
            {!status.covered_through && (
              <label className="flex flex-col gap-1">
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Start from</span>
                <Input type="date" className="w-auto" value={start} max={todayIso()} onChange={(e) => setStart(e.target.value)} />
              </label>
            )}
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={includeToday} onChange={(e) => setIncludeToday(e.target.checked)} />
              include today
            </label>
            <ProviderSelect value={provider} onChange={setProvider} />
            <Button variant="primary" size="sm" disabled={busy || (!status.covered_through && !start)} onClick={onRun}>
              <Play size={13} /> {busy && !run ? "Drafting…" : "Run"}
            </Button>
          </div>

          {run && (
            <div className="space-y-4">
              <p className="text-xs text-muted">
                Logs {run.after ? `after ${run.after}` : `from ${run.start}`} through {run.until}: {run.dates.length} day(s)
                {run.skipped.private.length > 0 && ` · ${run.skipped.private.length} private skipped`}
                {run.skipped.placeholder.length > 0 && ` · ${run.skipped.placeholder.length} placeholder-only skipped`}
                {run.skipped.unlinked_sessions > 0 && ` · ${run.skipped.unlinked_sessions} session(s) mention no hub`}
                {run.provider_used && ` · drafted by ${run.provider_used}`}
              </p>
              {drafts.length === 0 && <EmptyState icon={FileText}>No hub-linked work logs in this window.</EmptyState>}
              {drafts.map((d, i) => (
                <div key={d.group.hub.id} className="rounded-lg border border-line p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="font-medium">{d.group.hub.title}</span>
                    <Badge tone="muted">{d.group.hub.kind}</Badge>
                    <span className="text-xs text-muted">{d.group.sessions.length} session(s)</span>
                    {!d.group.mapping.entry_id && <Badge tone="warn">no record entry — pick one or propose a new entry</Badge>}
                  </div>
                  <div className="mb-3 flex flex-wrap gap-2">
                    <Select className="w-auto min-w-0 max-w-full" value={d.target} onChange={(e) => patch(i, { target: e.target.value })} aria-label="Record entry">
                      <option value="">— choose entry —</option>
                      {d.group.mapping.candidates.length > 0 && (
                        <optgroup label="Likely">
                          {d.group.mapping.candidates.map((id) => (
                            <option key={`c${id}`} value={id}>
                              {id} {entries.find((e) => e.id === id)?.title}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      <optgroup label="All entries">
                        {entries.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.id} {e.title}
                          </option>
                        ))}
                      </optgroup>
                      <option value={NEW_ENTRY}>+ propose a new entry</option>
                    </Select>
                    {d.target === NEW_ENTRY && (
                      <>
                        <Select className="w-auto" value={d.newSection} onChange={(e) => patch(i, { newSection: Number(e.target.value) })} aria-label="Section">
                          {sections.map((s) => (
                            <option key={s.num} value={s.num}>
                              §{s.num} {s.title.slice(0, 40)}
                            </option>
                          ))}
                        </Select>
                        <Input
                          className="w-auto min-w-0 flex-1"
                          placeholder="Entry title, e.g. Personal project — …"
                          value={d.newTitle}
                          onChange={(e) => patch(i, { newTitle: e.target.value })}
                        />
                      </>
                    )}
                  </div>
                  {d.group.error && <p className="mb-2 text-xs text-danger">Drafting failed: {d.group.error}</p>}
                  <ul className="space-y-2">
                    {d.bullets.map((b, k) => (
                      <li key={k} className="rounded-md border border-line bg-surface-2/40 p-2">
                        <div className="flex gap-2">
                          <Textarea rows={2} value={b.text} onChange={(e) => patchBullet(i, k, { text: e.target.value })} />
                          <div className="flex flex-col gap-1">
                            <Select
                              className="w-auto text-xs"
                              value={b.section}
                              onChange={(e) => patchBullet(i, k, { section: e.target.value as CareerDraftBullet["section"] })}
                              aria-label="Section"
                            >
                              <option value="phrasing">phrasing bank</option>
                              <option value="detail">what I did</option>
                            </Select>
                            <Button variant="ghost" size="sm" onClick={() => dropBullet(i, k)} aria-label="Delete bullet">
                              <Trash2 size={13} />
                            </Button>
                          </div>
                        </div>
                        <p className="mt-1 font-mono text-[10px] text-muted">[WL {b.date}]</p>
                        <Sources b={b} />
                      </li>
                    ))}
                    {d.bullets.length === 0 && !d.group.error && <li className="text-xs text-muted">No new bullets proposed.</li>}
                  </ul>
                  {d.group.rejected.length > 0 && (
                    <details className="mt-2 text-xs text-muted">
                      <summary className="cursor-pointer">{d.group.rejected.length} draft(s) rejected by the fact check</summary>
                      <ul className="mt-1 space-y-1">
                        {d.group.rejected.map((b, k) => (
                          <li key={k}>
                            <span className="line-through">{b.text}</span> — {b.reasons?.join("; ")}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ))}
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" disabled={busy || !run.through || unresolved.length > 0} onClick={onSave}>
                  <Save size={14} /> Save to record
                </Button>
                <span className="text-xs text-muted">
                  {unresolved.length > 0
                    ? `Pick an entry for: ${unresolved.map((d) => d.group.hub.title).join(", ")}`
                    : run.through
                      ? `Appends only, then moves the watermark to ${run.through}.`
                      : "Nothing in this window."}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

// --- Website panel ------------------------------------------------------------

function AliasTable() {
  const [hubs, setHubs] = useState<CareerHub[]>([]);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    listCareerHubs()
      .then(setHubs)
      .catch((e) => setError(String(e)));
  }, []);

  function edit(id: string, change: Partial<CareerHub>) {
    setHubs((hs) => hs.map((h) => (h.id === id ? { ...h, ...change } : h)));
  }
  async function save(h: CareerHub) {
    setError("");
    try {
      const fresh = await updateCareerHub({
        folder: h.folder,
        slug: h.slug,
        public: h.public,
        public_name: h.public_name,
        public_repo: h.public_repo,
        public_slug: h.public_slug,
        record_entry: h.record_entry ?? "",
      });
      setHubs((hs) => hs.map((x) => (x.id === h.id ? { ...x, ...fresh } : x)));
      setSaved(h.id);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <details className="rounded-lg border border-line p-3">
      <summary className="cursor-pointer text-sm font-medium">Alias table — which hubs may appear on the site</summary>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      <p className="mt-2 text-xs text-muted">Only public hubs appear, under their public name. Company work stays off unless you tick it.</p>
      <div className="mt-2 space-y-2">
        {hubs.length === 0 && <p className="text-xs text-muted">No Career/Projects hub notes yet.</p>}
        {hubs.map((h) => (
          <div key={h.id} className="grid grid-cols-2 gap-2 rounded-md border border-line p-2 text-xs sm:grid-cols-6 sm:items-center">
            <div className="col-span-2 min-w-0 sm:col-span-1">
              <p className="truncate font-medium">{h.title}</p>
              <p className="text-muted">
                {h.kind}
                {h.private && " · private"}
              </p>
            </div>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={h.public} disabled={h.private} onChange={(e) => edit(h.id, { public: e.target.checked })} />
              public
            </label>
            <Input className="text-xs" placeholder="public name" value={h.public_name} onChange={(e) => edit(h.id, { public_name: e.target.value })} />
            <Input className="text-xs" placeholder="public repo URL" value={h.public_repo} onChange={(e) => edit(h.id, { public_repo: e.target.value })} />
            <Input className="text-xs" placeholder="site slug" value={h.public_slug} onChange={(e) => edit(h.id, { public_slug: e.target.value })} />
            <div className="flex items-center gap-2">
              <Input
                className="text-xs"
                placeholder="record entry"
                value={h.record_entry ?? ""}
                onChange={(e) => edit(h.id, { record_entry: e.target.value })}
              />
              <Button size="sm" onClick={() => save(h)} aria-label={`Save ${h.title}`}>
                {saved === h.id ? <Check size={13} /> : <Save size={13} />}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

function WebsitePanel() {
  const [status, setStatus] = useState<WebsiteStatus | null>(null);
  const [provider, setProvider] = useState<CareerProvider>("auto");
  const [run, setRun] = useState<WebsiteRun | null>(null);
  const [approved, setApproved] = useState<Record<string, boolean>>({});
  const [overrides, setOverrides] = useState<Record<string, { category?: string; summary?: string }>>({});
  const [result, setResult] = useState<WebsiteResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    getWebsiteStatus()
      .then(setStatus)
      .catch((e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  async function onRun() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const r = await runWebsite(provider);
      setRun(r);
      setApproved(Object.fromEntries(r.candidates.map((c) => [c.id, c.suggest === true && c.blocked.length === 0])));
      setOverrides({});
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onReject(c: WebsiteCandidate) {
    try {
      await rejectWebsiteCandidate(c.id, c.stamp);
      setRun((r) => (r ? { ...r, candidates: r.candidates.filter((x) => x.id !== c.id) } : r));
    } catch (e) {
      setError(String(e));
    }
  }

  async function onGenerate() {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      const items = run.candidates
        .filter((c) => approved[c.id])
        .map((c) => ({
          id: c.id,
          category: overrides[c.id]?.category ?? c.category,
          summary: overrides[c.id]?.summary ?? c.summary,
        }));
      const res = await generateWebsite({ through: run.through, items });
      setResult(res);
      setRun(null);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const nApproved = run ? run.candidates.filter((c) => approved[c.id]).length : 0;

  return (
    <Panel title="Website" icon={Globe}>
      {error && <p className="mb-3 break-words text-sm text-danger">{error}</p>}
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Changes since</p>
            <p className="font-mono">{status?.watermark ?? "never"}</p>
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Last run</p>
            <p className="font-mono">{status?.last_run ?? "—"}</p>
          </div>
          <ProviderSelect value={provider} onChange={setProvider} />
          <Button variant="primary" size="sm" disabled={busy} onClick={onRun}>
            <Play size={13} /> {busy && !run ? "Checking…" : "Run"}
          </Button>
        </div>
        {status && (
          <p className="break-all text-xs text-muted">
            Repo: <span className="font-mono">{status.repo}</span> · writes onto a new local branch, never pushed or merged.
          </p>
        )}

        {run && (
          <div className="space-y-2">
            {run.candidates.length === 0 && <EmptyState icon={Globe}>Nothing new since the last run.</EmptyState>}
            {run.more > 0 && <p className="text-xs text-muted">{run.more} more candidate(s) wait for the next run.</p>}
            {run.candidates.map((c) => (
              <div key={c.id} className="rounded-lg border border-line p-3 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <label className="flex min-w-0 flex-1 items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={!!approved[c.id]}
                      disabled={c.blocked.length > 0}
                      onChange={(e) => setApproved((a) => ({ ...a, [c.id]: e.target.checked }))}
                    />
                    <span className="min-w-0">
                      <span className="font-medium">{c.title}</span>{" "}
                      <Badge tone="muted">{c.kind}</Badge>{" "}
                      {c.suggest === true && <Badge tone="ok">suggested</Badge>}
                      {c.suggest === false && <Badge tone="muted">not suggested</Badge>}
                      <span className="mt-0.5 block text-xs text-muted">{c.reason}</span>
                      <span className="block break-all font-mono text-[10px] text-muted">→ {c.target_path}</span>
                    </span>
                  </label>
                  <Button variant="ghost" size="sm" onClick={() => onReject(c)} aria-label="Reject">
                    <X size={13} /> reject
                  </Button>
                </div>
                {c.snippet && <p className="mt-1 line-clamp-2 text-xs text-muted">{c.snippet}</p>}
                {c.renames.length > 0 && (
                  <p className="mt-1 text-xs text-muted">Renamed: {c.renames.map((r) => `${r.from} → ${r.to}`).join(", ")}</p>
                )}
                {c.kind === "knowledge" && approved[c.id] && (
                  <div className="mt-2 grid gap-2 sm:grid-cols-3">
                    <Input
                      className="text-xs"
                      placeholder="category"
                      value={overrides[c.id]?.category ?? c.category ?? ""}
                      onChange={(e) => setOverrides((o) => ({ ...o, [c.id]: { ...o[c.id], category: e.target.value } }))}
                    />
                    <Input
                      className="text-xs sm:col-span-2"
                      placeholder="summary"
                      value={overrides[c.id]?.summary ?? c.summary ?? ""}
                      onChange={(e) => setOverrides((o) => ({ ...o, [c.id]: { ...o[c.id], summary: e.target.value } }))}
                    />
                  </div>
                )}
              </div>
            ))}
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <Button variant="primary" disabled={busy} onClick={onGenerate}>
                <GitBranch size={14} /> {nApproved ? `Generate branch (${nApproved})` : "Finish run (nothing approved)"}
              </Button>
            </div>
          </div>
        )}

        {result && (
          <div className="rounded-lg border border-line p-3 text-sm">
            {result.branch ? (
              <>
                <p>
                  Branch <span className="font-mono text-accent">{result.branch}</span> · commit{" "}
                  <span className="font-mono">{result.commit?.slice(0, 8)}</span>
                </p>
                <ul className="mt-2 space-y-0.5 font-mono text-xs">
                  {result.files.map((f) => (
                    <li key={f.path} className="break-all">
                      <span className={f.status === "A" ? "text-ok" : "text-warn"}>{f.status}</span> {f.path}{" "}
                      <span className="text-ok">+{f.added}</span> <span className="text-danger">-{f.removed}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-muted">{result.message ?? "No branch created — watermark moved."}</p>
            )}
            {result.skipped.length > 0 && (
              <ul className="mt-2 text-xs text-warn">
                {result.skipped.map((s) => (
                  <li key={s.id}>
                    {s.id}: {s.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <AliasTable />
      </div>
    </Panel>
  );
}

export default function CareerPage() {
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Career updates"
        subtitle="Fold work logs into your career record, and turn approved notes into website content. Nothing is written until you Save."
        icon={Briefcase}
      />
      <div className="grid min-w-0 gap-4">
        <RecordPanel />
        <WebsitePanel />
      </div>
    </div>
  );
}
