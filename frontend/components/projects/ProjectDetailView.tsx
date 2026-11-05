"use client";

// The website's /projects/<slug> page, inside the HUD: title, banner (cover
// image) or an orbit-controls STL viewer, summary, stack chips, a GitHub
// button, then the project's content grouped by type — 3D models, images
// (lightbox), PDFs & documents, videos, the hub description and every other
// markdown note rendered — and the work-log days that touched it.

import { useMemo, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { ArrowLeft, Box, CalendarDays, Download, FileText, Film, FolderOpen, Image as ImageIcon, Link2, Lock, NotebookText, Pencil } from "lucide-react";
import { kbAssetUrl } from "@/lib/api";
import { formatIsoDate } from "@/lib/date";
import type { ProjectDetail, ProjectFile } from "@/lib/projectsApi";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState, Panel } from "@/components/ui/Panel";
import ImageLightbox from "@/components/ImageLightbox";
import DocxViewer from "@/components/DocxViewer";
import GithubIcon from "./GithubIcon";
import ProjectMarkdown, { stripAssetLines } from "./ProjectMarkdown";
import { STATUS_LABEL, STATUS_TONE } from "./ProjectCard";

const STLViewer = dynamic(() => import("@/components/STLViewer"), { ssr: false });

export function kbBrowseLink(folder: string, slug?: string) {
  return `/kb/browse?path=${encodeURIComponent(folder)}${slug ? `&open=${encodeURIComponent(slug)}` : ""}`;
}

function fmtSize(n: number | null): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const isStl = (f: ProjectFile) => f.name.toLowerCase().endsWith(".stl");

function FileRow({ f, onOpen, active }: { f: ProjectFile; onOpen?: () => void; active?: boolean }) {
  const url = kbAssetUrl(f.folder, f.path);
  return (
    <li className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm ${active ? "border-accent/50 bg-accent/10" : "border-line bg-surface-2/40"}`}>
      {onOpen ? (
        <button onClick={onOpen} className="min-w-0 flex-1 truncate text-left text-accent hover:underline">
          {f.path}
        </button>
      ) : (
        <a href={url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate text-accent hover:underline">
          {f.path}
        </a>
      )}
      <span className="shrink-0 font-mono text-[10px] text-muted">{fmtSize(f.size)}</span>
      <a href={url} download={f.name} title="Download" aria-label={`Download ${f.name}`} className="shrink-0 text-muted hover:text-accent">
        <Download size={14} />
      </a>
    </li>
  );
}

export default function ProjectDetailView({ project: p, onEdit }: { project: ProjectDetail; onEdit: () => void }) {
  const files = p.files;
  const models = files.filter((f) => f.kind === "model");
  const stls = models.filter(isStl);
  const images = files.filter((f) => f.kind === "image");
  const docs = files.filter((f) => f.kind === "pdf" || f.kind === "doc");
  const videos = files.filter((f) => f.kind === "video");
  const other = files.filter((f) => f.kind === "other");

  // One live WebGL viewer at a time (several canvases on a phone exhaust GL
  // contexts) — the website's stl-viewer page, inline: pick a file, view it.
  const initialStl = p.card?.kind === "stl" ? p.card.path : stls[0]?.path;
  const [stlPath, setStlPath] = useState<string | undefined>(initialStl);
  const [docPath, setDocPath] = useState<string | null>(null);
  const banner = p.card?.kind === "image" ? p.card : null;
  const openDoc = useMemo(() => docs.find((f) => f.path === docPath) ?? null, [docs, docPath]);
  const dates = [p.start, p.end].filter(Boolean).join(" – ");

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href="/projects" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-accent">
          <ArrowLeft size={14} /> All projects
        </Link>
        <div className="flex items-center gap-2">
          <Link
            href={kbBrowseLink(p.folder, p.hub?.slug)}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs text-muted hover:bg-white/5 hover:text-foreground"
          >
            <FolderOpen size={13} /> Browse
          </Link>
          <Button size="sm" onClick={onEdit}>
            <Pencil size={13} /> Edit
          </Button>
        </div>
      </div>

      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-accent md:text-3xl">{p.title}</h1>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={STATUS_TONE[p.status]}>{STATUS_LABEL[p.status]}</Badge>
          {dates && <Badge tone="muted">{dates}</Badge>}
          {p.private && (
            <Badge tone="muted">
              <Lock size={10} className="mr-1" /> private
            </Badge>
          )}
          {p.public && <Badge tone="ok">on website{p.public_name && p.public_name !== p.title ? ` as ${p.public_name}` : ""}</Badge>}
        </div>
      </header>

      {banner && (
        <ImageLightbox src={kbAssetUrl(banner.folder, banner.path)} alt={p.title} className="max-h-[420px] w-full rounded-lg border border-line object-cover" />
      )}

      {stlPath && (
        <div className="overflow-hidden rounded-lg border border-line bg-black/40">
          <STLViewer key={stlPath} url={kbAssetUrl(p.folder, stlPath)} height={400} controls zoom />
          <p className="border-t border-line px-3 py-1.5 font-mono text-[11px] text-muted">
            {stlPath} · drag to orbit, scroll/pinch to zoom
          </p>
        </div>
      )}

      {p.summary && <p className="text-base leading-relaxed text-foreground/90">{p.summary}</p>}

      {p.stack.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Stack">
          {p.stack.map((t) => (
            <li key={t} className="rounded border border-accent/25 bg-accent/5 px-1.5 py-0.5 font-mono text-xs text-accent/90">
              {t}
            </li>
          ))}
        </ul>
      )}

      {(p.repo || (p.public_repo && p.public_repo !== p.repo)) && (
        <div className="flex flex-wrap gap-2">
          {p.repo && (
            <a
              href={p.repo}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-md border border-line-strong bg-[#0d1117] px-3 py-1.5 font-mono text-sm text-foreground no-underline hover:border-accent/60"
            >
              <GithubIcon size={16} /> View on GitHub
            </a>
          )}
          {p.public_repo && p.public_repo !== p.repo && (
            <a
              href={p.public_repo}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 font-mono text-sm text-muted no-underline hover:border-accent/60 hover:text-foreground"
            >
              <GithubIcon size={16} /> Public repo
            </a>
          )}
        </div>
      )}

      {stripAssetLines(p.body) && (
        <Panel title="About" icon={NotebookText}>
          <ProjectMarkdown folder={p.hub?.folder ?? p.folder} content={p.body} />
        </Panel>
      )}

      {models.length > 0 && (
        <Panel title={`3D models · ${models.length}`} icon={Box}>
          <ul className="space-y-1.5">
            {models.map((f) =>
              isStl(f) ? (
                <FileRow key={f.path} f={f} active={f.path === stlPath} onOpen={() => setStlPath(f.path)} />
              ) : (
                <FileRow key={f.path} f={f} />
              )
            )}
          </ul>
          {models.length > stls.length && <p className="mt-2 text-xs text-muted">Only STL previews in-app; other model formats download.</p>}
        </Panel>
      )}

      {images.length > 0 && (
        <Panel title={`Images · ${images.length}`} icon={ImageIcon}>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {images.map((f) => (
              <ImageLightbox key={f.path} src={kbAssetUrl(f.folder, f.path)} alt={f.name} className="aspect-square w-full rounded-md border border-line object-cover" />
            ))}
          </div>
        </Panel>
      )}

      {docs.length > 0 && (
        <Panel title={`PDFs & docs · ${docs.length}`} icon={FileText}>
          <ul className="space-y-1.5">
            {docs.map((f) => {
              const viewable = f.kind === "pdf" || f.name.toLowerCase().endsWith(".docx");
              return (
                <FileRow
                  key={f.path}
                  f={f}
                  active={f.path === docPath}
                  onOpen={viewable ? () => setDocPath(docPath === f.path ? null : f.path) : undefined}
                />
              );
            })}
          </ul>
          {openDoc && (
            <div className="mt-3">
              {openDoc.kind === "pdf" ? (
                <iframe src={kbAssetUrl(openDoc.folder, openDoc.path)} title={openDoc.name} className="w-full rounded border border-line" style={{ height: "70vh" }} />
              ) : (
                <DocxViewer url={kbAssetUrl(openDoc.folder, openDoc.path)} />
              )}
            </div>
          )}
        </Panel>
      )}

      {videos.length > 0 && (
        <Panel title={`Videos · ${videos.length}`} icon={Film}>
          <div className="space-y-3">
            {videos.map((f) => (
              <div key={f.path} className="space-y-1">
                <video src={kbAssetUrl(f.folder, f.path)} controls className="w-full rounded-md border border-line" />
                <p className="font-mono text-[11px] text-muted">{f.path}</p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {p.notes.length > 0 && (
        <Panel title={`Notes · ${p.notes.length}`} icon={NotebookText} bodyClassName="p-0">
          <ul className="divide-y divide-line">
            {p.notes.map((n) => (
              <li key={`${n.folder}/${n.slug}`}>
                <details className="group">
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 hover:bg-white/5">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {n.private && <Lock size={11} className="mr-1 inline text-muted" />}
                        {n.title}
                      </span>
                      {n.snippet && <span className="block truncate text-xs text-muted">{n.snippet}</span>}
                    </span>
                    {n.subfolder && <Badge tone="muted">{n.subfolder}</Badge>}
                  </summary>
                  <div className="space-y-2 px-4 pb-4">
                    <ProjectMarkdown folder={n.folder} content={n.content} />
                    <Link href={kbBrowseLink(n.folder, n.slug)} className="text-xs text-muted hover:text-accent">
                      Open in Browse →
                    </Link>
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {other.length > 0 && (
        <Panel title={`Other files · ${other.length}`} icon={Download}>
          <ul className="space-y-1.5">
            {other.map((f) => (
              <FileRow key={f.path} f={f} />
            ))}
          </ul>
        </Panel>
      )}

      <Panel title={`Work logs · ${p.worklogs.length} day${p.worklogs.length === 1 ? "" : "s"}`} icon={CalendarDays}>
        {p.worklogs.length === 0 ? (
          <EmptyState icon={CalendarDays}>No work-log days linked to this project yet.</EmptyState>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {p.worklogs.map((w) => (
              <li key={w.slug}>
                <Link
                  href={kbBrowseLink(w.folder, w.slug)}
                  className="inline-block rounded-md border border-line bg-surface-2/40 px-2 py-1 font-mono text-xs text-foreground/90 hover:border-accent/50 hover:text-accent"
                >
                  {w.date ? formatIsoDate(w.date) : w.title}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {p.related.length > 0 && (
        <Panel title={`Connected · ${p.related.length}`} icon={Link2}>
          <ul className="flex flex-wrap gap-1.5">
            {p.related.map((r) => (
              <li key={r.id}>
                {r.folder && r.slug ? (
                  <Link
                    href={kbBrowseLink(r.folder, r.slug)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-2/40 px-2 py-1 text-xs hover:border-accent/50 hover:text-accent"
                  >
                    <span className="font-mono text-[10px] uppercase text-muted">{r.type}</span> {r.title}
                  </Link>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs">
                    <span className="font-mono text-[10px] uppercase text-muted">{r.type}</span> {r.title}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {files.length === 0 && p.notes.length === 0 && !stripAssetLines(p.body) && (
        <EmptyState icon={FolderOpen}>
          Nothing in this project folder yet — drop notes, STLs, images or PDFs into <span className="font-mono">{p.folder}/</span>.
        </EmptyState>
      )}
    </div>
  );
}
