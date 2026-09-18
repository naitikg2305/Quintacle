"use client";

import { useEffect, useRef, useState } from "react";
import { forceCenter, forceLink, forceManyBody, forceSimulation, SimulationNodeDatum } from "d3-force";
import { getGraph, GraphEdge, GraphNode } from "@/lib/api";

type SimNode = GraphNode & SimulationNodeDatum;

const COLORS: Record<string, string> = {
  note: "#4f8ef7",
  asset: "#f7b84f",
  journal_day: "#9b59f6",
  ingredient: "#2ecc71",
  meal: "#16a085",
  routine: "#e74c3c",
  exercise: "#e67e22",
  wardrobe_item: "#f39c12",
  outfit: "#d35400",
};

const WIDTH = 900;
const HEIGHT = 600;

// Everything already connected across the app, in one view — KB note links
// (frontmatter, AI-proposed, never in the note body itself), notes to their
// photos, photos to the journal day they were taken on (EXIF date match),
// meals to their real ingredients, routines to their exercises, outfits to
// their items. Force layout via d3-force; rendered as plain SVG, no
// dependency on a full graph-rendering library.
export default function GraphPage() {
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(new Set(Object.keys(COLORS)));
  const [tick, setTick] = useState(0);
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null);

  useEffect(() => {
    getGraph().then(({ nodes: rawNodes, edges: rawEdges }) => {
      const simNodes: SimNode[] = rawNodes.map((n) => ({ ...n }));
      setNodes(simNodes);
      setEdges(rawEdges);

      const sim = forceSimulation<SimNode>(simNodes)
        .force(
          "link",
          forceLink<SimNode, GraphEdge>(rawEdges.map((e) => ({ ...e })))
            .id((d) => d.id)
            .distance(70)
        )
        .force("charge", forceManyBody().strength(-120))
        .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
        .on("tick", () => setTick((t) => t + 1));
      simRef.current = sim;
    });
    return () => {
      simRef.current?.stop();
    };
  }, []);

  function toggleType(type: string) {
    setVisibleTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  const shownNodes = nodes.filter((n) => visibleTypes.has(n.type));
  const shownIds = new Set(shownNodes.map((n) => n.id));
  const nodesById = new Map(nodes.map((n) => [n.id, n]));

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      <h1 className="text-2xl font-semibold">Graph</h1>
      <p className="text-sm opacity-60 -mt-2">
        Everything connected: notes to each other, notes to their photos, photos to the day you journaled about them, meals to
        ingredients, routines to exercises, outfits to items.
      </p>

      <div className="flex flex-wrap gap-3 text-xs">
        {Object.entries(COLORS).map(([type, color]) => (
          <label key={type} className="flex items-center gap-1 cursor-pointer">
            <input type="checkbox" checked={visibleTypes.has(type)} onChange={() => toggleType(type)} />
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            {type.replace("_", " ")}
          </label>
        ))}
      </div>

      <div className="flex gap-4">
        <div className="border rounded overflow-hidden" style={{ width: WIDTH, height: HEIGHT }}>
          {nodes.length === 0 ? (
            <p className="text-sm opacity-60 p-4">Nothing to graph yet — drop something first.</p>
          ) : (
            <svg width={WIDTH} height={HEIGHT} key={tick}>
              {edges.map((e, i) => {
                const s = nodesById.get(typeof e.source === "string" ? e.source : (e.source as unknown as SimNode).id);
                const t = nodesById.get(typeof e.target === "string" ? e.target : (e.target as unknown as SimNode).id);
                if (!s || !t || !shownIds.has(s.id) || !shownIds.has(t.id)) return null;
                return (
                  <line
                    key={i}
                    x1={s.x ?? 0}
                    y1={s.y ?? 0}
                    x2={t.x ?? 0}
                    y2={t.y ?? 0}
                    stroke="currentColor"
                    strokeOpacity={0.2}
                  />
                );
              })}
              {shownNodes.map((n) => (
                <g key={n.id} onClick={() => setSelected(n)} className="cursor-pointer">
                  <circle cx={n.x ?? 0} cy={n.y ?? 0} r={selected?.id === n.id ? 8 : 5} fill={COLORS[n.type] ?? "#888"} />
                  <text x={(n.x ?? 0) + 8} y={(n.y ?? 0) + 3} fontSize={10} fill="currentColor" opacity={0.7}>
                    {n.label.length > 24 ? n.label.slice(0, 24) + "…" : n.label}
                  </text>
                </g>
              ))}
            </svg>
          )}
        </div>

        <div className="w-64 shrink-0">
          {selected ? (
            <div className="border rounded p-3 space-y-1 text-sm">
              <span
                className="inline-block px-2 py-0.5 rounded text-xs text-white"
                style={{ backgroundColor: COLORS[selected.type] ?? "#888" }}
              >
                {selected.type.replace("_", " ")}
              </span>
              <p className="font-medium">{selected.label}</p>
              {selected.folder && <p className="text-xs opacity-60">{selected.folder}</p>}
              {selected.location && (
                <p className="text-xs opacity-60">
                  {selected.location.lat.toFixed(4)}, {selected.location.lon.toFixed(4)}
                </p>
              )}
              {selected.type === "note" && selected.folder && selected.slug && (
                <a
                  href={`/kb/browse?folder=${encodeURIComponent(selected.folder)}&slug=${encodeURIComponent(selected.slug)}`}
                  className="text-xs underline opacity-70 hover:opacity-100 inline-block mt-1"
                >
                  open note →
                </a>
              )}
            </div>
          ) : (
            <p className="text-sm opacity-60">Click a node for details.</p>
          )}
        </div>
      </div>
    </div>
  );
}
