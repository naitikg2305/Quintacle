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

function fileIcon(ext: string): string {
  if (IMAGE_EXT.includes(ext)) return "🖼️";
  if (VIDEO_EXT.includes(ext)) return "🎬";
  if (ext === "pdf") return "📕";
  if (ext === "stl") return "📦";
  if (ext === "docx") return "📃";
  if (SPREADSHEET_EXT.includes(ext)) return "📊";
  return "📎";
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

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Browse Files</h1>

      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the whole knowledge base — filename or content..."
          className="w-full border rounded px-3 py-2 text-sm"
        />
        {query.trim() && (
          <div className="absolute z-10 mt-1 w-full max-h-80 overflow-y-auto border rounded bg-white dark:bg-black shadow-lg">
            {searching && <p className="text-xs opacity-60 p-2">searching...</p>}
            {!searching && results.length === 0 && <p className="text-xs opacity-60 p-2">No matches.</p>}
            {!searching &&
              results.map((r) => (
                <button
                  key={`${r.folder}/${r.slug}`}
                  onClick={() => openResult(r.folder, r.slug)}
                  className="block w-full text-left px-3 py-2 text-sm hover:bg-black/5 dark:hover:bg-white/5 border-b last:border-b-0"
                >
                  <span className="font-medium">{r.slug}</span>
                  <span className="opacity-50"> — {r.folder}</span>
                  {r.snippet && <p className="text-xs opacity-60 truncate">{r.snippet}</p>}
                </button>
              ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-1 text-sm border-b pb-2">
        <button onClick={() => setCurrentPath("")} className="hover:underline opacity-80">
          Knowledge Base
        </button>
        {crumbs.map((crumb, i) => {
          const pathToHere = crumbs.slice(0, i + 1).join("/");
          return (
            <span key={pathToHere} className="flex items-center gap-1">
              <span className="opacity-40">/</span>
              <button onClick={() => setCurrentPath(pathToHere)} className="hover:underline opacity-80">
                {crumb}
              </button>
            </span>
          );
        })}
        {currentPath && (
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={createEntry}
              className="text-xs border rounded px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5 whitespace-nowrap"
            >
              + New entry
            </button>
            <a
              href={`/kb/folder?path=${encodeURIComponent(currentPath)}`}
              className="text-xs border rounded px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5 whitespace-nowrap"
            >
              💬 Chat this folder →
            </a>
          </div>
        )}
      </div>

      <div className="grid grid-cols-12 gap-4" style={{ height: "calc(100vh - 220px)", minHeight: 450 }}>
        <div className="col-span-5 border rounded p-3 overflow-y-auto">
          <div className="grid grid-cols-3 gap-3">
            {folders.map((name) => {
              const path = currentPath ? `${currentPath}/${name}` : name;
              return (
                <button
                  key={path}
                  onClick={() => setCurrentPath(path)}
                  className="flex flex-col items-center gap-1 p-2 rounded hover:bg-black/5 dark:hover:bg-white/5 text-center"
                >
                  <span className="text-3xl">📁</span>
                  <span className="text-xs break-words">{name}</span>
                </button>
              );
            })}
            {files.map((slug) => (
              <button
                key={slug}
                onClick={() => openFile(slug)}
                className={`flex flex-col items-center gap-1 p-2 rounded text-center ${
                  viewing?.slug === slug ? "bg-black/10 dark:bg-white/10" : "hover:bg-black/5 dark:hover:bg-white/5"
                }`}
              >
                <span className="text-3xl">📄</span>
                <span className="text-xs break-words">{slug}.md</span>
              </button>
            ))}
            {rawFiles.map((name) => (
              <button
                key={name}
                onClick={() => openRawFile(name)}
                className={`flex flex-col items-center gap-1 p-2 rounded text-center ${
                  viewingRawFile === name ? "bg-black/10 dark:bg-white/10" : "hover:bg-black/5 dark:hover:bg-white/5"
                }`}
              >
                <span className="text-3xl">{fileIcon(name.split(".").pop()?.toLowerCase() ?? "")}</span>
                <span className="text-xs break-words">{name}</span>
              </button>
            ))}
          </div>
          {folders.length === 0 && files.length === 0 && rawFiles.length === 0 && (
            <p className="text-sm opacity-60 p-2">
              {currentPath ? "Empty folder." : "Nothing in the Knowledge Base yet."}
            </p>
          )}
        </div>

        <div className="col-span-7 border rounded p-4 overflow-y-auto">
          {!viewing && !viewingRawFile && <p className="text-sm opacity-60">Select a file to view it.</p>}
          {viewingRawFile && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs opacity-60">
                  {currentPath}/{viewingRawFile}
                </p>
                <a
                  href={kbAssetUrl(currentPath, viewingRawFile)}
                  target="_blank"
                  rel="noreferrer"
                  className="border rounded px-3 py-1 text-xs"
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
              {status && <p className="text-xs opacity-60">{status}</p>}
            </div>
          )}
          {viewing && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs opacity-60">
                  {viewing.folder}/{viewing.slug}.md
                </p>
                <div className="flex gap-2">
                  {!editing && (
                    <button onClick={startEditing} className="border rounded px-3 py-1 text-xs">
                      Edit
                    </button>
                  )}
                  {editing && (
                    <>
                      <button onClick={saveEdit} className="border rounded px-3 py-1 text-xs bg-black text-white dark:bg-white dark:text-black">
                        Save
                      </button>
                      <button onClick={() => setEditing(false)} className="border rounded px-3 py-1 text-xs">
                        Cancel
                      </button>
                    </>
                  )}
                  <label className="border rounded px-3 py-1 text-xs cursor-pointer">
                    📎 Attach file
                    <input
                      type="file"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) attachFile(f);
                      }}
                    />
                  </label>
                  <button onClick={continueInChat} className="border rounded px-3 py-1 text-xs">
                    Continue in chat →
                  </button>
                </div>
              </div>

              {editing ? (
                <div className="space-y-3">
                  <div className="space-y-1">
                    <p className="text-xs opacity-60">Fields</p>
                    {fieldRows.map((row, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <input
                          className="border rounded px-2 py-1 text-xs w-1/3"
                          placeholder="key"
                          value={row.key}
                          onChange={(e) =>
                            setFieldRows(fieldRows.map((r, j) => (j === i ? { ...r, key: e.target.value } : r)))
                          }
                        />
                        <input
                          className="border rounded px-2 py-1 text-xs flex-1"
                          placeholder="value"
                          value={row.value}
                          onChange={(e) =>
                            setFieldRows(fieldRows.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))
                          }
                        />
                        <button
                          onClick={() => setFieldRows(fieldRows.filter((_, j) => j !== i))}
                          className="text-xs opacity-60 hover:opacity-100"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                    <button
                      onClick={() => setFieldRows([...fieldRows, { key: "", value: "" }])}
                      className="text-xs underline opacity-60 hover:opacity-100"
                    >
                      + add field
                    </button>
                  </div>
                  <textarea
                    className="w-full border rounded p-2 text-sm font-mono"
                    rows={20}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                  />
                </div>
              ) : (
                <>
                  {Object.keys(viewing.fields).length > 0 && (
                    <div className="border rounded p-2 text-sm space-y-1">
                      {Object.entries(viewing.fields).map(([k, v]) => (
                        <p key={k}>
                          <span className="opacity-60">{k}:</span> {v}
                        </p>
                      ))}
                    </div>
                  )}
                  {assetPaths.length > 0 && (
                    <div className={assetPaths.length > 1 && assetPaths.every((p) => IMAGE_EXT.includes(p.split(".").pop()?.toLowerCase() ?? "")) ? "grid grid-cols-2 gap-2" : "space-y-3"}>
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
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                      {renderedBody}
                    </ReactMarkdown>
                  </div>
                </>
              )}
              {status && <p className="text-xs opacity-60">{status}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
