"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { ArrowLeft, FolderOpen, Link2, Lock, MessageSquare } from "lucide-react";
import ImageLightbox from "@/components/ImageLightbox";
import { Badge, EmptyState, Panel } from "@/components/ui/Panel";
import { kbAssetUrl } from "@/lib/api";
import { formatIsoDate } from "@/lib/date";
import { getKnowledgeNote, noteParam, type KnowledgeNote } from "@/lib/knowledgeApi";

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp", "svg"];
const VIDEO_EXT = ["mp4", "webm", "mov", "m4v"];

const ext = (p: string) => p.split("?")[0].split(".").pop()?.toLowerCase() ?? "";
const isRemote = (u: string) => /^(https?:|data:|mailto:|#|\/)/i.test(u);

// Same body handling as Browse: the "# Title" first line is shown as the
// header, trailing [asset](...) lines become inline previews.
function splitBody(content: string): { body: string; assetPaths: string[] } {
  let lines = content.replace(/^\s+/, "").split("\n");
  if (lines[0]?.startsWith("#")) lines = lines.slice(1);
  const assetPaths: string[] = [];
  let end = lines.length;
  while (end > 0) {
    const line = lines[end - 1].trim();
    const m = line.match(/^\[asset\]\(([^)]+)\)$/);
    if (m) assetPaths.unshift(m[1]);
    else if (line) break;
    end -= 1;
  }
  return { body: lines.slice(0, end).join("\n").trim(), assetPaths };
}

function InlineAsset({ folder, path }: { folder: string; path: string }) {
  const url = kbAssetUrl(folder, path);
  const e = ext(path);
  if (IMAGE_EXT.includes(e)) return <ImageLightbox src={url} alt={path} className="max-w-full rounded-lg border" />;
  if (e === "pdf") return <iframe src={url} title={path} className="w-full rounded-lg border" style={{ height: "70vh" }} />;
  if (VIDEO_EXT.includes(e)) return <video src={url} controls className="max-w-full rounded-lg border" />;
  return (
    <a href={url} target="_blank" rel="noreferrer" className="inline-block rounded-lg border px-3 py-2 text-sm text-accent underline">
      Open {path.split("/").pop()}
    </a>
  );
}

export function NoteReader({
  folder,
  slug,
  onBack,
  onTopic,
  onOpen,
}: {
  folder: string;
  slug: string;
  onBack: () => void;
  onTopic: (topic: string) => void;
  onOpen: (folder: string, slug: string) => void;
}) {
  const [note, setNote] = useState<KnowledgeNote | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getKnowledgeNote(folder, slug)
      .then((n) => live && (setNote(n), setError(null)))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [folder, slug]);

  const back = (
    <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-accent">
      <ArrowLeft size={14} /> All knowledge
    </button>
  );

  if (error) return <div className="space-y-3">{back}<EmptyState>Couldn&apos;t load this note. {error}</EmptyState></div>;
  if (!note || note.folder !== folder || note.slug !== slug) return <div className="space-y-3">{back}<p className="text-sm text-muted">Loading…</p></div>;

  const { body, assetPaths } = splitBody(note.content);
  const assets = Array.from(new Set([...note.assets, ...assetPaths]));
  const chatHref = `/kb?continueFolder=${encodeURIComponent(note.folder)}&continueSlug=${encodeURIComponent(note.slug)}`;
  const browseHref = `/kb/browse?path=${encodeURIComponent(note.folder)}&open=${encodeURIComponent(note.slug)}`;

  return (
    <div className="space-y-4">
      {back}
      <article className="rounded-xl border border-line bg-surface/80 p-4 shadow-panel md:p-6">
        <header className="mb-4 space-y-2 border-b border-line pb-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {note.topic && (
              <button onClick={() => onTopic(note.topic)} className="rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent hover:bg-accent/20">
                {note.topic_label}
              </button>
            )}
            {note.private && (
              <Badge tone="warn">
                <Lock size={10} className="mr-1" /> private
              </Badge>
            )}
            <span className="font-mono text-[11px] text-muted">edited {formatIsoDate(note.edited)}</span>
          </div>
          <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{note.title}</h1>
          {note.tags.length > 0 && (
            <div className="flex flex-wrap gap-2 text-xs text-accent/80">
              {note.tags.map((t) => (
                <span key={t}>#{t}</span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <Link href={browseHref} className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1 text-xs hover:border-accent/60 hover:bg-accent/10">
              <FolderOpen size={13} /> Open in Browse
            </Link>
            <Link href={chatHref} className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1 text-xs hover:border-accent/60 hover:bg-accent/10">
              <MessageSquare size={13} /> Chat about this
            </Link>
          </div>
        </header>

        <div className="prose prose-sm dark:prose-invert max-w-none break-words prose-a:text-accent prose-img:rounded-lg prose-pre:overflow-x-auto">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            urlTransform={(url) => (isRemote(url) ? url : kbAssetUrl(note.folder, url))}
          >
            {body}
          </ReactMarkdown>
        </div>

        {assets.length > 0 && (
          <div className={assets.length > 1 && assets.every((p) => IMAGE_EXT.includes(ext(p))) ? "mt-4 grid grid-cols-2 gap-2" : "mt-4 space-y-3"}>
            {assets.map((p) => (
              <InlineAsset key={p} folder={note.folder} path={p} />
            ))}
          </div>
        )}
      </article>

      {note.related.length > 0 && (
        <Panel title="Related" icon={Link2}>
          <ul className="space-y-1.5 text-sm">
            {note.related.map((r) => (
              <li key={`${r.id}:${r.edge_type}`} className="flex min-w-0 items-center gap-2">
                {r.knowledge && r.folder && r.slug ? (
                  <button onClick={() => onOpen(r.folder!, r.slug!)} className="truncate text-left text-accent hover:underline" title={noteParam(r.folder, r.slug)}>
                    {r.title}
                  </button>
                ) : r.folder && r.slug ? (
                  <Link href={`/kb/browse?path=${encodeURIComponent(r.folder)}&open=${encodeURIComponent(r.slug)}`} className="truncate hover:underline">
                    {r.title}
                  </Link>
                ) : (
                  <span className="truncate">{r.title}</span>
                )}
                <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted">{r.edge_type.replace(/_/g, " ")}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
