"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import {
  addKBEntryAsset,
  kbAssetUrl,
  listKBEntries,
  listKBFiles,
  listKBFolders,
  pushKBEntry,
  readKBEntry,
  replaceKBAsset,
  searchKBEntries,
} from "@/lib/api";
import ImageLightbox from "@/components/ImageLightbox";
import {
  ArrowLeft,
  Box,
  ChevronRight,
  File as FileGeneric,
  FileSpreadsheet,
  FileText,
  Film,
  Folder,
  FolderTree,
  Image as ImageIcon,
  MessageSquare,
  Paperclip,
  Pencil,
  Plus,
  Save,
  Search,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { EmptyState, PageHeader } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";
import DocxViewer from "@/components/DocxViewer";
import SpreadsheetEditor from "@/components/SpreadsheetEditor";

const STLViewer = dynamic(() => import("@/components/STLViewer"), { ssr: false });

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];
const VIDEO_EXT = ["mp4", "webm", "mov", "m4v"];
const SPREADSHEET_EXT = ["xlsx", "xlsm"];

function childFolderNames(allFolders: string[], currentPath: string): string[] {
  const depth = currentPath === "" ? 1 : currentPath.split("/").length + 1;
  const prefix = currentPath === "" ? "" : `${currentPath}/`;
  const names = allFolders
    .filter((f) => (currentPath === "" || f.startsWith(prefix)) && f.split("/").length === depth)
    .map((f) => f.split("/").pop()!);
  return [...new Set(names)].sort();
}

// A pushed-with-asset entry has one or more trailing "[asset](assets/xxx)"
// markdown links appended to its body (one per photo, for a two-photo drop)
// — pull them all out so each can be rendered as a real preview
// (image/STL/download) instead of a plain link to a path that isn't a real
// URL on its own.
function extractAssets(content: string): { body: string; assetPaths: string[] } {
  const lines = content.split("\n");
  const assetPaths: string[] = [];
  let end = lines.length;
  while (end > 0) {
    const match = lines[end - 1].match(/^\[asset\]\(([^)]+)\)$/);
    if (!match) break;
    assetPaths.unshift(match[1]);
    end -= 1;
  }
  const body = lines.slice(0, end).join("\n").replace(/\n+$/, "");
  return { body, assetPaths };
}

function splitTitle(content: string): { title: string; body: string } {
  const firstLine = content.split("\n")[0] ?? "";
  const title = firstLine.replace(/^#\s*/, "").trim();
  const body = content.slice(firstLine.length).replace(/^\n+/, "");
  return { title, body };
}

function fileIcon(ext: string): LucideIcon {
  if (IMAGE_EXT.includes(ext)) return ImageIcon;
  if (VIDEO_EXT.includes(ext)) return Film;
  if (ext === "pdf" || ext === "docx") return FileText;
  if (ext === "stl") return Box;
  if (SPREADSHEET_EXT.includes(ext)) return FileSpreadsheet;
  return FileGeneric;
}

// Shared by both "an asset attached to an entry" (assetPaths, path relative
// to the entry's folder) and "a raw file sitting directly in a folder" (e.g.
// everything inside an assets/ directory, which has no owning .md entry at
// all) — same file, same preview, so one component handles both instead of
// Browse only being able to render one of the two cases.
function AssetPreview({ folder, path, onReplace }: { folder: string; path: string; onReplace?: (file: File) => void }) {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const url = kbAssetUrl(folder, path);
  return (
    <div className="space-y-1">
      {IMAGE_EXT.includes(ext) && <ImageLightbox src={url} className="max-w-full rounded border" />}
      {ext === "stl" && (
        <div className="border rounded overflow-hidden">
          <STLViewer url={url} hover controls zoom height="40vh" />
        </div>
      )}
      {ext === "pdf" && <iframe src={url} className="w-full border rounded" style={{ height: "70vh" }} />}
      {VIDEO_EXT.includes(ext) && (
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <video src={url} controls className="max-w-full rounded border" />
      )}
      {ext === "docx" && <DocxViewer url={url} />}
      {SPREADSHEET_EXT.includes(ext) && <SpreadsheetEditor folder={folder} path={path} />}
      {![...IMAGE_EXT, "stl", "pdf", ...VIDEO_EXT, "docx", ...SPREADSHEET_EXT].includes(ext) && (
        <a href={url} target="_blank" rel="noreferrer" className="inline-block border rounded px-3 py-2 text-sm underline">
          Open {path}
        </a>
      )}
      {onReplace && (
        <label className="text-xs underline opacity-60 hover:opacity-100 cursor-pointer inline-block">
          ↻ replace this file
          <input
            type="file"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onReplace(f);
            }}
          />
        </label>
      )}
    </div>
  );
}

export default function KBBrowsePage() {
  const router = useRouter();
  const [allFolders, setAllFolders] = useState<string[]>([]);
  const [currentPath, setCurrentPath] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const [rawFiles, setRawFiles] = useState<string[]>([]);
  const [viewingRawFile, setViewingRawFile] = useState<string | null>(null);
  const [viewing, setViewing] = useState<{ folder: string; slug: string; content: string; fields: Record<string, string> } | null>(
    null
  );
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [fieldRows, setFieldRows] = useState<{ key: string; value: string }[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ folder: string; slug: string; snippet: string }[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    listKBFolders().then(setAllFolders);
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const handle = setTimeout(() => {
      searchKBEntries(q)
        .then(setResults)
        .finally(() => setSearching(false));
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    setViewing(null);
    setViewingRawFile(null);
    setEditing(false);
    if (currentPath) {
      listKBEntries(currentPath).then(setFiles);
      listKBFiles(currentPath).then(setRawFiles);
    } else {
      setFiles([]);
      setRawFiles([]);
    }
  }, [currentPath]);

  async function openFile(slug: string) {
    setViewingRawFile(null);
    setEditing(false);
    setStatus(null);
    setViewing(await readKBEntry(currentPath, slug));
  }

  function openRawFile(name: string) {
    setViewing(null);
    setEditing(false);
    setStatus(null);
    setViewingRawFile(name);
  }

  async function openResult(folder: string, slug: string) {
    setQuery("");
    setResults([]);
    setCurrentPath(folder);
    setViewingRawFile(null);
    setEditing(false);
    setStatus(null);
    setViewing(await readKBEntry(folder, slug));
  }

  function continueInChat() {
    if (!viewing) return;
    router.push(`/kb?continueFolder=${encodeURIComponent(viewing.folder)}&continueSlug=${encodeURIComponent(viewing.slug)}`);
  }

  function startEditing() {
    if (!viewing) return;
    setDraft(viewing.content);
    setFieldRows(Object.entries(viewing.fields).map(([key, value]) => ({ key, value })));
    setEditing(true);
  }

  async function saveEdit() {
    if (!viewing) return;
    const { title, body } = splitTitle(draft);
    const fields = Object.fromEntries(fieldRows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]));
    setStatus("saving...");
    await pushKBEntry({ folder: viewing.folder, title, content: body, fields });
    setViewing({ ...viewing, content: draft, fields });
    setEditing(false);
    setStatus("saved");
  }

  async function createEntry() {
    const title = window.prompt("Title for the new entry:");
    if (!title?.trim()) return;
    setStatus("creating...");
    const { slug } = await pushKBEntry({ folder: currentPath, title: title.trim(), content: "" });
    setFiles(await listKBEntries(currentPath));
    const entry = await readKBEntry(currentPath, slug);
    setViewingRawFile(null);
    setViewing(entry);
    setDraft(entry.content);
    setFieldRows([]);
    setEditing(true);
    setStatus(null);
  }

  async function attachFile(file: File) {
    if (!viewing) return;
    setStatus("attaching...");
    await addKBEntryAsset(viewing.folder, viewing.slug, file);
    setViewing(await readKBEntry(viewing.folder, viewing.slug));
    setStatus("attached");
  }

  const crumbs = currentPath ? currentPath.split("/") : [];
  const folders = childFolderNames(allFolders, currentPath);
  const { body: renderedBody, assetPaths } = viewing ? extractAssets(viewing.content) : { body: "", assetPaths: [] };

  const hasSelection = viewing !== null || viewingRawFile !== null;
  const mono = "font-mono text-[10px] uppercase tracking-[0.14em] text-muted";
  const tile = (active: boolean) =>
    cn(
      "flex flex-col items-center gap-1.5 rounded-lg border p-2.5 text-center transition-colors",
      active ? "border-accent/60 bg-accent/10" : "border-transparent hover:border-line hover:bg-white/5"
    );

  function closePreview() {
    setViewing(null);
    setViewingRawFile(null);
    setEditing(false);
  }

  return (
    <div className="space-y-3">
      <PageHeader title="Browse" icon={FolderTree} subtitle="Everything you've stored, folder by folder." />

      <div className="relative">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <Input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the whole knowledge base — filename or content..."
          className="pl-9"
        />
        {query.trim() && (
          <div className="absolute z-20 mt-1 max-h-80 w-full overflow-y-auto rounded-xl border border-line-strong bg-surface shadow-glow">
            {searching && <p className="p-3 text-xs text-muted">searching...</p>}
            {!searching && results.length === 0 && <p className="p-3 text-xs text-muted">No matches.</p>}
            {!searching &&
              results.map((r) => (
                <button
                  key={`${r.folder}/${r.slug}`}
                  onClick={() => openResult(r.folder, r.slug)}
                  className="block w-full border-b border-line px-3 py-2 text-left text-sm last:border-b-0 hover:bg-accent/10"
                >
                  <span className="font-medium">{r.slug}</span>
                  <span className="text-muted"> — {r.folder}</span>
                  {r.snippet && <p className="truncate text-xs text-muted">{r.snippet}</p>}
                </button>
              ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 border-b border-line pb-2">
        <div className="flex min-w-0 items-center gap-1 overflow-x-auto whitespace-nowrap text-sm">
          <button onClick={() => setCurrentPath("")} className="text-muted hover:text-accent">
            Knowledge base
          </button>
          {crumbs.map((crumb, i) => {
            const pathToHere = crumbs.slice(0, i + 1).join("/");
            return (
              <span key={pathToHere} className="flex items-center gap-1">
                <ChevronRight size={14} className="text-muted/60" />
                <button onClick={() => setCurrentPath(pathToHere)} className="text-muted hover:text-accent">
                  {crumb}
                </button>
              </span>
            );
          })}
        </div>
        {currentPath && (
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" onClick={createEntry}>
              <Plus size={14} /> New
            </Button>
            <a
              href={`/kb/folder?path=${encodeURIComponent(currentPath)}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1 text-xs hover:border-accent/60 hover:bg-accent/10"
            >
              <MessageSquare size={14} /> Chat
            </a>
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-12 h-[calc(100dvh-19rem)] min-h-[360px] lg:h-[calc(100dvh-14rem)]">
        {/* File list — hidden on phones while something is open */}
        <div
          className={cn(
            "overflow-y-auto rounded-xl border border-line bg-surface/80 p-3 shadow-panel lg:col-span-5 lg:block",
            hasSelection ? "hidden" : "block"
          )}
        >
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-3">
            {folders.map((name) => {
              const path = currentPath ? `${currentPath}/${name}` : name;
              return (
                <button key={path} onClick={() => setCurrentPath(path)} className={tile(false)}>
                  <Folder size={28} className="text-accent" />
                  <span className="break-words text-xs">{name}</span>
                </button>
              );
            })}
            {files.map((slug) => (
              <button key={slug} onClick={() => openFile(slug)} className={tile(viewing?.slug === slug)}>
                <FileText size={28} className="text-foreground/70" />
                <span className="break-words text-xs">{slug}.md</span>
              </button>
            ))}
            {rawFiles.map((name) => {
              const Icon = fileIcon(name.split(".").pop()?.toLowerCase() ?? "");
              return (
                <button key={name} onClick={() => openRawFile(name)} className={tile(viewingRawFile === name)}>
                  <Icon size={28} className="text-accent/80" />
                  <span className="break-all text-xs">{name}</span>
                </button>
              );
            })}
          </div>
          {folders.length === 0 && files.length === 0 && rawFiles.length === 0 && (
            <EmptyState icon={Folder}>{currentPath ? "Empty folder." : "Nothing in the Knowledge Base yet."}</EmptyState>
          )}
        </div>

        {/* Preview — full screen on phones, side panel on desktop */}
        <div
          className={cn(
            "overflow-y-auto rounded-xl border border-line bg-surface/80 p-4 shadow-panel lg:col-span-7 lg:block",
            hasSelection ? "block" : "hidden"
          )}
        >
          {!hasSelection && <EmptyState icon={FileText}>Select a file to view it.</EmptyState>}

          {hasSelection && (
            <button onClick={closePreview} className="mb-3 flex items-center gap-1.5 text-sm text-accent lg:hidden">
              <ArrowLeft size={16} /> Back
            </button>
          )}

          {viewingRawFile && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="break-all font-mono text-xs text-muted">
                  {currentPath}/{viewingRawFile}
                </p>
                <a
                  href={kbAssetUrl(currentPath, viewingRawFile)}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-lg border border-line-strong px-3 py-1 text-xs hover:border-accent/60 hover:bg-accent/10"
                >
                  Open in new tab
                </a>
              </div>
              <AssetPreview
                folder={currentPath}
                path={viewingRawFile}
                onReplace={async (f) => {
                  setStatus("replacing...");
                  await replaceKBAsset(currentPath, viewingRawFile, f);
                  setStatus("replaced — refresh to see the new version");
                }}
              />
              {status && <p className="text-xs text-muted">{status}</p>}
            </div>
          )}

          {viewing && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="break-all font-mono text-xs text-muted">
                  {viewing.folder}/{viewing.slug}.md
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  {!editing && (
                    <Button size="sm" onClick={startEditing}>
                      <Pencil size={13} /> Edit
                    </Button>
                  )}
                  {editing && (
                    <>
                      <Button size="sm" variant="primary" onClick={saveEdit}>
                        <Save size={13} /> Save
                      </Button>
                      <Button size="sm" onClick={() => setEditing(false)}>
                        Cancel
                      </Button>
                    </>
                  )}
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1 text-xs hover:border-accent/60 hover:bg-accent/10">
                    <Paperclip size={13} /> Attach
                    <input
                      type="file"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) attachFile(f);
                      }}
                    />
                  </label>
                  <Button size="sm" onClick={continueInChat}>
                    <MessageSquare size={13} /> Chat about this
                  </Button>
                </div>
              </div>

              {editing ? (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <p className={mono}>Fields</p>
                    {fieldRows.map((row, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <Input
                          className="w-1/3 py-1 text-xs"
                          placeholder="key"
                          value={row.key}
                          onChange={(e) => setFieldRows(fieldRows.map((r, j) => (j === i ? { ...r, key: e.target.value } : r)))}
                        />
                        <Input
                          className="flex-1 py-1 text-xs"
                          placeholder="value"
                          value={row.value}
                          onChange={(e) => setFieldRows(fieldRows.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))}
                        />
                        <button
                          onClick={() => setFieldRows(fieldRows.filter((_, j) => j !== i))}
                          aria-label="Remove field"
                          className="p-1 text-muted hover:text-danger"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                    <button
                      onClick={() => setFieldRows([...fieldRows, { key: "", value: "" }])}
                      className="flex items-center gap-1 text-xs text-accent hover:underline"
                    >
                      <Plus size={12} /> add field
                    </button>
                  </div>
                  <Textarea className="font-mono" rows={20} value={draft} onChange={(e) => setDraft(e.target.value)} />
                </div>
              ) : (
                <>
                  {Object.keys(viewing.fields).length > 0 && (
                    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 rounded-lg border border-line bg-surface-2/60 p-3 text-sm sm:grid-cols-2">
                      {Object.entries(viewing.fields).map(([k, v]) => (
                        <div key={k} className="flex gap-2">
                          <dt className={cn(mono, "shrink-0 pt-0.5")}>{k}</dt>
                          <dd className="min-w-0 break-words">{v}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {assetPaths.length > 0 && (
                    <div
                      className={
                        assetPaths.length > 1 && assetPaths.every((p) => IMAGE_EXT.includes(p.split(".").pop()?.toLowerCase() ?? ""))
                          ? "grid grid-cols-2 gap-2"
                          : "space-y-3"
                      }
                    >
                      {assetPaths.map((assetPath) => (
                        <AssetPreview
                          key={assetPath}
                          folder={viewing!.folder}
                          path={assetPath}
                          onReplace={async (f) => {
                            setStatus("replacing...");
                            await replaceKBAsset(viewing!.folder, assetPath, f);
                            setStatus("replaced — refresh to see the new version");
                          }}
                        />
                      ))}
                    </div>
                  )}
                  <div className="prose prose-sm dark:prose-invert max-w-none prose-a:text-accent prose-img:rounded-lg">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                      {renderedBody}
                    </ReactMarkdown>
                  </div>
                </>
              )}
              {status && <p className="text-xs text-muted">{status}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
