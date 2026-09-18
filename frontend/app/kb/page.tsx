"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  base64ToFile,
  buildChatMessage,
  ChatMessage,
  ChatModel,
  chatWithKB,
  ChatSession,
  createChatSession,
  createGroomingItem,
  createGroomingRoutine,
  createMealFromIngredients,
  createOutfit,
  createWardrobeItem,
  createRoutine,
  deleteChatSession,
  generateImage,
  KBSuggestion,
  listChatModels,
  listChatSessions,
  loadChatSession,
  ParsedGroomingRoutineComposition,
  ParsedMealComposition,
  ParsedOutfitComposition,
  ParsedWorkoutRoutine,
  pushKBEntry,
  pushKBEntryWithAsset,
  readKBEntry,
  saveChatSession,
  sortKBEntry,
  suggestGroomingRoutine,
  suggestMealComposition,
  suggestOutfitComposition,
  suggestWorkoutRoutine,
} from "@/lib/api";
import MealCompositionEditor from "@/components/MealCompositionEditor";
import OutfitEditor from "@/components/OutfitEditor";
import GroomingRoutineEditor from "@/components/GroomingRoutineEditor";
import ChatLog from "@/components/ChatLog";

type TargetFile = { folder: string; slug: string; title: string };

export default function KBPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [scratchpad, setScratchpad] = useState("");
  const [suggestion, setSuggestion] = useState<KBSuggestion | null>(null);
  const [mealSuggestion, setMealSuggestion] = useState<ParsedMealComposition | null>(null);
  const [outfitSuggestion, setOutfitSuggestion] = useState<ParsedOutfitComposition | null>(null);
  const [groomingSuggestion, setGroomingSuggestion] = useState<ParsedGroomingRoutineComposition | null>(null);
  const [workoutSuggestion, setWorkoutSuggestion] = useState<ParsedWorkoutRoutine | null>(null);
  const [generatedImageFile, setGeneratedImageFile] = useState<File | null>(null);
  const [generatedImagePreviewUrl, setGeneratedImagePreviewUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [target, setTarget] = useState<TargetFile | null>(null);

  const [chatLog, setChatLog] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatFile, setChatFile] = useState<File | null>(null);
  const [useKB, setUseKB] = useState(true);
  const [models, setModels] = useState<ChatModel[]>([]);
  const [model, setModel] = useState<string | undefined>(undefined);
  const [chatBusy, setChatBusy] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("");

  async function refreshSessions() {
    setSessions(await listChatSessions());
  }

  useEffect(() => {
    refreshSessions();
    listChatModels().then((list) => {
      setModels(list);
      let saved: string | null = null;
      try {
        saved = localStorage.getItem("quintacle.chatModel");
      } catch {}
      setModel(list.some((m) => m.id === saved) ? (saved as string) : list[0]?.id);
    });
  }, []);

  function pickModel(id: string) {
    setModel(id);
    try {
      localStorage.setItem("quintacle.chatModel", id);
    } catch {}
  }

  async function openSession(id: string, title: string) {
    setSessionId(id);
    setSessionTitle(title);
    setChatLog(await loadChatSession(id));
    setTarget(null);
    setChatFile(null);
  }

  function newChat() {
    setSessionId(null);
    setSessionTitle("");
    setChatLog([]);
    setTarget(null);
    setChatFile(null);
  }

  async function deleteSession() {
    if (!sessionId) return;
    if (!confirm("Delete this chat? This can't be undone — push anything worth keeping into the Knowledge Base first.")) return;
    await deleteChatSession(sessionId);
    newChat();
    await refreshSessions();
  }

  async function continueInChatWith(folder: string, slug: string, content: string) {
    const firstLine = content.split("\n")[0] ?? "";
    const title = firstLine.replace(/^#\s*/, "").trim() || slug;
    const body = content.slice(firstLine.length).replace(/^\n+/, "");

    const created = await createChatSession(`Re: ${title}`);
    setSessionId(created.id);
    setSessionTitle(`Re: ${title}`);
    setChatLog([]);
    setUseKB(true);
    setTarget({ folder, slug, title });
    setScratchpad(body);
    setSuggestion(null);
    await refreshSessions();
  }

  useEffect(() => {
    const folder = searchParams.get("continueFolder");
    const slug = searchParams.get("continueSlug");
    if (folder && slug) {
      readKBEntry(folder, slug).then((entry) => continueInChatWith(entry.folder, entry.slug, entry.content));
      router.replace("/kb");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function stopTargeting() {
    setTarget(null);
    setSuggestion(null);
  }

  async function sortWithAI() {
    if (!scratchpad.trim()) return;
    setBusy(true);
    setStatus(target ? `updating "${target.title}"...` : "sorting...");
    try {
      setSuggestion(await sortKBEntry(scratchpad, target ? { folder: target.folder, slug: target.slug } : undefined));
      setMealSuggestion(null);
      setOutfitSuggestion(null);
      setGroomingSuggestion(null);
      setWorkoutSuggestion(null);
      setStatus(null);
    } catch (e) {
      setStatus(`sort failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  // Anthropic has no image generation model — this one call goes to a
  // separate OpenAI-backed endpoint (see lib/api.ts). The result flows
  // through the exact same scratchpad -> Sort with AI -> review -> push
  // pipeline as everything else, not a bespoke panel: the prompt becomes
  // scratchpad text, "Sort with AI" proposes a folder/title from it as
  // usual, and push() (below) attaches the generated image the same way a
  // dropped photo would be.
  async function generateImageFromPrompt() {
    if (!scratchpad.trim()) return;
    setBusy(true);
    setStatus("generating image...");
    try {
      const { data, mime_type } = await generateImage(scratchpad);
      const file = base64ToFile(data, mime_type, "generated.png");
      setGeneratedImageFile(file);
      if (generatedImagePreviewUrl) URL.revokeObjectURL(generatedImagePreviewUrl);
      setGeneratedImagePreviewUrl(URL.createObjectURL(file));
      setStatus(null);
    } catch (e) {
      setStatus(`generate failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  function clearGeneratedImage() {
    if (generatedImagePreviewUrl) URL.revokeObjectURL(generatedImagePreviewUrl);
    setGeneratedImageFile(null);
    setGeneratedImagePreviewUrl(null);
  }

  async function push() {
    if (!suggestion) return;
    setBusy(true);
    setStatus("pushing...");
    if (generatedImageFile) {
      await pushKBEntryWithAsset(suggestion, [generatedImageFile]);
    } else {
      await pushKBEntry(suggestion);
    }
    setStatus(`pushed into ${suggestion.folder}`);
    setScratchpad("");
    setSuggestion(null);
    setTarget(null);
    clearGeneratedImage();
    setBusy(false);
  }

  // Discuss a dish in chat, add it to the scratchpad, then compose it from
  // your real ingredient library — matched ingredients use their actual
  // stored macros (not a fresh guess), only genuinely new ones get an AI
  // estimate. Independent of the KB-entry suggestion above; either can be open.
  async function suggestMeal() {
    if (!scratchpad.trim()) return;
    setBusy(true);
    setStatus("composing...");
    try {
      const result = await suggestMealComposition(scratchpad);
      setMealSuggestion({ type: "meal_composition", ...result });
      setSuggestion(null);
      setOutfitSuggestion(null);
      setGroomingSuggestion(null);
      setWorkoutSuggestion(null);
      setStatus(null);
    } catch (e) {
      setStatus(`compose failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  async function pushMeal() {
    if (!mealSuggestion) return;
    setBusy(true);
    setStatus("saving meal preset...");
    await createMealFromIngredients(mealSuggestion.meal_name, mealSuggestion.components);
    setStatus(`saved "${mealSuggestion.meal_name}" as a meal preset`);
    setScratchpad("");
    setMealSuggestion(null);
    setBusy(false);
  }

  // Same idea as suggestMeal()/pushMeal() but for outfits — a "simple
  // question from the chat" against the real wardrobe item library.
  async function suggestOutfit() {
    if (!scratchpad.trim()) return;
    setBusy(true);
    setStatus("composing...");
    try {
      const result = await suggestOutfitComposition(scratchpad);
      setOutfitSuggestion({ type: "outfit_composition", ...result });
      setSuggestion(null);
      setMealSuggestion(null);
      setGroomingSuggestion(null);
      setWorkoutSuggestion(null);
      setStatus(null);
    } catch (e) {
      setStatus(`compose failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  async function pushOutfit() {
    if (!outfitSuggestion) return;
    setBusy(true);
    setStatus("saving outfit...");
    for (const it of outfitSuggestion.items) {
      if (it.is_new) await createWardrobeItem(it.name, it.category, it.description ?? "");
    }
    await createOutfit(
      outfitSuggestion.outfit_name,
      outfitSuggestion.items.map((it) => it.name)
    );
    setStatus(`saved "${outfitSuggestion.outfit_name}" as an outfit`);
    setScratchpad("");
    setOutfitSuggestion(null);
    setBusy(false);
  }

  // Same idea again, for a grooming routine — against the real product library.
  async function suggestGrooming() {
    if (!scratchpad.trim()) return;
    setBusy(true);
    setStatus("composing...");
    try {
      const result = await suggestGroomingRoutine(scratchpad);
      setGroomingSuggestion({ type: "grooming_routine_composition", ...result });
      setSuggestion(null);
      setMealSuggestion(null);
      setOutfitSuggestion(null);
      setWorkoutSuggestion(null);
      setStatus(null);
    } catch (e) {
      setStatus(`compose failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  async function pushGrooming() {
    if (!groomingSuggestion) return;
    setBusy(true);
    setStatus("saving routine...");
    for (const s of groomingSuggestion.steps) {
      if (s.is_new) await createGroomingItem(s.name, s.category, s.description ?? "");
    }
    await createGroomingRoutine(
      groomingSuggestion.routine_name,
      groomingSuggestion.steps.map((s) => s.name)
    );
    setStatus(`saved "${groomingSuggestion.routine_name}" as a grooming routine`);
    setScratchpad("");
    setGroomingSuggestion(null);
    setBusy(false);
  }

  // Same idea again, for a workout routine — against the real logged
  // exercise-name library. This is the piece that was missing: chat could
  // only ever save a plain KB note about a routine, never a real structured
  // one a future "did a pull day" drop can actually match against.
  async function suggestWorkout() {
    if (!scratchpad.trim()) return;
    setBusy(true);
    setStatus("composing...");
    try {
      const result = await suggestWorkoutRoutine(scratchpad);
      setWorkoutSuggestion({ type: "workout_routine", ...result });
      setSuggestion(null);
      setMealSuggestion(null);
      setOutfitSuggestion(null);
      setGroomingSuggestion(null);
      setStatus(null);
    } catch (e) {
      setStatus(`compose failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  async function pushWorkout() {
    if (!workoutSuggestion) return;
    setBusy(true);
    setStatus("saving routine...");
    await createRoutine(workoutSuggestion.name, workoutSuggestion.exercises);
    setStatus(`saved "${workoutSuggestion.name}" as a workout routine`);
    setScratchpad("");
    setWorkoutSuggestion(null);
    setBusy(false);
  }

  async function sendChat() {
    if (!chatInput.trim() && !chatFile) return;
    setChatError(null);
    const inputForTitle = chatInput;
    let userMessage: ChatMessage;
    try {
      userMessage = await buildChatMessage(chatInput, chatFile);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
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
      title = inputForTitle.slice(0, 60) || "Chat";
      const created = await createChatSession(title);
      id = created.id;
      setSessionId(id);
      setSessionTitle(title);
    }

    let finalLog = next;
    try {
      const { reply } = await chatWithKB(next, useKB, false, undefined, model);
      finalLog = [...next, { role: "assistant" as const, content: reply }];
    } catch (e) {
      finalLog = [...next, { role: "assistant" as const, content: `(error: ${e instanceof Error ? e.message : String(e)})` }];
    }
    setChatLog(finalLog);
    await saveChatSession(id, title, finalLog);
    await refreshSessions();
    setChatBusy(false);
  }

  function addToScratchpad(text: string) {
    setScratchpad((prev) => (prev ? `${prev}\n\n${text}` : text));
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Knowledge Base</h1>

      <div className="grid grid-cols-12 gap-4" style={{ height: "calc(100vh - 180px)", minHeight: 500 }}>
        {/* Chat — the main, GPT/Claude-style panel */}
        <div className="col-span-8 border rounded flex flex-col overflow-hidden">
          <div className="p-3 border-b space-y-2 shrink-0">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <h2 className="font-medium text-sm">Chat</h2>
              <div className="flex gap-3 text-xs items-center">
                <label className="flex items-center gap-1">
                  <input type="checkbox" checked={useKB} onChange={(e) => setUseKB(e.target.checked)} />
                  Use Knowledge Base
                </label>
                <label className="flex items-center gap-1" title="Which model answers — price is $ per 1M tokens in / out. Web search is always on.">
                  Model
                  <select
                    className="border rounded px-1 py-0.5 bg-transparent"
                    value={model ?? ""}
                    onChange={(e) => pickModel(e.target.value)}
                  >
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label} ({m.price})
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
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
                  Delete this chat
                </button>
              )}
            </div>
            {target && (
              <p className="text-xs opacity-70">
                Continuing on <strong>{target.title}</strong> ({target.folder})
              </p>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {chatLog.length === 0 && (
              <p className="text-sm opacity-60">
                {useKB ? "Ask about anything already in your knowledge base." : "Just banter — nothing here is saved."}
              </p>
            )}
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

          {chatError && (
            <div className="px-3 pb-2 shrink-0 text-xs text-red-600 dark:text-red-400">⚠ {chatError}</div>
          )}
          <div className="p-3 border-t flex gap-2 shrink-0">
            <label className="border rounded px-2 py-1 text-sm cursor-pointer shrink-0" title="Attach a photo or PDF">
              📎
              <input
                type="file"
                accept="image/*,.pdf"
                className="hidden"
                onChange={(e) => {
                  setChatError(null);
                  setChatFile(e.target.files?.[0] ?? null);
                }}
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

        {/* Scratchpad — visible alongside the chat the whole time */}
        <div className="col-span-4 border rounded p-3 flex flex-col overflow-y-auto">
          <h2 className="font-medium text-sm mb-2">Scratchpad</h2>
          {target && (
            <div className="text-xs bg-black/5 dark:bg-white/10 rounded px-2 py-1 mb-2 flex items-center justify-between gap-2">
              <span>
                Updating <strong>{target.title}</strong>
              </span>
              <button onClick={stopTargeting} className="underline opacity-70 hover:opacity-100 shrink-0">
                new entry instead
              </button>
            </div>
          )}
          <textarea
            className="w-full border rounded p-2 text-sm flex-1"
            rows={10}
            placeholder="Write out whatever you're thinking as you go..."
            value={scratchpad}
            onChange={(e) => setScratchpad(e.target.value)}
          />
          {generatedImagePreviewUrl && (
            <div className="mt-2 space-y-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={generatedImagePreviewUrl} alt="" className="max-w-full rounded border" />
              <button onClick={clearGeneratedImage} className="text-xs underline opacity-70 hover:opacity-100">
                ✕ remove generated image
              </button>
            </div>
          )}
          <div className="flex gap-2 mt-2 flex-wrap">
            <button
              onClick={sortWithAI}
              disabled={busy || !scratchpad.trim()}
              className="flex-1 bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              {target ? "Update with AI" : "Sort with AI"}
            </button>
            <button
              onClick={suggestMeal}
              disabled={busy || !scratchpad.trim()}
              className="flex-1 border rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Suggest meal
            </button>
            <button
              onClick={suggestOutfit}
              disabled={busy || !scratchpad.trim()}
              className="flex-1 border rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Suggest outfit
            </button>
            <button
              onClick={suggestGrooming}
              disabled={busy || !scratchpad.trim()}
              className="flex-1 border rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Suggest grooming routine
            </button>
            <button
              onClick={suggestWorkout}
              disabled={busy || !scratchpad.trim()}
              className="flex-1 border rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Suggest workout routine
            </button>
            <button
              onClick={generateImageFromPrompt}
              disabled={busy || !scratchpad.trim()}
              className="flex-1 border rounded px-4 py-2 text-sm disabled:opacity-40"
              title="Uses the scratchpad text as the image prompt"
            >
              🎨 Generate image
            </button>
          </div>

          {mealSuggestion && (
            <div className="space-y-2 border-t pt-3 mt-3">
              <MealCompositionEditor value={mealSuggestion} onChange={setMealSuggestion} />
              <button
                onClick={pushMeal}
                disabled={busy}
                className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
              >
                Save as meal preset
              </button>
            </div>
          )}

          {outfitSuggestion && (
            <div className="space-y-2 border-t pt-3 mt-3">
              <OutfitEditor value={outfitSuggestion} onChange={setOutfitSuggestion} />
              <button
                onClick={pushOutfit}
                disabled={busy}
                className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
              >
                Save as outfit
              </button>
            </div>
          )}

          {groomingSuggestion && (
            <div className="space-y-2 border-t pt-3 mt-3">
              <GroomingRoutineEditor value={groomingSuggestion} onChange={setGroomingSuggestion} />
              <button
                onClick={pushGrooming}
                disabled={busy}
                className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
              >
                Save as grooming routine
              </button>
            </div>
          )}

          {workoutSuggestion && (
            <div className="space-y-2 border-t pt-3 mt-3">
              <input
                className="w-full border rounded px-2 py-1 text-sm"
                placeholder="routine name"
                value={workoutSuggestion.name}
                onChange={(e) => setWorkoutSuggestion({ ...workoutSuggestion, name: e.target.value })}
              />
              {workoutSuggestion.exercises.map((ex, ei) => (
                <div key={ei} className="flex gap-1 items-center text-xs">
                  <input
                    className="border rounded px-1 py-0.5 flex-1"
                    value={ex}
                    onChange={(e) =>
                      setWorkoutSuggestion({
                        ...workoutSuggestion,
                        exercises: workoutSuggestion.exercises.map((x, xi) => (xi === ei ? e.target.value : x)),
                      })
                    }
                  />
                  <button
                    onClick={() =>
                      setWorkoutSuggestion({
                        ...workoutSuggestion,
                        exercises: workoutSuggestion.exercises.filter((_, xi) => xi !== ei),
                      })
                    }
                    className="opacity-50 hover:opacity-100 px-1"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                onClick={() => setWorkoutSuggestion({ ...workoutSuggestion, exercises: [...workoutSuggestion.exercises, ""] })}
                className="text-xs underline opacity-70 hover:opacity-100"
              >
                + add exercise
              </button>
              <button
                onClick={pushWorkout}
                disabled={busy}
                className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
              >
                Save as workout routine
              </button>
            </div>
          )}

          {suggestion && (
            <div className="space-y-2 border-t pt-3 mt-3">
              <label className="block text-sm">
                Folder
                <input
                  className="block w-full border rounded px-2 py-1 mt-1 text-sm"
                  value={suggestion.folder}
                  onChange={(e) => setSuggestion({ ...suggestion, folder: e.target.value })}
                />
              </label>
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
                  rows={8}
                  value={suggestion.content}
                  onChange={(e) => setSuggestion({ ...suggestion, content: e.target.value })}
                />
              </label>
              <button
                onClick={push}
                disabled={busy}
                className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
              >
                {target ? "Push update" : "Push to Knowledge Base"}
              </button>
            </div>
          )}

          {status && <p className="text-sm opacity-70 mt-2">{status}</p>}
        </div>
      </div>
    </div>
  );
}
