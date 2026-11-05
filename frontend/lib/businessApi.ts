// Business Ideas board client (core/quintacle_core/nodes/business). Kept out
// of lib/api.ts so parallel page builds don't collide on one file.
import { API_BASE, kbAssetUrl } from "@/lib/api";

export const IDEA_STATUSES = ["idea", "exploring", "validating", "building", "parked", "dropped"] as const;
export type IdeaStatus = (typeof IDEA_STATUSES)[number];

export type IdeaFileKind = "markdown" | "image" | "video" | "pdf" | "doc" | "spreadsheet" | "model" | "link" | "other";

type IdeaBase = {
  slug: string;
  folder: string;
  title: string;
  has_hub: boolean;
  private: boolean;
  status: IdeaStatus;
  summary: string;
  market: string;
  tags: string[];
  created: string | null;
  file_total: number;
  last_edited: string | null;
};

export type IdeaCard = IdeaBase & { file_counts: Partial<Record<IdeaFileKind, number>> };

export type IdeaFile = {
  name: string;
  path: string; // relative to the idea folder
  kind: IdeaFileKind;
  size: number;
  modified: string;
  // markdown only
  folder?: string;
  slug?: string;
  title?: string;
  content?: string;
  private?: boolean;
  // link files only
  url?: string | null;
};

export type IdeaDetail = IdeaBase & {
  body: string;
  files: Partial<Record<IdeaFileKind, IdeaFile[]>>;
  links: string[];
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: options?.body ? { "content-type": "application/json" } : undefined,
    ...options,
  });
  if (!res.ok) {
    throw new Error(`${options?.method ?? "GET"} ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export const listIdeas = () => request<{ statuses: IdeaStatus[]; ideas: IdeaCard[] }>("/business/ideas");

export const getIdea = (slug: string) => request<IdeaDetail>(`/business/ideas/${encodeURIComponent(slug)}`);

export const createIdea = (body: { title: string; summary?: string; status?: IdeaStatus; market?: string; tags?: string[] }) =>
  request<IdeaDetail>("/business/ideas", { method: "POST", body: JSON.stringify(body) });

export const updateIdeaFields = (
  slug: string,
  body: Partial<{ status: IdeaStatus; summary: string; market: string; tags: string[] }>
) => request<IdeaDetail>(`/business/ideas/${encodeURIComponent(slug)}/fields`, { method: "PUT", body: JSON.stringify(body) });

// Every member file is served by the normal clamped /kb/asset route, with the
// path relative to the idea's folder.
export const ideaFileUrl = (idea: { folder: string }, file: { path: string }) => kbAssetUrl(idea.folder, file.path);
