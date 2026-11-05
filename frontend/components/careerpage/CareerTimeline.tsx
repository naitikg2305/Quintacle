"use client";

// The PersonalWebsite's experience page (`$ cat experience.md`, one black
// panel per employer, LinkedIn-style positions with bullets, a vertical
// `git log` line with glowing commit dots) redrawn in the HUD theme.
import Link from "next/link";
import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { Badge } from "@/components/ui/Panel";
import { formatIsoDate } from "@/lib/date";
import type { CareerNode } from "@/lib/careerPageApi";
import { Sparkline } from "./Sparkline";

export const detailHref = (n: CareerNode) => `/career?hub=${encodeURIComponent(n.folder)}`;

const TYPE_TONE = { employer: "accent", role: "accent", contract: "warn", education: "ok", other: "muted" } as const;

function Bullets({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-1.5 space-y-1 text-sm text-foreground/85">
      {items.map((b, i) => (
        <li key={i} className="flex gap-2">
          <span className="select-none font-mono text-accent">·</span>
          <span className="min-w-0">{b}</span>
        </li>
      ))}
    </ul>
  );
}

export function Activity({ node }: { node: CareerNode }) {
  const a = node.activity;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
      <Sparkline spark={a.spark} />
      <span>
        <span className="text-accent">{a.days}</span> log day{a.days === 1 ? "" : "s"}
        {a.last[0] && <> · last {formatIsoDate(a.last[0])}</>}
      </span>
      {node.file_count > 0 && (
        <span className="inline-flex items-center gap-1">
          <FileText size={11} /> {node.file_count} file{node.file_count === 1 ? "" : "s"}
        </span>
      )}
    </div>
  );
}

// One position inside an org card: "Role — dates" like the website's h4.
function Position({ node, open }: { node: CareerNode; open: boolean }) {
  return (
    <div className="border-l border-line pl-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <Link href={detailHref(node)} className="font-mono text-sm font-semibold text-accent hover:underline">
          {node.role || node.title}
        </Link>
        {node.role && node.role !== node.title && <span className="text-xs text-muted">({node.title})</span>}
        {node.range.display && <span className="font-mono text-xs text-muted">— {node.range.display}</span>}
        {node.range.present && <Badge tone="ok">present</Badge>}
        {node.private && <Badge tone="muted">private</Badge>}
      </div>
      {open && (
        <>
          {node.summary && <p className="mt-1 text-sm text-muted">{node.summary}</p>}
          <Bullets items={node.bullets} />
          {node.children.length > 0 && (
            <div className="mt-2 space-y-2">
              {node.children.map((c) => (
                <Position key={c.id} node={c} open={open} />
              ))}
            </div>
          )}
          {node.activity.days > 0 && (
            <div className="mt-1.5">
              <Activity node={node} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Card({ node }: { node: CareerNode }) {
  const [open, setOpen] = useState(node.range.present);
  const headline = node.children.length ? node.title : node.role ? `${node.role} — ${node.title}` : node.title;
  const meta = [node.range.display, node.location].filter(Boolean).join(" • ");
  return (
    <article className="rounded-lg border border-accent/30 bg-background/80 p-4 shadow-[0_0_12px_rgb(34_211_238/0.12)] sm:px-6 sm:py-5">
      <div className="flex items-start gap-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className="mt-1 shrink-0 text-muted hover:text-accent"
          aria-label={open ? "Collapse" : "Expand"}
          aria-expanded={open}
        >
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={detailHref(node)} className="min-w-0 break-words font-mono text-lg font-semibold text-accent hover:underline sm:text-xl">
              {headline}
            </Link>
            {node.range.present && <Badge tone="ok">present</Badge>}
            {node.type !== "employer" && <Badge tone={TYPE_TONE[node.type]}>{node.type}</Badge>}
            {node.private && <Badge tone="muted">private</Badge>}
          </div>
          {meta && <p className="mt-0.5 text-sm italic text-muted">{meta}</p>}
          {node.summary && <p className="mt-1.5 text-sm text-foreground/80">{node.summary}</p>}
        </div>
      </div>

      <div className="mt-3 space-y-3 sm:pl-6">
        {node.children.length > 0 ? (
          <div className="space-y-3">
            {node.children.map((c) => (
              <Position key={c.id} node={c} open={open} />
            ))}
          </div>
        ) : (
          open && <Bullets items={node.bullets} />
        )}
        {open && node.record && node.bullets.length === 0 && node.children.length === 0 && (
          <Bullets items={node.record.bullets.slice(0, 4).map((b) => b.text)} />
        )}
        <Activity node={node} />
        <Link href={detailHref(node)} className="inline-block font-mono text-xs text-accent underline underline-offset-2">
          Read more →
        </Link>
      </div>
    </article>
  );
}

// Vertical git-log line, newest on top; dots glow on current entries.
export function CareerTimeline({ items }: { items: CareerNode[] }) {
  return (
    <ol className="relative space-y-5 border-l border-line-strong pl-5 sm:pl-7">
      {items.map((n) => (
        <li key={n.id} className="relative">
          <span
            className={`absolute -left-[26px] top-5 h-[11px] w-[11px] rounded-full border-2 bg-background sm:-left-[34px] ${
              n.range.present ? "border-ok shadow-[0_0_8px_rgb(52_211_153/0.6)]" : "border-accent shadow-[0_0_8px_rgb(34_211_238/0.5)]"
            }`}
          />
          {n.range.start && (
            <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.15em] text-accent">
              {n.range.display.split(" – ")[0]}
            </p>
          )}
          <Card node={n} />
        </li>
      ))}
    </ol>
  );
}
