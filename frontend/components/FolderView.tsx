"use client";

import { File as FileIcon, FileText } from "lucide-react";
import { kbAssetUrl, KBEntryRow, KBView } from "@/lib/api";
import { Badge } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];

const extOf = (path: string) => path.split(".").pop()?.toLowerCase() ?? "";

// Frontmatter can hold anything — show scalars as-is, short lists inline, and
// collapse structured lists (sets, components...) to a count.
export function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) {
    return v.every((x) => x === null || typeof x !== "object") ? v.join(", ") : `${v.length} item${v.length === 1 ? "" : "s"}`;
  }
  if (typeof v === "object") return "{…}";
  return String(v);
}

// Any date field with "expir" in its name (expiry_date, expires...) becomes an
// automatic heads-up — expired, or due within 60 days. This is the Documents
// page's renewal warning, but for every folder, with no per-page code.
export function expiryStatus(meta: Record<string, unknown>): { tone: "danger" | "warn"; text: string } | null {
  for (const [k, v] of Object.entries(meta)) {
    if (!/expir/i.test(k) || typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(v)) continue;
    const days = Math.ceil((new Date(v).getTime() - Date.now()) / 86_400_000);
    if (days < 0) return { tone: "danger", text: "expired" };
    if (days <= 60) return { tone: "warn", text: `expires in ${days}d` };
  }
  return null;
}

export function scalarKeys(rows: KBEntryRow[]): string[] {
  const counts = new Map<string, number>();
  for (const r of rows) {
    for (const [k, v] of Object.entries(r.meta)) {
      if (v !== null && typeof v !== "object") counts.set(k, (counts.get(k) ?? 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
}

function sortRows(rows: KBEntryRow[], view: KBView): KBEntryRow[] {
  const dir = view.sort_dir === "desc" ? -1 : 1;
  const key = view.sort_by;
  return [...rows].sort((a, b) => {
    const av = key ? a.meta[key] : a.title;
    const bv = key ? b.meta[key] : b.title;
    if (av === bv) return 0;
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
  });
}

function Thumb({ folder, row, className }: { folder: string; row: KBEntryRow; className?: string }) {
  const image = row.assets.find((a) => IMAGE_EXT.includes(extOf(a)));
  if (image) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={kbAssetUrl(folder, image)} alt="" loading="lazy" className={cn("object-cover", className)} />;
  }
  const Icon = row.assets.length > 0 ? FileText : FileIcon;
  return (
    <div className={cn("flex items-center justify-center bg-surface-2 text-accent/60", className)}>
      <Icon size={28} />
    </div>
  );
}

function Badges({ row, keys }: { row: KBEntryRow; keys: string[] }) {
  const shown = keys.map((k) => ({ k, v: fmt(row.meta[k]) })).filter((x) => x.v);
  const expiry = expiryStatus(row.meta);
  if (shown.length === 0 && !expiry) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {expiry && <Badge tone={expiry.tone}>{expiry.text}</Badge>}
      {shown.map((x) => (
        <Badge key={x.k} tone="muted" className="normal-case tracking-normal">
          {x.v}
        </Badge>
      ))}
    </div>
  );
}

// The generic page: renders a folder's entries as a gallery, cards or a table
// from nothing but their frontmatter — so a new category needs no new page.
export default function FolderView({
  folder,
  rows,
  view,
  activeSlug,
  onOpen,
}: {
  folder: string;
  rows: KBEntryRow[];
  view: KBView;
  activeSlug: string | null;
  onOpen: (slug: string) => void;
}) {
  const sorted = sortRows(rows, view);
  const active = (slug: string) => activeSlug === slug;

  if (view.layout === "gallery") {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3">
        {sorted.map((r) => (
          <button
            key={r.slug}
            onClick={() => onOpen(r.slug)}
            className={cn(
              "overflow-hidden rounded-lg border text-left transition-colors",
              active(r.slug) ? "border-accent/70 shadow-glow" : "border-line hover:border-accent/40"
            )}
          >
            <Thumb folder={folder} row={r} className="aspect-square w-full" />
            <div className="space-y-1 p-2">
              <p className="truncate text-xs font-medium">{r.title}</p>
              <Badges row={r} keys={view.badges} />
            </div>
          </button>
        ))}
      </div>
    );
  }

  if (view.layout === "cards") {
    const detailKeys = view.columns.length > 0 ? view.columns : scalarKeys(rows).filter((k) => !view.badges.includes(k)).slice(0, 3);
    return (
      <div className="space-y-2">
        {sorted.map((r) => (
          <button
            key={r.slug}
            onClick={() => onOpen(r.slug)}
            className={cn(
              "flex w-full gap-3 rounded-lg border p-2.5 text-left transition-colors",
              active(r.slug) ? "border-accent/70 bg-accent/10" : "border-line hover:border-accent/40"
            )}
          >
            {r.assets.length > 0 && <Thumb folder={folder} row={r} className="h-14 w-14 shrink-0 rounded-md" />}
            <div className="min-w-0 flex-1 space-y-1">
              <p className="truncate text-sm font-medium">{r.title}</p>
              <Badges row={r} keys={view.badges} />
              <p className="truncate text-xs text-muted">
                {detailKeys
                  .map((k) => ({ k, v: fmt(r.meta[k]) }))
                  .filter((x) => x.v)
                  .map((x) => `${x.k.replace(/_/g, " ")}: ${x.v}`)
                  .join(" · ") || r.snippet}
              </p>
            </div>
          </button>
        ))}
      </div>
    );
  }

  // table
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-line bg-surface-2/60 font-mono text-[10px] uppercase tracking-wider text-muted">
            <th className="px-2.5 py-2 font-normal">Name</th>
            {view.columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-2.5 py-2 font-normal">
                {c.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.slug}
              onClick={() => onOpen(r.slug)}
              className={cn(
                "cursor-pointer border-b border-line last:border-b-0 transition-colors",
                active(r.slug) ? "bg-accent/10" : "hover:bg-white/5"
              )}
            >
              <td className="max-w-[10rem] truncate px-2.5 py-2 font-medium">{r.title}</td>
              {view.columns.map((c) => (
                <td key={c} className="whitespace-nowrap px-2.5 py-2 text-muted">
                  {fmt(r.meta[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
