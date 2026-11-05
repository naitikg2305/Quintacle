// Knowledge page client (2026-11-05) — GET /knowledge + GET /knowledge/note
// (core/quintacle_core/nodes/knowledge/). Kept out of lib/api.ts so the
// parallel page builds don't collide in one file.
import { API_BASE } from "@/lib/api";

export type KnowledgeTopic = {
  topic: string; // "tech-notes/graphs" (relative to knowledge/)
  name: string; // "Graphs"
  label: string; // "Tech Notes › Graphs"
  folder: string; // "knowledge/tech-notes/graphs"
  count: number; // notes in the whole subtree
  direct_count: number;
  description: string; // the folder's about-* charter, first paragraph
  children: KnowledgeTopic[];
};

export type KnowledgeTag = { tag: string; count: number; kind: "tag" | "place" | "project" };

export type KnowledgeNoteRow = {
  id: string;
  folder: string;
  slug: string;
  title: string;
  topic: string;
  topic_label: string;
  tags: string[];
  hubs: { label: string; kind: "place" | "project" }[];
  summary: string;
  edited: string;
  has_assets: boolean;
  private: boolean;
};

export type KnowledgeIndex = {
  topics: KnowledgeTopic[];
  tags: KnowledgeTag[];
  notes: KnowledgeNoteRow[];
  root_count: number;
  charter: string;
  total: number;
};

export type KnowledgeRelated = {
  id: string;
  title: string;
  edge_type: string;
  folder: string | null;
  slug: string | null;
  knowledge: boolean;
};

export type KnowledgeNote = {
  id: string;
  folder: string;
  slug: string;
  title: string;
  content: string;
  fields: Record<string, string>;
  meta: Record<string, unknown>;
  assets: string[];
  topic: string;
  topic_label: string;
  tags: string[];
  edited: string;
  private: boolean;
  related: KnowledgeRelated[];
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export function getKnowledge(params: { q?: string; topic?: string; tag?: string } = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  const s = qs.toString();
  return get<KnowledgeIndex>(`/knowledge${s ? `?${s}` : ""}`);
}

export function getKnowledgeNote(folder: string, slug: string) {
  return get<KnowledgeNote>(`/knowledge/note?folder=${encodeURIComponent(folder)}&slug=${encodeURIComponent(slug)}`);
}

/** `?n=` value for a note: "<folder>/<slug>". */
export function noteParam(folder: string, slug: string) {
  return `${folder}/${slug}`;
}

export function splitNoteParam(n: string): { folder: string; slug: string } | null {
  const i = n.lastIndexOf("/");
  if (i <= 0 || i === n.length - 1) return null;
  return { folder: n.slice(0, i), slug: n.slice(i + 1) };
}
