// Projects page client (2026-11-05) — GET/PUT/POST /projects
// (core/quintacle_core/nodes/projects/api.py). Kept out of lib/api.ts so
// parallel page builds don't collide there.
import { request } from "@/lib/api";

export const PROJECT_STATUSES = ["doing", "planned", "done"] as const;
export type ProjectStatus = (typeof PROJECT_STATUSES)[number];

export type ProjectFileKind = "model" | "image" | "pdf" | "doc" | "video" | "other";

export type ProjectCard = { kind: "stl" | "image"; folder: string; path: string };

export type ProjectSummary = {
  slug: string;
  title: string;
  folder: string;
  hub: { folder: string; slug: string } | null;
  status: ProjectStatus;
  repo: string | null;
  summary: string;
  stack: string[];
  start: string | null;
  end: string | null;
  cover: string | null;
  public: boolean;
  public_name: string | null;
  public_repo: string | null;
  private: boolean;
  edited: string | null;
  counts: Record<ProjectFileKind, number> & { notes: number; worklogs: number };
  last_worklog: string | null;
  card: ProjectCard | null;
};

export type ProjectFile = { folder: string; path: string; name: string; kind: ProjectFileKind; size: number | null };

export type ProjectNote = {
  folder: string;
  slug: string;
  title: string;
  subfolder: string;
  snippet: string;
  private: boolean;
  edited: string | null;
  content: string;
};

export type ProjectWorklog = { folder: string; slug: string; date: string | null; title: string };

export type ProjectRelated = { id: string; type: string; title: string; folder: string | null; slug: string | null };

export type ProjectDetail = ProjectSummary & {
  body: string;
  notes: ProjectNote[];
  files: ProjectFile[];
  worklogs: ProjectWorklog[];
  related: ProjectRelated[];
};

// Only keys present change; "" / [] clears a field.
export type ProjectFieldsUpdate = Partial<{
  status: ProjectStatus;
  repo: string;
  summary: string;
  stack: string[] | string;
  start: string;
  end: string;
  cover: string;
  public: boolean;
  public_name: string;
  public_repo: string;
}>;

export const listProjects = () => request<ProjectSummary[]>("/projects");

export const getProject = (slug: string) => request<ProjectDetail>(`/projects/${encodeURIComponent(slug)}`);

export const updateProjectFields = (slug: string, body: ProjectFieldsUpdate) =>
  request<ProjectDetail>(`/projects/${encodeURIComponent(slug)}/fields`, { method: "PUT", body: JSON.stringify(body) });

export const createProject = (body: ProjectFieldsUpdate & { name: string; description?: string }) =>
  request<ProjectDetail>("/projects", { method: "POST", body: JSON.stringify(body) });
