"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { ChatContentBlock, ChatMessage, chatMessageText } from "@/lib/api";

function Attachment({ block }: { block: ChatContentBlock }) {
  if (block.type === "image") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={`data:${block.source.media_type};base64,${block.source.data}`}
        alt=""
        className="mb-1 max-h-40 rounded-lg border border-line"
      />
    );
  }
  if (block.type === "document") {
    return <p className="mb-1 text-xs text-muted">📎 PDF attached</p>;
  }
  return null;
}

export default function ChatLog({
  messages,
  busy,
  onAddToScratchpad,
}: {
  messages: ChatMessage[];
  busy?: boolean;
  onAddToScratchpad?: (text: string) => void;
}) {
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
                <Attachment key={bi} block={b} />
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
              {m.role === "assistant" && onAddToScratchpad && (
                <button onClick={() => onAddToScratchpad(text)} className="mt-1 text-xs text-accent/80 hover:text-accent hover:underline">
                  → add to scratchpad
                </button>
              )}
            </div>
          </div>
        );
      })}
      {busy && <p className="animate-pulse font-mono text-xs uppercase tracking-wider text-accent">thinking…</p>}
    </>
  );
}
