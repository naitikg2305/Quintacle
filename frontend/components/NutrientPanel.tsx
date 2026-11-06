"use client";

import { useEffect, useState } from "react";
import {
  getUsdaDbStatus,
  installUsdaDb,
  NutrientPanelData,
  NutrientSource,
  PanelNutrient,
  UsdaDbStatus,
} from "@/lib/nutritionApi";

// 2026-11-05 — the full nutrient panel (Macros · Vitamins · Minerals · Fatty
// acids · Flavonoids · Carotenoids · Other). Shared by the Day view, the meal
// composer and the ingredient preset card. Display only: totals, % of
// target, contributions and the omega-6:omega-3 ratio all arrive computed.

const DEFAULT_OPEN = new Set(["Macros", "Vitamins", "Minerals", "Fatty acids"]);

function fmt(amount: number): string {
  if (amount === 0) return "0";
  const a = Math.abs(amount);
  if (a >= 100) return amount.toFixed(0);
  if (a >= 10) return amount.toFixed(1);
  if (a >= 1) return amount.toFixed(2).replace(/0$/, "");
  return amount.toPrecision(2);
}

export function SourceBadge({ source }: { source: NutrientSource | string }) {
  if (!source) return null;
  const style: Record<string, string> = {
    usda: "border-emerald-500/40 text-emerald-400",
    label: "border-sky-500/40 text-sky-400",
    estimated: "border-amber-500/40 text-amber-400",
    mixed: "border-line text-muted",
  };
  const text: Record<string, string> = { usda: "USDA", label: "label", estimated: "est.", mixed: "mixed" };
  return (
    <span className={`shrink-0 rounded border px-1 font-mono text-[9px] uppercase leading-4 ${style[source] ?? "border-line text-muted"}`}>
      {text[source] ?? source}
    </span>
  );
}

function Row({ n, showContrib }: { n: PanelNutrient; showContrib: boolean }) {
  const [open, setOpen] = useState(false);
  const top = n.contributions[0];
  const canOpen = showContrib && n.contributions.length > 0;
  return (
    <li className={`border-b border-line/60 py-1 last:border-b-0 ${n.has_data ? "" : "opacity-45"}`}>
      <button
        type="button"
        className="flex w-full min-w-0 items-center gap-2 text-left text-xs"
        onClick={() => canOpen && setOpen(!open)}
        aria-expanded={canOpen ? open : undefined}
      >
        <span className="min-w-0 flex-1 truncate">
          {n.nutrient}
          {n.is_limit ? <span className="text-muted"> (limit)</span> : null}
        </span>
        <span className="shrink-0 whitespace-nowrap font-mono text-muted">
          {n.has_data ? `${n.approx ? "≈" : ""}${fmt(n.amount)} ${n.unit}` : "no data"}
        </span>
        <span className="w-14 shrink-0">
          {n.pct !== null && (
            <span className="block h-1.5 overflow-hidden rounded bg-white/10">
              <span
                className={`block h-full ${n.is_limit && n.pct > 100 ? "bg-danger" : "bg-accent"}`}
                style={{ width: `${Math.min(100, n.pct)}%` }}
              />
            </span>
          )}
        </span>
        <span className="w-10 shrink-0 text-right font-mono text-[11px] text-muted">
          {n.pct !== null ? `${n.pct.toFixed(0)}%` : n.reference ? "ref" : "—"}
        </span>
        <span className="w-11 shrink-0 text-right">{n.has_data && <SourceBadge source={n.source} />}</span>
      </button>
      {showContrib && top && n.contributions.length > 1 && !open && (
        <p className="truncate pl-1 text-[10px] text-muted">
          {top.pct.toFixed(0)}% from {top.name}
        </p>
      )}
      {open && (
        <div className="mt-1 space-y-0.5 rounded bg-surface-2/60 p-1.5 text-[11px]">
          {n.contributions.map((c) => (
            <div key={c.name} className="flex min-w-0 items-center gap-2">
              <span className="min-w-0 flex-1 truncate">{c.name}</span>
              <span className="font-mono text-muted">
                {fmt(c.amount)} {n.unit}
              </span>
              <span className="w-10 text-right font-mono text-muted">{c.pct.toFixed(0)}%</span>
              <span className="w-11 text-right">
                <SourceBadge source={c.source} />
              </span>
            </div>
          ))}
          {n.coverage.with_data < n.coverage.of && (
            <p className="text-muted">
              Only {n.coverage.with_data} of {n.coverage.of} items have data for this — the rest are unknown, not zero.
            </p>
          )}
        </div>
      )}
      {open && n.target && (
        <p className="pl-1 text-[10px] text-muted">
          target {fmt(n.target.amount)} {n.target.unit} · {n.target.kind}
        </p>
      )}
      {n.reference && (open || !n.target) && n.has_data && (
        <p className="pl-1 text-[10px] text-muted">
          {n.reference.low}–{n.reference.high} {n.reference.unit}: {n.reference.label}
        </p>
      )}
    </li>
  );
}

export default function NutrientPanel({ data, title }: { data: NutrientPanelData; title?: string }) {
  const [openGroups, setOpenGroups] = useState<Set<string>>(DEFAULT_OPEN);
  const [showEmpty, setShowEmpty] = useState(false);
  const showContrib = data.components.length > 1;
  const ratio = data.computed.omega6_to_omega3;
  const epaDha = data.computed.epa_dha;

  function toggle(g: string) {
    const next = new Set(openGroups);
    if (next.has(g)) next.delete(g);
    else next.add(g);
    setOpenGroups(next);
  }

  const emptyCount = data.groups.reduce((s, g) => s + g.nutrients.filter((n) => !n.has_data).length, 0);

  return (
    <div className="min-w-0 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent">{title ?? "All nutrients"}</h4>
        {emptyCount > 0 && (
          <button type="button" className="text-[10px] text-muted underline" onClick={() => setShowEmpty(!showEmpty)}>
            {showEmpty ? "hide" : "show"} {emptyCount} with no data
          </button>
        )}
      </div>
      {data.groups.map((g) => {
        const rows = g.nutrients.filter((n) => showEmpty || n.has_data);
        const isOpen = openGroups.has(g.group);
        const withData = g.nutrients.filter((n) => n.has_data).length;
        return (
          <section key={g.group} className="rounded-lg border border-line bg-surface-2/40">
            <button
              type="button"
              onClick={() => toggle(g.group)}
              className="flex w-full items-center justify-between px-2 py-1.5 text-xs font-medium"
              aria-expanded={isOpen}
            >
              <span>{g.group}</span>
              <span className="text-[10px] font-normal text-muted">
                {withData}/{g.nutrients.length} with data {isOpen ? "▾" : "▸"}
              </span>
            </button>
            {isOpen && (
              <div className="px-2 pb-1.5">
                {g.group === "Fatty acids" && (ratio || epaDha) && (
                  <div className="mb-1 space-y-0.5 rounded bg-surface-2/60 p-1.5 text-[11px]">
                    {ratio && (
                      <p>
                        omega-6 : omega-3 <span className="font-mono">{ratio.value}:1</span>{" "}
                        <span className="text-muted">({ratio.label})</span>
                      </p>
                    )}
                    {epaDha && (
                      <p>
                        EPA + DHA <span className="font-mono">{fmt(epaDha.amount_mg)} mg</span>
                        {epaDha.reference && <span className="text-muted"> · {epaDha.reference.label}</span>}
                      </p>
                    )}
                  </div>
                )}
                {rows.length === 0 ? (
                  <p className="py-1 text-[11px] text-muted">No data for this group in these foods.</p>
                ) : (
                  <ul>
                    {rows.map((n) => (
                      <Row key={n.nutrient} n={n} showContrib={showContrib} />
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
        );
      })}
      <p className="text-[10px] text-muted">≈ = USDA&apos;s undifferentiated isomer total used as a stand-in. Tap a row for what contributed.</p>
    </div>
  );
}

// "Nutrition database: not installed — download (≈XX MB)". Calls the
// backend install job and polls its status; renders nothing once installed
// unless `always` (then a one-line status).
export function UsdaDbNotice({ always = false }: { always?: boolean }) {
  const [status, setStatus] = useState<UsdaDbStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = () =>
      getUsdaDbStatus()
        .then((s) => {
          if (cancelled) return;
          setStatus(s);
          if (s.job.state === "running") timer = setTimeout(poll, 2000);
        })
        .catch(() => !cancelled && setError("couldn't reach the backend"));
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [status?.job.state]);

  if (!status) return error ? <p className="text-[10px] text-muted">Nutrition database: {error}</p> : null;
  if (status.installed && status.job.state !== "running") {
    if (!always || !status.summary) return null;
    return (
      <p className="text-[10px] text-muted">
        Nutrition database: USDA FoodData Central, {status.summary.foods.toLocaleString()} foods ·{" "}
        {(status.summary.size_bytes / 1e6).toFixed(1)} MB
      </p>
    );
  }
  const running = status.job.state === "running";
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface-2/50 p-2 text-xs">
      <span className="min-w-0 flex-1">
        {running
          ? `Installing nutrition database… ${status.job.step}`
          : `Nutrition database: not installed — numbers are AI estimates until you download USDA data (≈${status.approx_download_mb} MB).`}
        {status.job.state === "error" && <span className="block text-danger">Install failed: {status.job.error}</span>}
      </span>
      {!running && (
        <button
          type="button"
          className="rounded border border-line px-2 py-1"
          onClick={() =>
            installUsdaDb()
              .then(() => setStatus({ ...status, job: { ...status.job, state: "running", step: "starting" } }))
              .catch(() => setError("install request failed"))
          }
        >
          Download
        </button>
      )}
    </div>
  );
}
