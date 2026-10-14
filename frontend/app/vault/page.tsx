"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, Lock, LockOpen, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { Badge, EmptyState, PageHeader, Panel } from "@/components/ui/Panel";
import {
  deleteVaultEntry,
  getVaultEntry,
  listVaultEntries,
  putVaultEntry,
  vaultInit,
  vaultLock,
  vaultStatus,
  vaultUnlock,
  VaultEntry,
  VaultEntrySummary,
  VaultStatus,
} from "@/lib/api";

// Mirrors the backend's slugify so a new entry lands where edits expect it.
function slugFor(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "entry";
}

function fmtCountdown(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export default function VaultPage() {
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [entries, setEntries] = useState<VaultEntrySummary[]>([]);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [pass1, setPass1] = useState("");
  const [pass2, setPass2] = useState("");

  const [expanded, setExpanded] = useState<string | null>(null);
  const [full, setFull] = useState<VaultEntry | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [secret, setSecret] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const s = await vaultStatus();
      setStatus(s);
      setSecondsLeft(s.auto_lock_seconds_remaining);
      if (s.initialized && !s.locked) {
        setEntries(await listVaultEntries());
      } else {
        setEntries([]);
        setExpanded(null);
        setFull(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Local countdown to the backend's auto-lock; on zero, re-check for real.
  useEffect(() => {
    if (status == null || !status.initialized || status.locked || secondsLeft == null || secondsLeft <= 0) return;
    const t = setTimeout(() => {
      const next = secondsLeft - 1;
      setSecondsLeft(next);
      if (next === 0) refresh();
    }, 1000);
    return () => clearTimeout(t);
  }, [status, secondsLeft, refresh]);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes(" 401 ")) {
        await refresh(); // auto-locked under us — fall back to the unlock prompt
      } else if (msg.includes(" 403 ")) {
        setError("wrong passphrase");
      } else {
        setError(msg);
      }
    }
    setBusy(false);
  }

  function resetForm() {
    setShowForm(false);
    setEditingSlug(null);
    setName("");
    setUsername("");
    setSecret("");
    setUrl("");
    setNotes("");
  }

  async function openEntry(slug: string) {
    if (expanded === slug) {
      setExpanded(null);
      setFull(null);
      return;
    }
    await run(async () => {
      const entry = await getVaultEntry(slug);
      setExpanded(slug);
      setFull(entry);
      setRevealed(false);
      setCopied(false);
      setSecondsLeft(300);
    });
  }

  async function startEdit(slug: string) {
    await run(async () => {
      const entry = await getVaultEntry(slug);
      setEditingSlug(slug);
      setName(entry.name);
      setUsername(entry.username);
      setSecret(entry.secret);
      setUrl(entry.url);
      setNotes(entry.notes);
      setShowForm(true);
    });
  }

  async function submit() {
    if (!name.trim()) return;
    await run(async () => {
      await putVaultEntry(editingSlug ?? slugFor(name), { name, username, secret, url, notes });
      resetForm();
      await refresh();
    });
  }

  async function remove(slug: string) {
    if (!confirm("Delete this entry? The encrypted file is removed for good.")) return;
    await run(async () => {
      await deleteVaultEntry(slug);
      await refresh();
    });
  }

  async function copySecret() {
    if (!full) return;
    await navigator.clipboard.writeText(full.secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (status === null) {
    return <p className="text-sm text-muted">loading…</p>;
  }

  if (!status.initialized) {
    return (
      <div className="mx-auto max-w-md space-y-4">
        <PageHeader title="Vault" icon={KeyRound} subtitle="Encrypted passwords and API keys, local only." />
        <Panel title="Create vault" icon={Lock} bodyClassName="space-y-3">
          <p className="text-sm text-muted">
            Pick a passphrase — it encrypts everything and is never stored. There is no recovery if you forget it.
          </p>
          <Input
            type="password"
            placeholder="passphrase"
            value={pass1}
            onChange={(e) => setPass1(e.target.value)}
          />
          <Input
            type="password"
            placeholder="passphrase, again"
            value={pass2}
            onChange={(e) => setPass2(e.target.value)}
          />
          {pass2 && pass1 !== pass2 && <p className="text-xs text-danger">passphrases don&apos;t match</p>}
          <Button
            variant="primary"
            disabled={busy || !pass1 || pass1 !== pass2}
            onClick={() =>
              run(async () => {
                await vaultInit(pass1);
                setPass1("");
                setPass2("");
                await refresh();
              })
            }
          >
            Create vault
          </Button>
          {error && <p className="text-sm text-danger">{error}</p>}
        </Panel>
      </div>
    );
  }

  if (status.locked) {
    return (
      <div className="mx-auto max-w-md space-y-4">
        <PageHeader title="Vault" icon={KeyRound} subtitle="Encrypted passwords and API keys, local only." />
        <Panel title="Locked" icon={Lock} bodyClassName="space-y-3">
          <Input
            type="password"
            placeholder="passphrase"
            value={pass1}
            onChange={(e) => setPass1(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && pass1) {
                run(async () => {
                  await vaultUnlock(pass1);
                  setPass1("");
                  await refresh();
                });
              }
            }}
          />
          <Button
            variant="primary"
            disabled={busy || !pass1}
            onClick={() =>
              run(async () => {
                await vaultUnlock(pass1);
                setPass1("");
                await refresh();
              })
            }
          >
            <LockOpen size={16} /> Unlock
          </Button>
          {error && <p className="text-sm text-danger">{error}</p>}
        </Panel>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageHeader
        title="Vault"
        icon={KeyRound}
        subtitle="Locks itself after 5 minutes idle."
        actions={
          <>
            {secondsLeft != null && <Badge tone={secondsLeft < 60 ? "warn" : "muted"}>locks in {fmtCountdown(Math.max(0, secondsLeft))}</Badge>}
            <Button size="sm" onClick={() => (showForm ? resetForm() : setShowForm(true))}>
              <Plus size={14} /> Entry
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() =>
                run(async () => {
                  await vaultLock();
                  await refresh();
                })
              }
            >
              <Lock size={14} /> Lock
            </Button>
          </>
        }
      />

      {error && <p className="text-sm text-danger">{error}</p>}

      {showForm && (
        <Panel title={editingSlug ? "Edit entry" : "New entry"} bodyClassName="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Input
              className="min-w-40 flex-1"
              placeholder="name (e.g. GitHub)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Input
              className="min-w-40 flex-1"
              placeholder="username / account"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <Input
            type="password"
            placeholder="secret (password / API key)"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
          <Input placeholder="url" value={url} onChange={(e) => setUrl(e.target.value)} />
          <Textarea rows={2} placeholder="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="flex gap-2">
            <Button variant="primary" disabled={busy || !name.trim()} onClick={submit}>
              {editingSlug ? "Save changes" : "Save entry"}
            </Button>
            <Button onClick={resetForm}>Cancel</Button>
          </div>
        </Panel>
      )}

      {entries.length === 0 && !showForm && (
        <EmptyState icon={KeyRound}>No entries yet — add your first password or API key.</EmptyState>
      )}

      <div className="space-y-2">
        {entries.map((e) => (
          <Panel key={e.slug} bodyClassName="space-y-2">
            <button onClick={() => openEntry(e.slug)} className="flex w-full items-center justify-between gap-2 text-left">
              <span className="flex min-w-0 flex-wrap items-center gap-x-2">
                <span className="font-medium text-sm">{e.name}</span>
                {e.username && <span className="text-xs text-muted">{e.username}</span>}
              </span>
              {e.url && (
                <a
                  href={e.url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(ev) => ev.stopPropagation()}
                  className="truncate text-xs text-accent underline-offset-2 hover:underline"
                >
                  {e.url}
                </a>
              )}
            </button>

            {expanded === e.slug && full && (
              <div className="space-y-2 border-t border-line pt-2">
                <div className="flex flex-wrap items-center gap-2">
                  <code className="rounded-lg border border-line bg-surface-2/60 px-3 py-1.5 font-mono text-sm">
                    {revealed ? full.secret : "••••••••••••"}
                  </code>
                  <Button size="sm" variant="ghost" onClick={() => setRevealed((v) => !v)}>
                    {revealed ? <EyeOff size={14} /> : <Eye size={14} />} {revealed ? "Hide" : "Reveal"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={copySecret}>
                    {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
                {full.notes && <p className="whitespace-pre-wrap text-sm text-muted">{full.notes}</p>}
                <div className="flex items-center gap-2">
                  <Button size="sm" onClick={() => startEdit(e.slug)}>
                    Edit
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => remove(e.slug)}>
                    Delete
                  </Button>
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-wider text-muted">
                    updated {full.updated_at.slice(0, 16).replace("T", " ")}
                  </span>
                </div>
              </div>
            )}
          </Panel>
        ))}
      </div>
    </div>
  );
}
