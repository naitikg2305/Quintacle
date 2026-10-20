"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { base64ToFile, ChatContentBlock, ChatMessage, chatMessageText } from "@/lib/api";

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
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                    {text}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{text}</p>
              )}
              {m.role === "assistant" && (m.model || onAddToScratchpad) && (
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
