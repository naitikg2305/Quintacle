"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, BookOpen, FileText, Folder, Paperclip, Pencil, Plus, ScrollText } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState, Panel } from "@/components/ui/Panel";
import { kbAssetUrl } from "@/lib/api";
import { formatIsoDate } from "@/lib/date";
import type { CareerFile, CareerNode } from "@/lib/careerPageApi";
import { Activity, detailHref } from "./CareerTimeline";
import { HubForm } from "./HubForm";

const WORKLOG_FOLDER = "daily-log/work-logs";
const browseHref = (folder: string, slug?: string) =>
  `/kb/browse?path=${encodeURIComponent(folder)}${slug ? `&open=${encodeURIComponent(slug)}` : ""}`;

function FileRow({ f }: { f: CareerFile }) {
  const cls = "flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent/10";
  if (f.kind === "note")
    return (
      <Link href={browseHref(f.folder, f.slug)} className={cls}>
        <FileText size={14} className="shrink-0 text-accent" />
        <span className="truncate">{f.name}</span>
        {f.private && <Badge tone="muted">private</Badge>}
      </Link>
    );
  if (f.kind === "file")
    return (
      <a href={kbAssetUrl(f.folder, f.path)} target="_blank" rel="noreferrer" className={cls}>
        <Paperclip size={14} className="shrink-0 text-accent" />
        <span className="truncate">{f.name}</span>
      </a>
    );
  return (
    <Link href={browseHref(f.folder)} className={cls}>
      <Folder size={14} className="shrink-0 text-accent" />
      <span className="truncate">{f.name}/</span>
    </Link>
  );
}

export function HubDetail({
  node,
  orgs,
  onChanged,
}: {
  node: CareerNode;
  orgs: CareerNode[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const meta = [node.range.display, node.location].filter(Boolean).join(" • ");
  const canHaveRoles = node.type !== "role" && node.type !== "contract";

  return (
    <div className="space-y-4">
      <Link href="/career" className="inline-flex items-center gap-1 font-mono text-sm text-accent hover:underline">
        <ArrowLeft size={14} /> career
      </Link>

      <article className="rounded-lg border border-accent/30 bg-background/80 p-4 shadow-[0_0_12px_rgb(34_211_238/0.12)] sm:px-6 sm:py-5">
        <p className="font-mono text-xs text-accent">
          $ cat {node.folder}/{node.slug}.md
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="min-w-0 break-words font-mono text-xl font-semibold text-accent sm:text-2xl">
            {node.role && node.children.length === 0 ? `${node.role} — ${node.title}` : node.title}
          </h1>
          {node.range.present && <Badge tone="ok">present</Badge>}
          <Badge tone="muted">{node.type}</Badge>
          {node.private && <Badge tone="muted">private</Badge>}
          {node.public && <Badge>public{node.public_name && node.public_name !== node.title ? `: ${node.public_name}` : ""}</Badge>}
        </div>
        {meta && <p className="mt-0.5 text-sm italic text-muted">{meta}</p>}
        {node.summary && <p className="mt-2 text-sm text-foreground/85">{node.summary}</p>}
        {node.bullets.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground/85 marker:text-accent">
            {node.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
        <div className="mt-3">
          <Activity node={node} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => (setEditing((v) => !v), setAdding(false))}>
            <Pencil size={13} /> Edit fields
          </Button>
          {canHaveRoles && (
            <Button size="sm" onClick={() => (setAdding((v) => !v), setEditing(false))}>
              <Plus size={13} /> Add role
            </Button>
          )}
          <Link href={browseHref(node.folder, node.slug)} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs text-muted hover:bg-white/5 hover:text-foreground">
            <BookOpen size={13} /> Open note
          </Link>
        </div>
      </article>

      {editing && (
        <Panel title="Edit fields" icon={Pencil}>
          <HubForm
            hub={node}
            orgs={orgs}
            onCancel={() => setEditing(false)}
            onSaved={() => {
              setEditing(false);
              onChanged();
            }}
          />
        </Panel>
      )}
      {adding && (
        <Panel title={`Add a role at ${node.title}`} icon={Plus}>
          <HubForm
            orgs={orgs}
            defaultOrg={node.folder}
            onCancel={() => setAdding(false)}
            onSaved={() => {
              setAdding(false);
              onChanged();
            }}
          />
        </Panel>
      )}

      {node.children.length > 0 && (
        <Panel title="Roles" icon={Folder}>
          <ul className="space-y-2">
            {node.children.map((c) => (
              <li key={c.id} className="border-l border-line pl-3">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <Link href={detailHref(c)} className="font-mono text-sm font-semibold text-accent hover:underline">
                    {c.role || c.title}
                  </Link>
                  {c.range.display && <span className="font-mono text-xs text-muted">— {c.range.display}</span>}
                  {c.range.present && <Badge tone="ok">present</Badge>}
                </div>
                <p className="font-mono text-[11px] text-muted">
                  {c.activity.days} log day{c.activity.days === 1 ? "" : "s"}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <div className="grid min-w-0 gap-4 md:grid-cols-2">
        <Panel title="Recent work logs" icon={ScrollText}>
          {node.activity.last.length === 0 ? (
            <EmptyState icon={ScrollText}>No work-log days link here yet.</EmptyState>
          ) : (
            <ul className="space-y-1">
              {node.activity.last.map((d) => (
                <li key={d}>
                  <Link href={browseHref(WORKLOG_FOLDER, `work-log-${d}`)} className="font-mono text-sm text-accent hover:underline">
                    {formatIsoDate(d)}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {node.type === "role" && (
            <p className="mt-2 text-xs text-muted">A role counts a day only when the log also links its org.</p>
          )}
        </Panel>

        <Panel title={`Files (${node.files.length})`} icon={Paperclip}>
          {node.files.length === 0 ? (
            <EmptyState icon={Paperclip}>
              Nothing else in <span className="font-mono">{node.folder}</span> yet — drop offer letters, docs, PDFs there.
            </EmptyState>
          ) : (
            <div className="-mx-2">
              {node.files.map((f) => (
                <FileRow key={`${f.kind}:${f.name}`} f={f} />
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Master career record" icon={BookOpen}>
        {node.record ? (
          <div>
            <p className="font-mono text-sm text-accent">
              {node.record.id} · {node.record.title}
            </p>
            <p className="text-xs text-muted">mapped by {node.record.how === "field" ? "record_entry field" : "unique title match"}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground/85 marker:text-accent">
              {node.record.bullets.map((b, i) => (
                <li key={i}>{b.text}</li>
              ))}
            </ul>
            {node.record.tech.length > 0 && <p className="mt-2 font-mono text-xs text-muted">tech: {node.record.tech.join(", ")}</p>}
          </div>
        ) : (
          <p className="text-sm text-muted">
            No record entry mapped.
            {node.record_candidates.length > 0 && <> Candidates: <span className="font-mono">{node.record_candidates.join(", ")}</span> — set one with Edit fields.</>}
          </p>
        )}
      </Panel>
    </div>
  );
}
