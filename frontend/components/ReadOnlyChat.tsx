"use client";

import { useState } from "react";
import { MessageSquare, Paperclip, SendHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { buildChatMessage, ChatMessage, chatWithKB } from "@/lib/api";
import ChatLog from "@/components/ChatLog";

// Query-only — no scratchpad, no sort/push, nothing ever gets written from
// here. Same backend endpoint as the main KB chat (which itself never writes
// on its own either), just with every write-adjacent affordance removed from
// the UI so this reads as unambiguously safe: ask about your data, get an
// answer, nothing changes. Ephemeral by design — no session persistence. A
// photo/PDF can still be attached to a question (e.g. "what's this
// document") — that's just extra context for one answer, not a write.
export default function ReadOnlyChat() {
  const [log, setLog] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    if (!input.trim() && !file) return;
    let userMessage: ChatMessage;
    try {
      userMessage = await buildChatMessage(input, file);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    setError(null);
    const next = [...log, userMessage];
    setLog(next);
    setInput("");
    setFile(null);
    setBusy(true);
    try {
      const { reply } = await chatWithKB(next, true, false);
      setLog([...next, { role: "assistant" as const, content: reply }]);
    } catch (e) {
      setLog([...next, { role: "assistant" as const, content: `(error: ${e instanceof Error ? e.message : String(e)})` }]);
    }
    setBusy(false);
  }

  return (
    <div className="flex h-[min(50dvh,480px)] flex-col overflow-hidden rounded-xl border border-line bg-surface/80 shadow-panel">
      <div className="shrink-0 border-b border-line px-4 py-2.5">
        <h2 className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
          <MessageSquare size={14} /> Ask about your data
        </h2>
        <p className="mt-0.5 text-xs text-muted">Read-only — nothing here is saved or editable, just answers.</p>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {log.length === 0 && (
          <p className="text-sm text-muted">Ask anything — your goals, a document, a business idea, whatever&apos;s already in the app.</p>
        )}
        <ChatLog messages={log} busy={busy} />
      </div>
      {file && (
        <div className="flex shrink-0 items-center gap-2 px-3 pb-2 text-xs">
          <span className="flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-1 text-muted">
            <Paperclip size={12} /> {file.name}
            <button onClick={() => setFile(null)} aria-label="Remove attachment" className="hover:text-foreground">
              <X size={12} />
            </button>
          </span>
        </div>
      )}
      {error && <p className="shrink-0 px-3 pb-1 text-xs text-danger">{error}</p>}
      <div className="flex shrink-0 gap-2 border-t border-line p-3">
        <label
          className="flex cursor-pointer items-center rounded-lg border border-line px-2.5 text-muted transition-colors hover:border-accent/50 hover:text-accent"
          title="Attach a photo or PDF"
        >
          <Paperclip size={18} />
          <input type="file" accept="image/*,.pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <Input
          className="flex-1"
          placeholder="Ask a question..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <Button variant="primary" onClick={send} disabled={busy || (!input.trim() && !file)} aria-label="Ask">
          <SendHorizontal size={18} />
        </Button>
      </div>
    </div>
  );
}
