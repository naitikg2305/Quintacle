"use client";

import { useEffect, useState } from "react";
import NutrientPanel, { SourceBadge } from "@/components/NutrientPanel";
import {
  BreakdownComponent,
  getNutrientBreakdown,
  getUsdaFood,
  matchUsdaFood,
  NutrientPanelData,
  UsdaCandidate,
  UsdaFoodFields,
} from "@/lib/nutritionApi";

// 2026-11-05 — the owner's override of a USDA match: shows which USDA entry
// the numbers came from, lets them pick another candidate (or search), and
// applies that food's real per-gram numbers. Never edits a number itself.
type Props = {
  name: string;
  grams: number;
  source?: string;
  fdcId?: number | null;
  description?: string;
  candidates?: UsdaCandidate[];
  onApply: (fields: UsdaFoodFields, candidates: UsdaCandidate[]) => void;
};

export default function UsdaMatchPicker({ name, grams, source, fdcId, description, candidates = [], onApply }: Props) {
  const [list, setList] = useState<UsdaCandidate[]>(candidates);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  async function pick(fdc: number, from: UsdaCandidate[]) {
    setBusy(true);
    try {
      onApply(await getUsdaFood(fdc, grams || 100), from);
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  async function search() {
    const q = query.trim() || name;
    if (!q) return;
    setBusy(true);
    try {
      const res = await matchUsdaFood(q);
      setList(res.candidates);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-w-0 space-y-1 text-[11px]">
      <div className="flex min-w-0 items-center gap-1.5">
        <SourceBadge source={source || "estimated"} />
        <span className="min-w-0 flex-1 truncate text-muted" title={description}>
          {source === "usda" || (source === "label" && fdcId)
            ? `${source === "label" ? "label · gaps from " : ""}USDA: ${description ?? ""}`
            : source === "label"
              ? "values from the label"
              : "AI estimate — no USDA match picked"}
        </span>
        <button type="button" className="shrink-0 underline" onClick={() => setOpen(!open)}>
          {open ? "close" : "change match"}
        </button>
      </div>
      {open && (
        <div className="space-y-1 rounded border border-line p-1.5">
          <div className="flex gap-1">
            <input
              className="min-w-0 flex-1 rounded border px-1 py-0.5"
              placeholder={`search USDA (default: ${name || "name"})`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
            />
            <button type="button" className="rounded border px-2" disabled={busy} onClick={search}>
              search
            </button>
          </div>
          {list.length === 0 && <p className="text-muted">No candidates yet — search above.</p>}
          <ul className="max-h-48 space-y-0.5 overflow-y-auto">
            {list.map((c) => (
              <li key={c.fdc_id}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => pick(c.fdc_id, list)}
                  className={`w-full rounded px-1 py-0.5 text-left hover:bg-white/5 ${c.fdc_id === fdcId ? "bg-accent/15" : ""}`}
                >
                  {c.description} <span className="text-muted">· {c.source === "foundation" ? "Foundation" : "SR Legacy"}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// The live full-panel preview for unsaved drafts (preset card, composer).
// Debounced; the backend does every sum.
export function DraftNutrientPanel({ components, title }: { components: BreakdownComponent[]; title?: string }) {
  const [data, setData] = useState<NutrientPanelData | null>(null);
  const key = JSON.stringify(components);
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      getNutrientBreakdown(JSON.parse(key))
        .then((d) => !cancelled && setData(d))
        .catch(() => !cancelled && setData(null));
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [key]);
  if (!data) return null;
  return <NutrientPanel data={data} title={title} />;
}
