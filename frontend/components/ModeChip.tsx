"use client";

import { BookCheck, MessageCircle } from "lucide-react";
import type { ChatMode } from "@/lib/api";
import { cn } from "@/lib/cn";

// §12 chat-mode chip. Always carries a text label (never color alone);
// click toggles. "unserious" is shown as "Casual".
export const MODE_HINT: Record<ChatMode, string> = {
  unserious: "Casual: draws on your notes and recent chats",
  serious: "Serious: answers only from your knowledge base",
};

export function modeSwitchNotice(mode: ChatMode): string {
  return mode === "serious"
    ? "Switched to serious mode — answering from your notes only"
    : "Switched to casual mode — recent chats and your notes";
}

export default function ModeChip({ mode, onToggle }: { mode: ChatMode; onToggle: () => void }) {
  const serious = mode === "serious";
  return (
    <button
      onClick={onToggle}
      aria-pressed={serious}
      title={`${MODE_HINT[mode]}. Click to switch to ${serious ? "casual" : "serious"}.`}
      className={cn(
        "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors",
        serious ? "border-accent/60 bg-accent/10 font-semibold text-accent" : "border-line text-muted"
      )}
    >
      {serious ? <BookCheck size={14} /> : <MessageCircle size={14} />}
      Mode: {serious ? "Serious" : "Casual"}
    </button>
  );
}
