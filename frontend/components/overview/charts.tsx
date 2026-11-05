"use client";

import { useState, type ReactNode } from "react";

// Plain-SVG dashboard charts (2026-11-05) — no chart dependency. Every
// number here is computed by the caller; these only draw.

// Categorical slots, stepped for the dark HUD surface (dataviz reference
// palette, dark column). Assigned in fixed order; past 7 folds to "Other".
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9", "#e66767"];
export const OTHER = "#5b6b80";

/** Progress ring. `value` and `marker` are 0..1+ fractions of the target. */
export function Ring({
  value,
  marker,
  color,
  size = 64,
  stroke = 6,
  children,
  label,
}: {
  value: number;
  marker?: number;
  color: string;
  size?: number;
  stroke?: number;
  children?: ReactNode;
  label: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  const m = marker == null ? null : Math.max(0, Math.min(1, marker));
  const mAngle = m == null ? 0 : m * 2 * Math.PI - Math.PI / 2;
  const mid = size / 2;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
        <circle cx={mid} cy={mid} r={r} fill="none" stroke="rgb(56 189 248 / 0.12)" strokeWidth={stroke} />
        <circle
          cx={mid}
          cy={mid}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${v * c} ${c}`}
          transform={`rotate(-90 ${mid} ${mid})`}
          style={{ filter: `drop-shadow(0 0 4px ${color})` }}
        />
        {m != null && m > 0 && m < 1 && (
          <line
            x1={mid + (r - stroke) * Math.cos(mAngle)}
            y1={mid + (r - stroke) * Math.sin(mAngle)}
            x2={mid + (r + stroke) * Math.cos(mAngle)}
            y2={mid + (r + stroke) * Math.sin(mAngle)}
            stroke="#dbe6f5"
            strokeWidth={2}
            strokeLinecap="round"
            opacity={0.85}
          />
        )}
      </svg>
      {children && <div className="absolute inset-0 grid place-items-center text-center">{children}</div>}
    </div>
  );
}

/** Horizontal meter vs a target; `marker` draws a tick (e.g. prorated pace). */
export function Meter({ value, max, color, marker }: { value: number; max: number; color: string; marker?: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color, boxShadow: `0 0 8px ${color}` }} />
      {marker != null && max > 0 && marker < max && (
        <span className="absolute inset-y-0 w-0.5 bg-foreground/70" style={{ left: `${(marker / max) * 100}%` }} />
      )}
    </div>
  );
}

export type Point = { x: string; y: number; label: string };

/** Area sparkline with hover readout. Points must be oldest first; x is an
 *  ISO date used for horizontal placement between `start` and `end`. */
export function Sparkline({
  points,
  start,
  end,
  height = 96,
  color = "#22d3ee",
  format,
}: {
  points: Point[];
  start: string;
  end: string;
  height?: number;
  color?: string;
  format: (y: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 320;
  const H = height;
  const padY = 10;
  const t0 = Date.parse(`${start}T00:00:00Z`);
  const t1 = Date.parse(`${end}T00:00:00Z`);
  const span = Math.max(1, t1 - t0);
  const ys = points.map((p) => p.y);
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const range = hi - lo || 1;
  const px = (p: Point) => ((Date.parse(`${p.x}T00:00:00Z`) - t0) / span) * (W - 8) + 4;
  const py = (y: number) => padY + (1 - (y - lo) / range) * (H - padY * 2);
  const coords = points.map((p) => [px(p), py(p.y)] as const);
  const line = coords.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = coords.length > 1 ? `${line} L${coords[coords.length - 1][0].toFixed(1)},${H} L${coords[0][0].toFixed(1)},${H} Z` : "";
  const h = hover != null ? points[hover] : null;
  const gid = "spark-grad";

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="block h-24 w-full touch-none"
        role="img"
        aria-label={`Trend from ${format(points[0].y)} to ${format(points[points.length - 1].y)}`}
        onPointerMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = ((e.clientX - rect.left) / rect.width) * W;
          let best = 0;
          coords.forEach(([cx], i) => {
            if (Math.abs(cx - x) < Math.abs(coords[best][0] - x)) best = i;
          });
          setHover(best);
        }}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.32} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={W} y1={H * f} y2={H * f} stroke="rgb(56 189 248 / 0.07)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        {area && <path d={area} fill={`url(#${gid})`} />}
        <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {hover != null && (
          <line x1={coords[hover][0]} x2={coords[hover][0]} y1={0} y2={H} stroke="rgb(219 230 245 / 0.35)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {/* Dots drawn in HTML so they stay round under preserveAspectRatio="none". */}
      {coords.map(([x, y], i) =>
        i === coords.length - 1 || i === hover ? (
          <span
            key={i}
            className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
            style={{ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%`, background: color, boxShadow: `0 0 8px ${color}` }}
          />
        ) : null
      )}
      {h && hover != null && (
        <div
          className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-line-strong bg-surface px-2 py-1 font-mono text-[11px] text-foreground shadow-glow"
          style={{ left: `${Math.min(88, Math.max(12, (coords[hover][0] / W) * 100))}%` }}
        >
          {format(h.y)} <span className="text-muted">· {h.label}</span>
        </div>
      )}
    </div>
  );
}

export type StackDay = { label: string; title: string; segments: { key: string; value: number }[] };

/** Daily stacked columns (Mon..Sun). Colors come from `colorOf(key)`. */
export function StackedColumns({
  days,
  colorOf,
  highlight,
  unit = "h",
}: {
  days: StackDay[];
  colorOf: (key: string) => string;
  highlight?: number;
  unit?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const totals = days.map((d) => d.segments.reduce((s, x) => s + x.value, 0));
  const max = Math.max(1, ...totals);
  return (
    <div className="relative">
      <div className="flex h-28 items-end gap-1.5">
        {days.map((d, i) => {
          const total = totals[i];
          return (
            <button
              key={i}
              type="button"
              className="group flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1 outline-none"
              onPointerEnter={() => setHover(i)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              aria-label={`${d.title}: ${Math.round(total * 10) / 10}${unit}`}
            >
              <div
                className="flex w-full max-w-7 flex-col-reverse gap-[2px] overflow-hidden rounded-t-[4px]"
                style={{ height: `${(total / max) * 100}%`, minHeight: total > 0 ? 3 : 0 }}
              >
                {d.segments
                  .filter((s) => s.value > 0)
                  .map((s) => (
                    <div key={s.key} style={{ flexGrow: s.value, background: colorOf(s.key) }} className="min-h-[2px] opacity-90 group-hover:opacity-100" />
                  ))}
              </div>
              {total === 0 && <div className="h-[2px] w-full max-w-7 rounded bg-white/10" />}
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1.5">
        {days.map((d, i) => (
          <span key={i} className={`flex-1 text-center font-mono text-[10px] ${i === highlight ? "text-accent" : "text-muted"}`}>
            {d.label}
          </span>
        ))}
      </div>
      {hover != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 -translate-y-full rounded-md border border-line-strong bg-surface px-2 py-1 font-mono text-[11px] shadow-glow"
          style={{ left: `${Math.min(85, Math.max(15, ((hover + 0.5) / days.length) * 100))}%` }}
        >
          <p className="text-foreground">
            {days[hover].title} · {Math.round(totals[hover] * 10) / 10}
            {unit}
          </p>
          {days[hover].segments
            .filter((s) => s.value > 0)
            .map((s) => (
              <p key={s.key} className="flex items-center gap-1.5 text-muted">
                <span className="h-2 w-2 rounded-sm" style={{ background: colorOf(s.key) }} />
                {s.key} {Math.round(s.value * 10) / 10}
                {unit}
              </p>
            ))}
        </div>
      )}
    </div>
  );
}
