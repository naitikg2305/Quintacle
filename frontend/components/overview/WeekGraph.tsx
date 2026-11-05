"use client";

import { useRouter } from "next/navigation";
import type { RecentGraph } from "@/lib/api";
import { nodeHref } from "@/components/overview/links";

// The overview's mini graph: this week's saved nodes on the outer ring, the
// things they link to (hubs like Minfy / Quintacle) on the inner ring. Plain
// radial layout computed here — no physics, it's a glance, the full
// interactive graph lives at /kb/graph.
export default function WeekGraph({ graph }: { graph: RecentGraph }) {
  const router = useRouter();
  const W = 680;
  const H = 300;
  const cx = W / 2;
  const cy = H / 2;

  const recent = graph.nodes.filter((n) => n.recent).slice(0, 18);
  const keep = new Set(recent.map((n) => n.id));
  const edges = graph.edges.filter((e) => keep.has(e.source) || keep.has(e.target));
  const linked = new Set(edges.flatMap((e) => [e.source, e.target]));
  const hubs = graph.nodes.filter((n) => !n.recent && linked.has(n.id)).slice(0, 8);
  hubs.forEach((n) => keep.add(n.id));

  const pos = new Map<string, { x: number; y: number }>();
  const ring = (list: { id: string }[], rx: number, ry: number, offset: number) =>
    list.forEach((n, i) => {
      const a = offset + (2 * Math.PI * i) / Math.max(list.length, 1);
      pos.set(n.id, { x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) });
    });
  if (hubs.length === 1) pos.set(hubs[0].id, { x: cx, y: cy });
  else ring(hubs, 70, 42, -Math.PI / 2);
  ring(recent, 200, 115, -Math.PI / 2 + 0.2);

  const degree = new Map<string, number>();
  edges.forEach((e) => [e.source, e.target].forEach((id) => degree.set(id, (degree.get(id) ?? 0) + 1)));
  const shown = edges.filter((e) => pos.has(e.source) && pos.has(e.target));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="This week's connections">
      {shown.map((e, i) => {
        const a = pos.get(e.source)!;
        const b = pos.get(e.target)!;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--color-line-strong)" strokeWidth={1} />;
      })}
      {[...hubs, ...recent].map((n) => {
        const p = pos.get(n.id)!;
        const hub = !n.recent;
        const r = hub ? 6 + Math.min(degree.get(n.id) ?? 0, 8) : 4;
        const href = nodeHref(n.id);
        const label = n.title.length > 20 ? `${n.title.slice(0, 19)}…` : n.title;
        const anchor = p.x < cx - 20 ? "end" : p.x > cx + 20 ? "start" : "middle";
        const dx = anchor === "end" ? -(r + 4) : anchor === "start" ? r + 4 : 0;
        const dy = anchor === "middle" ? r + 12 : 4;
        return (
          <g
            key={n.id}
            onClick={href ? () => router.push(href) : undefined}
            className={href ? "cursor-pointer" : undefined}
          >
            <title>{n.title}</title>
            <circle
              cx={p.x}
              cy={p.y}
              r={r}
              fill={hub ? "var(--color-accent)" : "var(--color-surface-2)"}
              stroke="var(--color-accent)"
              strokeWidth={hub ? 0 : 1.5}
              opacity={hub ? 0.9 : 1}
            />
            <text
              x={p.x + dx}
              y={p.y + dy}
              textAnchor={anchor}
              fontSize={hub ? 11 : 9.5}
              fill={hub ? "var(--color-foreground)" : "var(--color-muted)"}
              fontWeight={hub ? 600 : 400}
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
