"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download, ExternalLink, Eye, EyeOff, Link2, Lock } from "lucide-react";
import ImageLightbox from "@/components/ImageLightbox";
import DocxViewer from "@/components/DocxViewer";
import SpreadsheetEditor from "@/components/SpreadsheetEditor";
import { Badge, Panel } from "@/components/ui/Panel";
import { formatIsoDate } from "@/lib/date";
import { kbAssetUrl } from "@/lib/api";
import { ideaFileUrl, type IdeaDetail, type IdeaFile, type IdeaFileKind } from "@/lib/businessApi";
import { formatBytes, KIND_META, KIND_ORDER } from "./fileKinds";

const STLViewer = dynamic(() => import("@/components/STLViewer"), { ssr: false });

const ASSET_LINE = /^\[asset\]\(([^)]+)\)\s*$/gm;

function kbLink(folder: string, slug: string) {
  return `/kb/browse?path=${encodeURIComponent(folder)}&open=${encodeURIComponent(slug)}`;
}

// Markdown with relative image/link targets resolved against the note's own
// folder through /kb/asset (a note's `assets/x.png` is not a real URL).
export function IdeaMarkdown({ folder, content }: { folder: string; content: string }) {
  const body = content.replace(ASSET_LINE, "").trim();
  if (!body) return null;
  const resolve = (src: string) => (/^(https?:|data:|\/|#)/.test(src) ? src : kbAssetUrl(folder, src));
  return (
    <div className="prose prose-sm prose-invert max-w-none break-words prose-a:text-accent prose-img:rounded-lg">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // eslint-disable-next-line @next/next/no-img-element
          img: ({ src, alt }) => <img src={typeof src === "string" ? resolve(src) : undefined} alt={alt ?? ""} className="max-w-full" />,
          a: ({ href, children }) => (
            <a href={href ? resolve(href) : undefined} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {body}
      </ReactMarkdown>
    </div>
  );
}

function FileChip({ idea, file }: { idea: IdeaDetail; file: IdeaFile }) {
  const url = ideaFileUrl(idea, file);
  const Icon = KIND_META[file.kind].icon;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      download={file.name}
      className="inline-flex max-w-full items-center gap-2 rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-sm transition-colors hover:border-accent/60"
    >
      <Icon size={14} className="shrink-0 text-accent" />
      <span className="min-w-0 truncate">{file.name}</span>
      <span className="shrink-0 font-mono text-[10px] text-muted">{formatBytes(file.size)}</span>
      <Download size={13} className="shrink-0 text-muted" />
    </a>
  );
}

// PDFs, docs and spreadsheets: open / download always, an in-page preview on
// demand (iframes and parsed documents are heavy to mount all at once).
function PreviewableFile({ idea, file }: { idea: IdeaDetail; file: IdeaFile }) {
  const [open, setOpen] = useState(false);
  const url = ideaFileUrl(idea, file);
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  const canPreview = ext === "pdf" || ext === "docx" || ext === "xlsx" || ext === "xlsm";
  const Icon = KIND_META[file.kind].icon;
  return (
    <div className="rounded-lg border border-line bg-surface-2/60">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <Icon size={14} className="shrink-0 text-accent" />
        <span className="min-w-0 flex-1 truncate text-sm" title={file.path}>
          {file.name}
        </span>
        <span className="font-mono text-[10px] text-muted">{formatBytes(file.size)}</span>
        {canPreview && (
          <button onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
            {open ? <EyeOff size={13} /> : <Eye size={13} />}
            {open ? "Hide" : "Preview"}
          </button>
        )}
        <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
          <ExternalLink size={13} /> Open
        </a>
        <a href={url} download={file.name} className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
          <Download size={13} /> Save
        </a>
      </div>
      {open && (
        <div className="border-t border-line p-2">
          {ext === "pdf" && <iframe src={url} title={file.name} className="h-[70vh] w-full rounded border border-line bg-white" />}
          {ext === "docx" && (
            <div className="max-h-[70vh] overflow-auto rounded bg-white p-3 text-black">
              <DocxViewer url={url} />
            </div>
          )}
          {(ext === "xlsx" || ext === "xlsm") && <SpreadsheetEditor folder={idea.folder} path={file.path} />}
        </div>
      )}
    </div>
  );
}

function KindSection({ idea, kind, files }: { idea: IdeaDetail; kind: IdeaFileKind; files: IdeaFile[] }) {
  const { label, icon } = KIND_META[kind];
  return (
    <Panel title={`${label} · ${files.length}`} icon={icon} bodyClassName="space-y-3">
      {kind === "markdown" &&
        files.map((f) => (
          <article key={f.path} className="space-y-2 rounded-lg border border-line bg-surface-2/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Link href={kbLink(f.folder ?? idea.folder, f.slug ?? "")} className="min-w-0 break-words text-sm font-medium hover:text-accent">
                {f.title ?? f.name}
              </Link>
              {f.private && (
                <Badge tone="warn">
                  <Lock size={10} className="mr-1" />
                  private
                </Badge>
              )}
              <span className="font-mono text-[10px] text-muted">{formatIsoDate(f.modified)}</span>
            </div>
            <IdeaMarkdown folder={f.folder ?? idea.folder} content={f.content ?? ""} />
          </article>
        ))}

      {kind === "image" && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {files.map((f) => (
            <figure key={f.path} className="min-w-0">
              <ImageLightbox
                src={ideaFileUrl(idea, f)}
                alt={f.name}
                className="aspect-square w-full rounded-lg border border-line object-cover"
              />
              <figcaption className="mt-1 truncate font-mono text-[10px] text-muted">{f.name}</figcaption>
            </figure>
          ))}
        </div>
      )}

      {kind === "video" &&
        files.map((f) => (
          <figure key={f.path} className="space-y-1">
            <video src={ideaFileUrl(idea, f)} controls preload="metadata" className="w-full rounded-lg border border-line" />
            <figcaption className="truncate font-mono text-[10px] text-muted">{f.name}</figcaption>
          </figure>
        ))}

      {kind === "model" &&
        files.map((f) =>
          f.name.toLowerCase().endsWith(".stl") ? (
            <figure key={f.path} className="space-y-1">
              <div className="overflow-hidden rounded-lg border border-line bg-background">
                <STLViewer url={ideaFileUrl(idea, f)} hover controls zoom height="40vh" />
              </div>
              <figcaption className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted">{f.name}</span>
                <a href={ideaFileUrl(idea, f)} download={f.name} className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
                  <Download size={13} /> Save
                </a>
              </figcaption>
            </figure>
          ) : (
            <FileChip key={f.path} idea={idea} file={f} />
          )
        )}

      {(kind === "pdf" || kind === "doc" || kind === "spreadsheet") &&
        files.map((f) => <PreviewableFile key={f.path} idea={idea} file={f} />)}

      {kind === "link" && (
        <div className="flex flex-wrap gap-2">
          {files.map((f) =>
            f.url ? (
              <a
                key={f.path}
                href={f.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex max-w-full items-center gap-2 rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-sm hover:border-accent/60"
              >
                <Link2 size={14} className="shrink-0 text-accent" />
                <span className="min-w-0 truncate">{f.name.replace(/\.(url|webloc)$/i, "")}</span>
              </a>
            ) : (
              <FileChip key={f.path} idea={idea} file={f} />
            )
          )}
        </div>
      )}

      {kind === "other" && (
        <div className="flex flex-wrap gap-2">
          {files.map((f) => (
            <FileChip key={f.path} idea={idea} file={f} />
          ))}
        </div>
      )}
    </Panel>
  );
}

export default function IdeaFiles({ idea }: { idea: IdeaDetail }) {
  const kinds = KIND_ORDER.filter((k) => (idea.files[k]?.length ?? 0) > 0);
  return (
    <div className="space-y-4">
      {kinds.map((k) => (
        <KindSection key={k} idea={idea} kind={k} files={idea.files[k]!} />
      ))}
      {idea.links.length > 0 && (
        <Panel title={`Links in notes · ${idea.links.length}`} icon={ExternalLink} bodyClassName="space-y-1.5">
          {idea.links.map((u) => (
            <a key={u} href={u} target="_blank" rel="noreferrer" className="block break-all text-sm text-accent hover:underline">
              {u}
            </a>
          ))}
        </Panel>
      )}
    </div>
  );
}
