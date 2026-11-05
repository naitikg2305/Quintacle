"use client";

// Small display helpers shared by the Finances tabs. Formatting + display
// scaling only — every figure comes computed from the backend.

import { cn } from "@/lib/cn";

export const money = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString(undefined, { style: "currency", currency: "USD" });

export const pct = (n: number | null | undefined) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(2)}%`);

export const fmtDelta = (n: number | null | undefined) =>
  n == null ? "—" : `${n > 0 ? "▲" : n < 0 ? "▼" : "·"} ${money(Math.abs(n))}`;

export const toneOf = (n: number | null | undefined): "accent" | "ok" | "danger" =>
  n == null || n === 0 ? "accent" : n > 0 ? "ok" : "danger";

export const toneText = (n: number | null | undefined) => (n == null || n === 0 ? "" : n > 0 ? "text-ok" : "text-danger");

// A quiet proportional bar — value / max of its group.
export function Bar({ value, max, className, barClassName }: { value: number; max: number; className?: string; barClassName?: string }) {
  const w = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}>
      <div className={cn("h-full rounded-full bg-accent", barClassName)} style={{ width: `${w}%` }} />
    </div>
  );
}

// Plain-SVG sparkline over a series of numbers (oldest → newest).
export function Sparkline({ values, className }: { values: number[]; className?: string }) {
  if (values.length < 2) return null;
  const w = 100;
  const h = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - min) / span) * (h - 4)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cn("h-7 w-full", className)} aria-hidden>
      <polyline points={pts} fill="none" stroke="var(--color-accent)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// Fixed categorical palette for donuts/legends.
export const SLICE_COLORS = ["var(--color-accent)", "#a78bfa", "#f59e0b", "#34d399", "#f472b6", "#60a5fa", "#fb7185", "#facc15"];

export function Donut({ slices, label }: { slices: { key: string; pct: number }[]; label: string }) {
  const r = 40;
  const c = 2 * Math.PI * r;
  const lens = slices.map((s) => (Math.max(0, s.pct) / 100) * c);
  const offsets = lens.map((_, i) => lens.slice(0, i).reduce((a, b) => a + b, 0));
  return (
    <svg viewBox="0 0 100 100" className="mx-auto h-36 w-36 -rotate-90" role="img" aria-label={label}>
      <circle cx="50" cy="50" r={r} fill="none" stroke="var(--color-line)" strokeWidth="14" />
      {slices.map((s, i) => (
        <circle
          key={s.key}
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke={SLICE_COLORS[i % SLICE_COLORS.length]}
          strokeWidth="14"
          strokeDasharray={`${lens[i]} ${c - lens[i]}`}
          strokeDashoffset={-offsets[i]}
        >
          <title>{`${s.key} ${s.pct.toFixed(1)}%`}</title>
        </circle>
      ))}
    </svg>
  );
}

export function FieldLabel({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={cn("space-y-1 text-xs text-muted", className)}>
      <span>{label}</span>
      {children}
    </label>
  );
}
