"use client";

// Projects (2026-11-05) — the PersonalWebsite's /projects page inside the
// HUD: sections of cards (Doing · Planned · Done here, where the website has
// Software / Hardware), each card a cover image or hover-rotating STL, and
// a detail view per project. Detail is a query param (/projects?p=<slug>)
// rather than a dynamic route because the phone build is a static export.
// Data: GET /projects, GET /projects/<slug> (nodes/projects/api.py) over the
// KB's Projects/<Name>/ folders.

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FolderKanban, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { EmptyState, PageHeader } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { BottomSheet } from "@/components/ui/BottomSheet";
import ProjectCard, { STATUS_LABEL } from "@/components/projects/ProjectCard";
import ProjectDetailView from "@/components/projects/ProjectDetailView";
import ProjectForm from "@/components/projects/ProjectForm";
import {
  createProject,
  getProject,
  listProjects,
  PROJECT_STATUSES,
  type ProjectDetail,
  type ProjectStatus,
  type ProjectSummary,
  updateProjectFields,
} from "@/lib/projectsApi";

const SECTION_SUBTITLE: Record<ProjectStatus, string> = {
  doing: "In progress right now",
  planned: "Ideas and what's next",
  done: "Shipped, finished, archived",
};

type Filter = "all" | ProjectStatus;

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectsPageInner />
    </Suspense>
  );
}

function ProjectsPageInner() {
  const searchParams = useSearchParams();
  const slug = searchParams.get("p");
  return slug ? <DetailPage key={slug} slug={slug} /> : <ListPage />;
}

function ListPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const raw = searchParams.get("status");
  const filter: Filter = raw === "doing" || raw === "planned" || raw === "done" ? raw : "all";
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    listProjects()
      .then((p) => {
        setProjects(p);
        setError(null);
      })
      .catch((e) => {
        setProjects([]);
        setError(errorText(e));
      });
  }, []);

  function setFilter(f: Filter) {
    router.replace(f === "all" ? pathname : `${pathname}?status=${f}`);
  }

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (projects ?? []).filter(
      (p) => !q || [p.title, p.summary, ...p.stack].some((s) => s.toLowerCase().includes(q))
    );
  }, [projects, query]);

  const counts = useMemo(() => {
    const c: Record<ProjectStatus, number> = { doing: 0, planned: 0, done: 0 };
    for (const p of projects ?? []) c[p.status] += 1;
    return c;
  }, [projects]);

  const sections = PROJECT_STATUSES.filter((s) => filter === "all" || filter === s);

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <PageHeader
        title="Projects"
        icon={FolderKanban}
        subtitle="What you've built, what you're building, and what's next."
        actions={
          <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
            <Plus size={14} /> New project
          </Button>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<Filter>
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `All${projects ? ` ${projects.length}` : ""}` },
            ...PROJECT_STATUSES.map((s) => ({ value: s, label: `${STATUS_LABEL[s]} ${counts[s]}` })),
          ]}
        />
        <div className="relative min-w-[10rem] flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by name or stack" className="pl-8" />
        </div>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}
      {projects === null && <p className="text-sm text-muted">Loading…</p>}
      {projects !== null && projects.length === 0 && !error && (
        <EmptyState icon={FolderKanban}>
          No projects yet. Create one, or drop files into a <span className="font-mono">Projects/&lt;Name&gt;/</span> folder in the KB.
        </EmptyState>
      )}

      {projects !== null &&
        projects.length > 0 &&
        sections.map((status) => {
          const rows = visible.filter((p) => p.status === status);
          if (rows.length === 0 && filter === "all") return null;
          return (
            <section key={status} className="space-y-3 pt-2">
              <div className="text-center">
                <h2 className="text-xl font-semibold text-accent md:text-2xl">{STATUS_LABEL[status]}</h2>
                <p className="font-mono text-xs text-muted">{SECTION_SUBTITLE[status]}</p>
              </div>
              {rows.length === 0 ? (
                <EmptyState icon={FolderKanban}>Nothing {STATUS_LABEL[status].toLowerCase()} {query ? "matches" : "yet"}.</EmptyState>
              ) : (
                <div className="grid grid-cols-1 gap-5 sm:grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
                  {rows.map((p) => (
                    <ProjectCard key={p.slug} project={p} href={`/projects?p=${encodeURIComponent(p.slug)}`} />
                  ))}
                </div>
              )}
            </section>
          );
        })}

      <BottomSheet open={creating} onClose={() => setCreating(false)} title="New project">
        <ProjectForm
          onCancel={() => setCreating(false)}
          onSubmit={async (body) => {
            const created = await createProject({ ...body, name: body.name ?? "" });
            setCreating(false);
            router.push(`/projects?p=${encodeURIComponent(created.slug)}`);
          }}
        />
      </BottomSheet>
    </div>
  );
}

function DetailPage({ slug }: { slug: string }) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [version, setVersion] = useState(0);

  const load = useCallback(() => {
    getProject(slug)
      .then((p) => {
        setProject(p);
        setError(null);
      })
      .catch((e) => setError(errorText(e)));
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <div className="mx-auto max-w-3xl space-y-3">
        <PageHeader title="Projects" icon={FolderKanban} />
        <p className="text-sm text-danger">{error}</p>
      </div>
    );
  }
  if (!project) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <>
      <ProjectDetailView key={version} project={project} onEdit={() => setEditing(true)} />
      <BottomSheet open={editing} onClose={() => setEditing(false)} title={`Edit · ${project.title}`}>
        <ProjectForm
          project={project}
          onCancel={() => setEditing(false)}
          onSubmit={async (body) => {
            const fresh = await updateProjectFields(slug, body);
            setProject(fresh);
            setVersion((v) => v + 1);
            setEditing(false);
          }}
        />
      </BottomSheet>
    </>
  );
}
