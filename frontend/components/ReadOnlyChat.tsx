"use client";

import { useState } from "react";
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
    <div className="border rounded flex flex-col overflow-hidden" style={{ height: "50vh" }}>
      <div className="p-3 border-b shrink-0">
        <h2 className="font-medium text-sm">Ask about your data</h2>
        <p className="text-xs opacity-60">Read-only — nothing here is saved or editable, just answers.</p>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {log.length === 0 && <p className="text-sm opacity-60">Ask anything — your goals, a document, a business idea, whatever's already in the app.</p>}
        <ChatLog messages={log} busy={busy} />
      </div>
      {file && (
        <div className="px-3 pb-2 shrink-0 flex items-center gap-2 text-xs">
          <span className="opacity-70">📎 {file.name}</span>
          <button onClick={() => setFile(null)} className="underline opacity-70 hover:opacity-100">
            remove
          </button>
        </div>
      )}
      {error && <p className="px-3 pb-1 text-xs text-red-600 dark:text-red-400 shrink-0">{error}</p>}
      <div className="p-3 border-t flex gap-2 shrink-0">
        <label className="border rounded px-2 py-1 text-sm cursor-pointer shrink-0" title="Attach a photo or PDF">
          📎
          <input type="file" accept="image/*,.pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <input
          className="flex-1 border rounded px-2 py-1 text-sm"
          placeholder="Ask a question..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button
          onClick={send}
          disabled={busy || (!input.trim() && !file)}
          className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
        >
          Ask
        </button>
      </div>
    </div>
  );
}
