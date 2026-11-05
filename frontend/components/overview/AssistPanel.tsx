"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Inbox, Lock, Send, Sparkles } from "lucide-react";
import ChatLog from "@/components/ChatLog";
import ModeChip from "@/components/ModeChip";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import { archiveTranscript, newChatSessionId, ChatMessage, ChatMode, chatWithKB, DEFAULT_LOCAL_MODEL, listChatModels, privateHandoffNotice } from "@/lib/api";

// The overview's right column: a compact chat (same /kb/chat, same sticky
// §12 mode, same model the Chat page last picked) over a capture box that
// hands its text to the Chat page's scratchpad for the real review flow.
// Leaving the page archives the conversation like Chat's "New" does, so
// these asks land on the same timeline as every other chat.
export default function AssistPanel() {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<ChatMode>("unserious");
  const [model, setModel] = useState<string>(DEFAULT_LOCAL_MODEL);
  const [capture, setCapture] = useState("");
  // 2026-11-05: shown when a cloud request left private-note turns out.
  const [privacyNotice, setPrivacyNotice] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  // 2026-11-05: always saved — per-reply autosave into ONE transcript (same
  // session id), final save (with soft-fact extraction) on leave.
  const [sessionId] = useState(newChatSessionId);
  const sessionIdRef = useRef(sessionId);

  useEffect(() => {
    const leavingId = sessionIdRef.current;
    listChatModels()
      .then((list) => {
        let saved: string | null = null;
        try {
          saved = localStorage.getItem("quintacle.chatModel");
        } catch {}
        if (saved && list.some((m) => m.id === saved)) setModel(saved);
      })
      .catch(() => {});
    return () => {
      if (messagesRef.current.length > 0)
        archiveTranscript(messagesRef.current, null, true, false, { sessionId: leavingId, keepalive: true }).catch(() => {});
    };
  }, []);

  useEffect(() => {
    messagesRef.current = messages;
    const last = messages[messages.length - 1];
    if (last && last.role === "assistant")
      archiveTranscript(messages, null, true, false, { sessionId, final: false }).catch(() => {});
  }, [messages, sessionId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setPrivacyNotice(null);
    try {
      const res = await chatWithKB(next, true, false, undefined, model, undefined, mode);
      if (res.mode) setMode(res.mode);
      if (res.private_stripped) setPrivacyNotice(privateHandoffNotice(res.private_stripped));
      // Keep private_notes on the reply so a later cloud request strips it.
      setMessages([
        ...next,
        { role: "assistant", content: res.reply, model, ...(res.private_notes?.length ? { private_notes: res.private_notes } : {}) },
      ]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: `Couldn't reach the chat backend — ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  }

  function sendToScratchpad() {
    const text = capture.trim();
    if (!text) return;
    router.push(`/kb?draft=${encodeURIComponent(text)}`);
  }

  return (
    <div className="flex flex-col gap-4 lg:sticky lg:top-6">
      <Panel
        title="Assist"
        icon={Sparkles}
        actions={
          <Link href="/kb" className="flex items-center gap-1 text-xs text-muted hover:text-accent">
            Open Chat <ArrowUpRight size={12} />
          </Link>
        }
        bodyClassName="flex flex-col gap-3"
      >
        <div ref={logRef} className="max-h-[360px] min-h-[140px] space-y-2 overflow-y-auto">
          {messages.length === 0 ? (
            <p className="pt-8 text-center text-sm text-muted">Ask about anything in your notes — or your week.</p>
          ) : (
            <ChatLog messages={messages} busy={busy} />
          )}
          {busy && <p className="text-xs text-muted">Thinking…</p>}
        </div>
        {privacyNotice && (
          <p role="status" className="flex items-center gap-1.5 text-xs text-accent">
            <Lock size={12} /> {privacyNotice}
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="flex gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything…"
            className="min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm outline-none focus:border-accent/60"
          />
          <Button type="submit" variant="primary" size="sm" disabled={busy || !input.trim()} aria-label="Send">
            <Send size={14} />
          </Button>
        </form>
        <ModeChip mode={mode} onToggle={() => setMode(mode === "serious" ? "unserious" : "serious")} />
      </Panel>

      <Panel title="Capture" icon={Inbox} bodyClassName="flex flex-col gap-2">
        <Textarea
          value={capture}
          onChange={(e) => setCapture(e.target.value)}
          rows={4}
          placeholder="Anything — a meal, a thought, a todo, a note…"
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted">Reviewed in the scratchpad before anything saves.</p>
          <Button variant="primary" size="sm" onClick={sendToScratchpad} disabled={!capture.trim()} className="shrink-0 whitespace-nowrap">
            <Sparkles size={14} /> Sort with AI
          </Button>
        </div>
      </Panel>
    </div>
  );
}
