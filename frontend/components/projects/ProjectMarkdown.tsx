"use client";

// Markdown the way Browse renders it (react-markdown + GFM + highlight), with
// the website's one twist: relative image/link targets resolve against the
// note's own KB folder (here via /kb/asset), so `![](assets/x.png)` and the
// `[asset](assets/x.stl)` lines a drop appends both work.

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { kbAssetUrl } from "@/lib/api";
import ImageLightbox from "@/components/ImageLightbox";

const isAbsolute = (s: string) => /^(https?:|data:|mailto:|#|\/)/i.test(s);

// `[asset](…)` lines and the drop's `<!-- filemeta -->` caption lines are
// plumbing — the files themselves are shown in the page's galleries.
export function stripAssetLines(content: string): string {
  return content
    .split("\n")
    .filter((l) => !/^\[asset\]\([^)]+\)\s*$/.test(l.trim()) && !l.trim().endsWith("<!-- filemeta -->"))
    .join("\n")
    .trim();
}

export default function ProjectMarkdown({ folder, content: raw }: { folder: string; content: string }) {
  const content = stripAssetLines(raw);
  if (!content) return null;
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none break-words prose-a:text-accent prose-img:rounded-lg prose-pre:max-w-full prose-pre:overflow-x-auto">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          img: ({ src, alt }) => {
            const s = typeof src === "string" ? src : "";
            if (!s) return null;
            return (
              <ImageLightbox
                src={isAbsolute(s) ? s : kbAssetUrl(folder, s)}
                alt={alt || ""}
                className="mx-auto my-4 block max-w-full rounded-lg border border-line bg-black/40"
              />
            );
          },
          a: ({ href, children }) => {
            const h = typeof href === "string" ? href : "";
            const resolved = !h || isAbsolute(h) ? h : kbAssetUrl(folder, h);
            const label = String(children) === "asset" ? h.split("/").pop() : children;
            return (
              <a href={resolved} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
