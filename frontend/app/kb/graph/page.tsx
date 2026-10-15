"use client";

import { useEffect, useRef, useState } from "react";
import { forceCenter, forceLink, forceManyBody, forceSimulation, SimulationNodeDatum } from "d3-force";
import { getGraph, GraphEdge, GraphNode } from "@/lib/api";

type SimNode = GraphNode & SimulationNodeDatum;
type ViewBox = { x: number; y: number; w: number; h: number };

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
const FIT_PAD = 60;

// Everything already connected across the app, in one view — KB note links
// (frontmatter, AI-proposed, never in the note body itself), notes to their
// photos, photos to the journal day they were taken on (EXIF date match),
// meals to their real ingredients, routines to their exercises, outfits to
// their items. Force layout via d3-force; rendered as plain SVG, no
// dependency on a full graph-rendering library. The canvas is a pannable/
// zoomable viewBox that auto-fits the whole layout once the simulation
// settles — the force layout happily spreads a real KB far beyond any fixed
// window, so a fixed viewport only ever showed one corner of it.
export default function GraphPage() {
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(new Set(Object.keys(COLORS)));
  const [, setTick] = useState(0);
  const [viewBox, setViewBox] = useState<ViewBox>({ x: 0, y: 0, w: WIDTH, h: HEIGHT });
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const drag = useRef<{ startX: number; startY: number; vb: ViewBox } | null>(null);

  function fitToContent() {
    const pts = nodesRef.current.filter((n) => n.x != null && n.y != null);
    if (pts.length === 0) return;
    const xs = pts.map((n) => n.x as number);
    const ys = pts.map((n) => n.y as number);
    const minX = Math.min(...xs) - FIT_PAD;
    const minY = Math.min(...ys) - FIT_PAD;
    const w = Math.max(...xs) - minX + FIT_PAD;
    const h = Math.max(...ys) - minY + FIT_PAD;
    setViewBox({ x: minX, y: minY, w, h });
  }

  useEffect(() => {
    getGraph().then(({ nodes: rawNodes, edges: rawEdges }) => {
      const simNodes: SimNode[] = rawNodes.map((n) => ({ ...n }));
      setNodes(simNodes);
      nodesRef.current = simNodes;
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
        .on("tick", () => setTick((t) => t + 1))
        .on("end", fitToContent);
      simRef.current = sim;
    });
    return () => {
      simRef.current?.stop();
    };
  }, []);

  // Wheel zoom around the cursor. Attached by hand because React's onWheel
  // can't preventDefault (passive) — without it the page scrolls instead.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      setViewBox((vb) => {
        const rect = svg!.getBoundingClientRect();
        const px = vb.x + ((e.clientX - rect.left) / rect.width) * vb.w;
        const py = vb.y + ((e.clientY - rect.top) / rect.height) * vb.h;
        const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
        const w = Math.min(Math.max(vb.w * factor, 60), 20000);
        const h = (w / vb.w) * vb.h;
        return { x: px - ((px - vb.x) / vb.w) * w, y: py - ((py - vb.y) / vb.h) * h, w, h };
      });
    }
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [nodes.length]);

  function onPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    drag.current = { startX: e.clientX, startY: e.clientY, vb: viewBox };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!drag.current || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const { startX, startY, vb } = drag.current;
    setViewBox({
      ...vb,
      x: vb.x - ((e.clientX - startX) / rect.width) * vb.w,
      y: vb.y - ((e.clientY - startY) / rect.height) * vb.h,
    });
  }

  function onPointerUp() {
    drag.current = null;
  }

  function zoom(factor: number) {
    setViewBox((vb) => {
      const w = Math.min(Math.max(vb.w * factor, 60), 20000);
      const h = (w / vb.w) * vb.h;
      return { x: vb.x + (vb.w - w) / 2, y: vb.y + (vb.h - h) / 2, w, h };
    });
  }

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
  // Labels and dots keep a constant on-screen size regardless of zoom level,
  // or zooming out turns the graph into unreadable ant text.
  const scale = viewBox.w / WIDTH;

  return (
    <div className="space-y-4 mx-auto">
      <h1 className="text-2xl font-semibold">Graph</h1>
      <p className="text-sm opacity-60 -mt-2">
        Everything connected: notes to each other, notes to their photos, photos to the day you journaled about them, meals to
        ingredients, routines to exercises, outfits to items. Drag to pan, scroll to zoom.
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

      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="relative min-w-0 flex-1 overflow-hidden rounded border" style={{ height: "70vh" }}>
          {nodes.length === 0 ? (
            <p className="text-sm opacity-60 p-4">Nothing to graph yet — drop something first.</p>
          ) : (
            <>
              <svg
                ref={svgRef}
                className="h-full w-full touch-none cursor-grab active:cursor-grabbing"
                viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
                preserveAspectRatio="xMidYMid meet"
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerLeave={onPointerUp}
              >
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
                      strokeWidth={scale}
                    />
                  );
                })}
                {shownNodes.map((n) => (
                  <g
                    key={n.id}
                    onClick={() => setSelected(n)}
                    onPointerDown={(e) => e.stopPropagation()}
                    className="cursor-pointer"
                  >
                    <circle
                      cx={n.x ?? 0}
                      cy={n.y ?? 0}
                      r={(selected?.id === n.id ? 8 : 5) * scale}
                      fill={COLORS[n.type] ?? "#888"}
                    />
                    <text
                      x={(n.x ?? 0) + 8 * scale}
                      y={(n.y ?? 0) + 3 * scale}
                      fontSize={10 * scale}
                      fill="currentColor"
                      opacity={0.7}
                    >
                      {n.label.length > 24 ? n.label.slice(0, 24) + "…" : n.label}
                    </text>
                  </g>
                ))}
              </svg>
              <div className="absolute right-2 top-2 flex flex-col gap-1">
                <button onClick={() => zoom(1 / 1.3)} aria-label="Zoom in" className="h-7 w-7 rounded border bg-background/80 text-sm hover:bg-accent/10">
                  +
                </button>
                <button onClick={() => zoom(1.3)} aria-label="Zoom out" className="h-7 w-7 rounded border bg-background/80 text-sm hover:bg-accent/10">
                  −
                </button>
                <button onClick={fitToContent} aria-label="Fit graph" className="h-7 w-7 rounded border bg-background/80 text-[10px] hover:bg-accent/10">
                  FIT
                </button>
              </div>
            </>
          )}
        </div>

        <div className="w-full shrink-0 lg:w-64">
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
                  href={`/kb/browse?path=${encodeURIComponent(selected.folder)}&open=${encodeURIComponent(selected.slug)}`}
                  className="text-xs underline opacity-70 hover:opacity-100 inline-block mt-1"
                >
                  open note →
                </a>
              )}
            </div>
          ) : (
            <p className="text-sm opacity-60">Click a node for details. Drag the canvas to pan, scroll to zoom, FIT to see everything.</p>
          )}
        </div>
      </div>
    </div>
  );
}
