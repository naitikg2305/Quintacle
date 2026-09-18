"use client";

import { useEffect, useState } from "react";

// Fetches the raw .docx bytes and converts to HTML client-side (mammoth) —
// rendered as page content, not a file link, so it neither downloads nor
// hands off to an external app on mobile (Android in particular routes a
// direct file link to Word/Excel instead of showing it in-page).
export default function DocxViewer({ url }: { url: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHtml(null);
    setError(null);
    let cancelled = false;
    (async () => {
      try {
        const mammoth = await import("mammoth");
        const res = await fetch(url);
        const buf = await res.arrayBuffer();
        const result = await mammoth.convertToHtml({ arrayBuffer: buf });
        if (!cancelled) setHtml(result.value);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (error) return <p className="text-sm text-red-600 dark:text-red-400">Couldn&apos;t render this document: {error}</p>;
  if (!html) return <p className="text-sm opacity-60">Loading document...</p>;

  return (
    <div
      className="prose prose-sm dark:prose-invert max-w-none border rounded p-4 overflow-auto max-h-[70vh]"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
