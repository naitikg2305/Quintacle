"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { ForceGraphMethods } from "react-force-graph-3d";
import type { GraphEdge, GraphNode } from "@/lib/api";

export type Graph3DNode = GraphNode & { isHub?: boolean };

type FGNode = Graph3DNode & { x?: number; y?: number; z?: number };
type FGLink = { source: string | FGNode; target: string | FGNode; kind: string };

// The 3D view of /kb/graph. WebGL (three.js via 3d-force-graph), so it stays
// usable at thousands of nodes where the SVG view re-renders every DOM node
// per tick. Labels are hover tooltips rather than always-on text — always-on
// labels in 3D overlap into noise. Click a node to select it and fly to it.
export default function Graph3D({
  nodes,
  edges,
  colors,
  memberKind,
  selectedId,
  onSelect,
}: {
  nodes: Graph3DNode[];
  edges: GraphEdge[];
  colors: Record<string, string>;
  memberKind: string;
  selectedId: string | null;
  onSelect: (n: Graph3DNode) => void;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const fgRef = useRef<ForceGraphMethods<FGNode, FGLink> | undefined>(undefined);
  const [size, setSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height })
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Fresh copies: the force engine mutates nodes (x/y/z) and replaces link
  // endpoints with node objects, which must not leak into the 2D view's data.
  const data = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    return {
      nodes: nodes.map((n) => ({ ...n })) as FGNode[],
      links: edges
        .filter((e) => ids.has(e.source) && ids.has(e.target))
        .map((e) => ({ source: e.source, target: e.target, kind: e.kind })) as FGLink[],
    };
  }, [nodes, edges]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const link = fg.d3Force("link") as unknown as { distance?: (fn: (l: FGLink) => number) => void } | undefined;
    link?.distance?.((l) => (l.kind === memberKind ? 110 : 60));
    fg.d3ReheatSimulation();
  }, [data, memberKind]);

  function focus(n: FGNode) {
    onSelect(n);
    const fg = fgRef.current;
    if (!fg || n.x == null || n.y == null || n.z == null) return;
    const dist = 140;
    const r = Math.hypot(n.x, n.y, n.z) || 1;
    const k = 1 + dist / r;
    fg.cameraPosition({ x: n.x * k, y: n.y * k, z: n.z * k }, { x: n.x, y: n.y, z: n.z }, 800);
  }

  return (
    <div ref={wrapRef} className="h-full w-full">
      <ForceGraph3D<FGNode, FGLink>
        ref={fgRef}
        graphData={data}
        width={size.w}
        height={size.h}
        backgroundColor="#0a111d"
        showNavInfo={false}
        nodeId="id"
        nodeLabel={(n) => (n.isHub ? `<b>${escapeHtml(n.label)}</b>` : escapeHtml(n.label))}
        nodeColor={(n) => (n.id === selectedId ? "#ffffff" : colors[n.type] ?? "#888888")}
        nodeVal={(n) =>
          n.isHub ? 12 : (n.level === "continent" ? 6 : n.level === "country" ? 3 : n.level === "city" ? 1.5 : 1) * (n.id === selectedId ? 4 : 1)
        }
        nodeOpacity={0.9}
        nodeResolution={10}
        linkColor={(l) => (l.kind === memberKind ? "rgba(138,160,186,0.12)" : "rgba(138,160,186,0.55)")}
        linkWidth={(l) => (l.kind === memberKind ? 0 : 0.4)}
        enableNodeDrag={false}
        onNodeClick={(n) => focus(n)}
        cooldownTicks={300}
        onEngineStop={() => fgRef.current?.zoomToFit(600, 40)}
      />
    </div>
  );
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
