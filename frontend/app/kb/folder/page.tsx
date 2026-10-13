"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  buildChatMessage,
  ChatMessage,
  chatWithKB,
  ChatSession,
  createChatSession,
  deleteChatSession,
  KBSuggestion,
  listChatSessions,
  loadChatSession,
  pushKBEntry,
  saveChatSession,
  sortKBEntry,
} from "@/lib/api";
import ChatLog from "@/components/ChatLog";

// A chat that only knows about — and only writes into — one folder (e.g. a
// person's log). Context sent to Claude is limited to that folder's entries
// (see run_kb_chat's folder param), and every push is forced into that same
// folder — never AI-guessed, never somewhere else in the KB.
export default function FolderChatPage() {
  return (
    <Suspense>
      <FolderChatPageInner />
    </Suspense>
  );
}

function FolderChatPageInner() {
  const path = useSearchParams().get("path") ?? "";

  const [chatLog, setChatLog] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatFile, setChatFile] = useState<File | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("");

  const [scratchpad, setScratchpad] = useState("");
  const [suggestion, setSuggestion] = useState<KBSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    listChatSessions().then(setSessions);
  }, []);

  function newChat() {
    setSessionId(null);
    setSessionTitle("");
    setChatLog([]);
    setChatFile(null);
  }

  async function openSession(id: string, title: string) {
    setSessionId(id);
    setSessionTitle(title);
    setChatLog(await loadChatSession(id));
    setChatFile(null);
  }

  async function deleteSession() {
    if (!sessionId) return;
    if (!confirm("Delete this chat? This can't be undone.")) return;
    await deleteChatSession(sessionId);
    newChat();
    setSessions(await listChatSessions());
  }

  async function sendChat() {
    if ((!chatInput.trim() && !chatFile) || !path) return;
    const inputForTitle = chatInput;
    let userMessage: ChatMessage;
    try {
      userMessage = await buildChatMessage(chatInput, chatFile);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
      return;
    }
    const next = [...chatLog, userMessage];
    setChatLog(next);
    setChatInput("");
    setChatFile(null);
    setChatBusy(true);

    let id = sessionId;
    let title = sessionTitle;
    if (!id) {
      title = `${path.split("/").pop()}: ${inputForTitle.slice(0, 40) || "Chat"}`;
      const created = await createChatSession(title);
      id = created.id;
      setSessionId(id);
      setSessionTitle(title);
    }

    let finalLog = next;
    try {
      const { reply } = await chatWithKB(next, true, false, path);
      finalLog = [...next, { role: "assistant" as const, content: reply }];
    } catch (e) {
      finalLog = [...next, { role: "assistant" as const, content: `(error: ${e instanceof Error ? e.message : String(e)})` }];
    }
    setChatLog(finalLog);
    await saveChatSession(id, title, finalLog);
    setSessions(await listChatSessions());
    setChatBusy(false);
  }

  function addToScratchpad(text: string) {
    setScratchpad((prev) => (prev ? `${prev}\n\n${text}` : text));
  }

  async function sortWithAI() {
    if (!scratchpad.trim() || !path) return;
    setBusy(true);
    setStatus("sorting...");
    try {
      setSuggestion(await sortKBEntry(scratchpad, { folder: path }));
      setStatus(null);
    } catch (e) {
      setStatus(`sort failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  async function push() {
    if (!suggestion) return;
    setBusy(true);
    setStatus("pushing...");
    await pushKBEntry(suggestion);
    setStatus(`pushed into ${path}`);
    setScratchpad("");
    setSuggestion(null);
    setBusy(false);
  }

  if (!path) {
    return <p className="text-sm opacity-60 max-w-3xl mx-auto">No folder given — open this from Browse.</p>;
  }

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold">Folder Chat</h1>
      <p className="text-sm px-3 py-2 rounded bg-black/5 dark:bg-white/10">
        Only knows about, and only writes into: <span className="font-medium">{path}</span>
      </p>

      <div className="grid grid-cols-12 gap-4" style={{ height: "60vh" }}>
        <div className="col-span-7 border rounded flex flex-col overflow-hidden">
          <div className="p-3 border-b space-y-2 shrink-0">
            <div className="flex items-center gap-2 flex-wrap text-xs">
              <select
                className="border rounded px-2 py-1"
                value={sessionId ?? ""}
                onChange={(e) =>
                  e.target.value ? openSession(e.target.value, sessions.find((s) => s.id === e.target.value)?.title ?? "") : newChat()
                }
              >
                <option value="">New chat</option>
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
              <button onClick={newChat} className="border rounded px-2 py-1">
                + New chat
              </button>
              {sessionId && (
                <button onClick={deleteSession} className="border rounded px-2 py-1 text-red-600 dark:text-red-400">
                  Delete
                </button>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {chatLog.length === 0 && <p className="text-sm opacity-60">Ask or discuss anything about {path}.</p>}
            <ChatLog messages={chatLog} busy={chatBusy} onAddToScratchpad={addToScratchpad} />
          </div>

          {chatFile && (
            <div className="px-3 pb-2 shrink-0 flex items-center gap-2 text-xs">
              <span className="opacity-70">📎 {chatFile.name}</span>
              <button onClick={() => setChatFile(null)} className="underline opacity-70 hover:opacity-100">
                remove
              </button>
            </div>
          )}

          <div className="p-3 border-t flex gap-2 shrink-0">
            <label className="border rounded px-2 py-1 text-sm cursor-pointer shrink-0" title="Attach a photo or PDF">
              📎
              <input
                type="file"
                accept="image/*,.pdf"
                className="hidden"
                onChange={(e) => setChatFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="Say something..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendChat()}
            />
            <button
              onClick={sendChat}
              disabled={chatBusy || (!chatInput.trim() && !chatFile)}
              className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>

        <div className="col-span-5 border rounded p-3 flex flex-col overflow-y-auto">
          <h2 className="font-medium text-sm mb-2">Add to {path}</h2>
          <textarea
            className="w-full border rounded p-2 text-sm flex-1"
            rows={8}
            placeholder="Write something to file into this folder..."
            value={scratchpad}
            onChange={(e) => setScratchpad(e.target.value)}
          />
          <button
            onClick={sortWithAI}
            disabled={busy || !scratchpad.trim()}
            className="w-full mt-2 bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Sort with AI
          </button>

          {suggestion && (
            <div className="space-y-2 border-t pt-3 mt-3">
              <label className="block text-sm">
                Title
                <input
                  className="block w-full border rounded px-2 py-1 mt-1 text-sm"
                  value={suggestion.title}
                  onChange={(e) => setSuggestion({ ...suggestion, title: e.target.value })}
                />
              </label>
              <label className="block text-sm">
                Content
                <textarea
                  className="block w-full border rounded p-2 mt-1 text-sm"
                  rows={6}
                  value={suggestion.content}
                  onChange={(e) => setSuggestion({ ...suggestion, content: e.target.value })}
                />
              </label>
              <button
                onClick={push}
                disabled={busy}
                className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
              >
                Push into {path}
              </button>
            </div>
          )}

          {status && <p className="text-sm opacity-70 mt-2">{status}</p>}
        </div>
      </div>
    </div>
  );
}
