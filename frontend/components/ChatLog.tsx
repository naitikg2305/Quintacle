"use client";

import { ReactNode, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { API_BASE, base64ToFile, ChatContentBlock, ChatMessage, chatMessageText } from "@/lib/api";

// --- clickable deep links in chat answers (next-wave §10) -------------------
// The model is instructed (core/nodes/kb/chat.py) to emit root-relative
// markdown links into the app's REAL routes; the renderer below decides what
// each href becomes. Only "/"-relative and http(s) hrefs ever become links —
// anything else (javascript:, data:, mailto:, a route that doesn't exist)
// renders as plain text. No raw HTML is ever rendered (react-markdown
// ignores HTML nodes without rehype-raw, which is deliberately not added).

// Every page the app actually serves (frontend/app/**/page.tsx). A chat link
// must match one of these pathnames to be client-side navigable — the note
// deep-link shape is /kb/browse?path=<folder>&open=<slug> (what Browse
// already reads on mount). /vault is deliberately absent: the vault is
// invisible to every model surface, so model output never gets a live link in.
const APP_ROUTES = new Set([
  "/",
  "/day",
  "/documents",
  "/finance",
  "/finance/cards",
  "/finance/investments",
  "/gallery",
  "/habits",
  "/home",
  "/journal",
  "/kb",
  "/kb/batch",
  "/kb/browse",
  "/kb/drop",
  "/kb/folder",
  "/kb/graph",
  "/people",
  "/profile",
  "/soft-record",
  "/stocks",
  "/sync",
  "/todos",
  "/travel",
  "/wardrobe",
]);

// Backend file endpoints (see lib/api.ts *AssetUrl helpers). These are API
// paths, not pages — and the Capacitor build does NOT run same-origin with
// the backend, so a bare "/kb/asset?..." href must be resolved against
// API_BASE at render time, never left for the browser to resolve itself.
const ASSET_ROUTES = new Set([
  "/kb/asset",
  "/wardrobe/asset",
  "/wardrobe/outfits/asset",
  "/grooming/asset",
  "/documents/asset",
  "/home/asset",
]);

function MarkdownLink({ href, children }: { href?: string; children?: ReactNode }) {
  const h = href ?? "";
  // External links keep working, in a new tab.
  if (/^https?:\/\//i.test(h)) {
    return (
      <a href={h} target="_blank" rel="noreferrer">
        {children}
      </a>
    );
  }
  // Root-relative only — "//evil.com" has no matching pathname below and
  // falls through to plain text.
  if (h.startsWith("/")) {
    const pathname = h.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
    if (ASSET_ROUTES.has(pathname)) {
      return (
        <a href={`${API_BASE}${h}`} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    }
    if (APP_ROUTES.has(pathname)) {
      return <Link href={h}>{children}</Link>;
    }
  }
  return <span>{children}</span>;
}

// --- chat TEXT → a file in the scratchpad tray (next-wave §10) --------------
// Images/PDFs got this bridge in §9; this is the same funnel for drafted
// text: the message becomes a real File among the pending drop attachments
// and flows through /drop like any dropped file.

// Fenced-block languages that name a real text-file format — a block tagged
// with one of these gets attached as that kind of file (contents only, no
// fence), so a drafted CSV lands in the tray as a usable .csv.
const LANG_EXT: Record<string, string> = {
  csv: "csv",
  tsv: "tsv",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  xml: "xml",
  html: "html",
  css: "css",
  markdown: "md",
  md: "md",
  text: "txt",
  txt: "txt",
  python: "py",
  py: "py",
  javascript: "js",
  js: "js",
  typescript: "ts",
  ts: "ts",
  sql: "sql",
  sh: "sh",
  bash: "sh",
};

type FencedBlock = { lang: string; ext: string; body: string; whole: boolean };

// Fenced code blocks with a known text-format language, parsed from the raw
// markdown (NOT the rendered tree — rehype-highlight has already shredded
// that into spans). `whole` marks a message that IS exactly one block.
function fencedBlocks(trimmedText: string): FencedBlock[] {
  const out: FencedBlock[] = [];
  const re = /```([^\n]*)\n([\s\S]*?)```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(trimmedText))) {
    const ext = LANG_EXT[m[1].trim().toLowerCase()];
    if (!ext) continue;
    out.push({
      lang: m[1].trim().toLowerCase(),
      ext,
      body: m[2].replace(/\n$/, ""),
      whole: m.index === 0 && m.index + m[0].length === trimmedText.length,
    });
  }
  return out;
}

// The whole message as a File: default .md with the full text — unless the
// message IS one fenced block with a known format, then only the block's
// contents with that extension.
function messageToFile(text: string): File {
  const t = text.trim();
  const blocks = fencedBlocks(t);
  if (blocks.length === 1 && blocks[0].whole) {
    return new File([blocks[0].body], `chat-draft.${blocks[0].ext}`, { type: "text/plain" });
  }
  return new File([t], "chat-draft.md", { type: "text/markdown" });
}

// Rebuild the File behind a message's image/PDF block so a photo DISCUSSED in
// chat can hop into the scratchpad's pending drop attachments (next-wave §9)
// and flow through /drop like any dropped file.
function blockToFile(block: ChatContentBlock): File | null {
  if (block.type === "image") {
    const ext = block.source.media_type.split("/")[1] ?? "png";
    return base64ToFile(block.source.data, block.source.media_type, `chat-photo.${ext === "jpeg" ? "jpg" : ext}`);
  }
  if (block.type === "document") {
    return base64ToFile(block.source.data, block.source.media_type, "chat-attachment.pdf");
  }
  return null;
}

function Attachment({ block, onAddToDrop }: { block: ChatContentBlock; onAddToDrop?: (file: File) => void }) {
  const addButton = onAddToDrop && (
    <button
      onClick={() => {
        const f = blockToFile(block);
        if (f) onAddToDrop(f);
      }}
      title="Queue this attachment on the scratchpad — it gets sorted and saved through the drop lane like any dropped file"
      className="mb-1 block text-xs text-accent/80 hover:text-accent hover:underline"
    >
      → add to scratchpad
    </button>
  );
  if (block.type === "image") {
    return (
      <div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`data:${block.source.media_type};base64,${block.source.data}`}
          alt=""
          className="mb-1 max-h-40 rounded-lg border border-line"
        />
        {addButton}
      </div>
    );
  }
  if (block.type === "document") {
    return (
      <div>
        <p className="mb-1 text-xs text-muted">📎 PDF attached</p>
        {addButton}
      </div>
    );
  }
  return null;
}

export default function ChatLog({
  messages,
  busy,
  onAddToScratchpad,
  onAddAttachmentToDrop,
  onEscalate,
  escalateModels,
}: {
  messages: ChatMessage[];
  busy?: boolean;
  onAddToScratchpad?: (text: string) => void;
  // Next-wave §9: a photo/PDF attached to a chat MESSAGE (the discussion
  // lane) can hop into the scratchpad's pending drop attachments.
  onAddAttachmentToDrop?: (file: File) => void;
  // Local-first chat: a reply that came from a `local:` model (known
  // client-side via message.model) gets an "Escalate ↗" affordance — pick a
  // cloud model and the SAME conversation up to that reply is re-sent to it,
  // appending the cloud answer alongside (never deleting) the local one.
  onEscalate?: (messageIndex: number, cloudModel: string) => void;
  escalateModels?: { id: string; label: string }[];
}) {
  // Which message's tiny cloud-model chooser is open (one at a time).
  const [escalatingIndex, setEscalatingIndex] = useState<number | null>(null);
  return (
    <>
      {messages.map((m, i) => {
        const blocks = typeof m.content === "string" ? [] : m.content.filter((b) => b.type !== "text");
        const text = chatMessageText(m.content);
        // Fenced blocks with a known text format, for the per-block attach
        // buttons — a message that IS one block is covered by "attach as
        // file" (which then uses the block's format), so it gets no extra button.
        const codeBlocks = m.role === "assistant" && onAddAttachmentToDrop ? fencedBlocks(text.trim()).filter((b) => !b.whole) : [];
        return (
          <div key={i} className={m.role === "user" ? "text-right" : ""}>
            <div
              className={`inline-block max-w-[92%] rounded-xl border px-3 py-2 text-left text-sm md:max-w-[85%] ${
                m.role === "user" ? "border-accent/30 bg-accent/15 text-foreground" : "border-line bg-surface-2"
              }`}
            >
              {blocks.map((b, bi) => (
                <Attachment key={bi} block={b} onAddToDrop={onAddAttachmentToDrop} />
              ))}
              {m.role === "assistant" ? (
                <div className="prose prose-sm dark:prose-invert max-w-none prose-img:rounded-lg prose-a:text-accent">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={{ a: MarkdownLink }}>
                    {text}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{text}</p>
              )}
              {m.role === "assistant" && (m.model || onAddToScratchpad || onAddAttachmentToDrop) && (
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                  {m.model && (
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted" title="Which model wrote this answer">
                      {m.model}
                    </span>
                  )}
                  {onAddToScratchpad && (
                    <button onClick={() => onAddToScratchpad(text)} className="text-xs text-accent/80 hover:text-accent hover:underline">
                      → add to scratchpad
                    </button>
                  )}
                  {onAddAttachmentToDrop && text.trim() && (
                    <button
                      onClick={() => onAddAttachmentToDrop(messageToFile(text))}
                      title="Turn this answer into a file in the scratchpad's attachment tray — Sort with AI sends it through the drop lane like any dropped file"
                      className="text-xs text-accent/80 hover:text-accent hover:underline"
                    >
                      → attach as file
                    </button>
                  )}
                  {codeBlocks.map((b, bi) => (
                    <button
                      key={bi}
                      onClick={() => onAddAttachmentToDrop!(new File([b.body], `chat-draft.${b.ext}`, { type: "text/plain" }))}
                      title={`Attach only this ${b.lang} block as a .${b.ext} file in the scratchpad's attachment tray`}
                      className="text-xs text-accent/80 hover:text-accent hover:underline"
                    >
                      → attach .{b.ext} block
                    </button>
                  ))}
                  {onEscalate && !!escalateModels?.length && m.model?.startsWith("local:") && (
                    <button
                      onClick={() => setEscalatingIndex(escalatingIndex === i ? null : i)}
                      title="Not good enough? Re-ask this same conversation on a cloud model — the cloud answer is added alongside this one for comparison."
                      className="text-xs text-accent/80 hover:text-accent hover:underline"
                    >
                      Escalate ↗
                    </button>
                  )}
                </div>
              )}
              {escalatingIndex === i && onEscalate && !!escalateModels?.length && (
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  {escalateModels.map((em) => (
                    <button
                      key={em.id}
                      onClick={() => {
                        setEscalatingIndex(null);
                        onEscalate(i, em.id);
                      }}
                      className="rounded-md border border-line px-2 py-0.5 text-[11px] text-muted transition-colors hover:border-accent/50 hover:text-accent"
                    >
                      {em.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
      {busy && <p className="animate-pulse font-mono text-xs uppercase tracking-wider text-accent">thinking…</p>}
    </>
  );
}
