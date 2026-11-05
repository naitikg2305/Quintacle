// The Career page (timeline of Career/** hubs) — backend: core/quintacle_core/
// nodes/career/timeline.py + the /career/timeline, /career/hubs routes.
// Kept apart from lib/api.ts (the Career *updates* client lives there).
import { API_BASE } from "@/lib/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: options?.body ? { "content-type": "application/json" } : undefined,
    ...options,
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      const j = JSON.parse(detail);
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* plain text body */
    }
    throw new Error(detail || `${options?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.json();
}

export type CareerHubType = "employer" | "role" | "contract" | "education" | "other";

export type CareerRange = {
  start: string | null;
  end: string | null;
  present: boolean;
  display: string;
  derived?: boolean;
};

export type CareerFile =
  | { kind: "note"; name: string; folder: string; slug: string; private: boolean }
  | { kind: "file"; name: string; folder: string; path: string }
  | { kind: "folder"; name: string; folder: string };

export type CareerRecordEntry = {
  id: string;
  title: string;
  how: "field" | "title" | null;
  tech: string[];
  bullets: { text: string; kind: string }[];
};

export type CareerNode = {
  id: string;
  folder: string;
  slug: string;
  title: string;
  type: CareerHubType;
  role: string;
  location: string;
  summary: string;
  bullets: string[];
  start_raw: string;
  end_raw: string;
  range: CareerRange;
  order: number | null;
  private: boolean;
  public: boolean;
  public_name: string;
  record_entry_field: string;
  record: CareerRecordEntry | null;
  record_candidates: string[];
  activity: { days: number; last: string[]; spark: { month: string; days: number }[] };
  own_days: number;
  files: CareerFile[];
  file_count: number;
  children: CareerNode[];
};

export type CareerTimeline = {
  today: string;
  items: CareerNode[];
  counts: Record<CareerHubType, number>;
  record_present: boolean;
};

export type CareerHubFields = {
  type?: CareerHubType | "";
  role?: string;
  start?: string;
  end?: string;
  location?: string;
  summary?: string;
  bullets?: string[];
  public?: boolean | null;
  public_name?: string;
  record_entry?: string;
  order?: number | null;
};

export const getCareerTimeline = () => request<CareerTimeline>("/career/timeline");

export const createCareerHub = (body: CareerHubFields & { type: CareerHubType; name: string; org?: string }) =>
  request<CareerNode>("/career/hubs", { method: "POST", body: JSON.stringify(body) });

export const updateCareerHubFields = (folder: string, body: CareerHubFields) =>
  request<CareerNode>(`/career/hubs/${folder.split("/").map(encodeURIComponent).join("/")}/fields`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

// Every node in the tree, depth first (detail lookup by folder).
export function flattenCareer(items: CareerNode[]): CareerNode[] {
  const out: CareerNode[] = [];
  const walk = (ns: CareerNode[]) => ns.forEach((n) => (out.push(n), walk(n.children)));
  walk(items);
  return out;
}
