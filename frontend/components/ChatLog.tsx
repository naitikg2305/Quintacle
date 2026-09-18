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
        className="max-h-40 rounded border mb-1"
      />
    );
  }
  if (block.type === "document") {
    return <p className="text-xs opacity-70 mb-1">📎 PDF attached</p>;
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
              className={`inline-block rounded px-3 py-2 text-sm max-w-[85%] text-left ${
                m.role === "user" ? "bg-black text-white dark:bg-white dark:text-black" : "bg-black/5 dark:bg-white/10"
              }`}
            >
              {blocks.map((b, bi) => (
                <Attachment key={bi} block={b} />
              ))}
              {m.role === "assistant" ? (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                    {text}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{text}</p>
              )}
              {m.role === "assistant" && onAddToScratchpad && (
                <button onClick={() => onAddToScratchpad(text)} className="text-xs underline opacity-70 hover:opacity-100 mt-1">
                  → add to scratchpad
                </button>
              )}
            </div>
          </div>
        );
      })}
      {busy && <p className="text-sm opacity-60">thinking...</p>}
    </>
  );
}
