"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  archiveTranscript,
  base64ToFile,
  buildChatMessage,
  ChatMessage,
  ChatModel,
  chatWithKB,
  createGroomingItem,
  createGroomingRoutine,
  createMealFromIngredients,
  createOutfit,
  createWardrobeItem,
  createRoutine,
  generateImage,
  KBSuggestion,
  listChatModels,
  ParsedGroomingRoutineComposition,
  ParsedMealComposition,
  ParsedOutfitComposition,
  ParsedWorkoutRoutine,
  pushKBEntry,
  pushKBEntryWithAsset,
  readKBEntry,
  recordThat,
  RecordThatProposal,
  saveRecordThat,
  searchTranscripts,
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
import {
  Archive,
  ArchiveX,
  BookmarkPlus,
  Database,
  Droplets,
  Dumbbell,
  FileSearch,
  ImagePlus,
  NotebookPen,
  Paperclip,
  Plus,
  SendHorizontal,
  Shirt,
  Sparkles,
  TriangleAlert,
  Utensils,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { Segmented } from "@/components/ui/Segmented";
import { cn } from "@/lib/cn";

type TargetFile = { folder: string; slug: string; title: string };

// The dropdown value for "type your own Bedrock model id" — not a real model;
// the typed id is sent to the backend as `bedrock:<id>` (see sendChat).
const CUSTOM_BEDROCK = "__custom_bedrock__";
// Same for "type your own local Ollama model" — sent as `local:<id>`.
const CUSTOM_LOCAL = "__custom_local__";
// The picker's default when no choice is stored yet — local-first.
const DEFAULT_LOCAL_MODEL = "local:qwen3:8b";

export default function KBPage() {
  return (
    <Suspense>
      <KBPageInner />
    </Suspense>
  );
}

function KBPageInner() {
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
  // Free-form Bedrock model id — picking "Custom model id…" in the dropdown
  // reveals an input; whatever's typed is sent as `bedrock:<id>` (any model
  // the AWS account can invoke, not just the curated list).
  const [customBedrockId, setCustomBedrockId] = useState("");
  // Free-form local Ollama model — same deal, sent as `local:<id>` (any
  // model the local daemon has pulled, not just the curated list).
  const [customLocalId, setCustomLocalId] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  // Phone only: one pane at a time (chat | scratchpad). lg+ shows both.
  const [pane, setPane] = useState<"chat" | "scratch">("chat");
  // The chat's subject — first message (or the note being continued), used
  // only as the archive's topic slug. There is deliberately NO thread list:
  // the page stays fresh ("talk yap add and delete"); continuity comes from
  // the KB, closed chats go verbatim into the second-tier transcript archive.
  const [chatSubject, setChatSubject] = useState("");
  // Per-chat "don't keep" toggle — when off, closing archives nothing.
  const [keepTranscript, setKeepTranscript] = useState(true);
  // "Record that" review state — the proposed dated append, edited here
  // before the explicit save (propose→review→Save; nothing writes until then).
  const [recordProposal, setRecordProposal] = useState<RecordThatProposal | null>(null);

  useEffect(() => {
    listChatModels().then((list) => {
      setModels(list);
      let saved: string | null = null;
      let savedCustom: string | null = null;
      let savedCustomLocal: string | null = null;
      try {
        saved = localStorage.getItem("quintacle.chatModel");
        savedCustom = localStorage.getItem("quintacle.chatBedrockCustomId");
        savedCustomLocal = localStorage.getItem("quintacle.chatLocalCustomId");
      } catch {}
      if (savedCustom) setCustomBedrockId(savedCustom);
      if (savedCustomLocal) setCustomLocalId(savedCustomLocal);
      // Local-first chat: with no stored choice, default to the free local
      // 8B — cloud is an escalation the user chooses (per answer, via
      // Escalate ↗, or by picking a cloud model here), never the default.
      const fallback = list.find((m) => m.id === DEFAULT_LOCAL_MODEL)?.id ?? list[0]?.id;
      setModel(saved === CUSTOM_BEDROCK || saved === CUSTOM_LOCAL || list.some((m) => m.id === saved) ? (saved as string) : fallback);
    });
  }, []);

  function pickModel(id: string) {
    setModel(id);
    try {
      localStorage.setItem("quintacle.chatModel", id);
    } catch {}
  }

  function pickCustomBedrockId(id: string) {
    setCustomBedrockId(id);
    try {
      localStorage.setItem("quintacle.chatBedrockCustomId", id);
    } catch {}
  }

  function pickCustomLocalId(id: string) {
    setCustomLocalId(id);
    try {
      localStorage.setItem("quintacle.chatLocalCustomId", id);
    } catch {}
  }

  // Closing a chat (the New button, or continuing on a note) archives the
  // transcript verbatim — one file write, zero model calls — unless the
  // "don't keep" toggle is set, then clears the page. Always fresh.
  async function closeChat() {
    if (chatLog.length > 0) {
      try {
        await archiveTranscript(chatLog, chatSubject || null, keepTranscript);
      } catch {
        // an unreachable backend must not trap the user in a stale chat
      }
    }
    setChatSubject("");
    setKeepTranscript(true);
    setChatLog([]);
    setTarget(null);
    setChatFile(null);
    setRecordProposal(null);
  }

  // The EXPLICIT transcripts deep-search lane (never automatic): uses the
  // typed text as the query, and surfaces the hits (topic, date, snippet) as
  // a deterministic message in the log — so they're in context for the next
  // turn. Zero model calls; the archive is otherwise invisible to chat.
  async function diveIntoTranscripts() {
    const q = chatInput.trim();
    if (!q) return;
    setChatError(null);
    setChatBusy(true);
    try {
      const hits = await searchTranscripts(q);
      const lines = hits.length
        ? hits.slice(0, 8).map((h) => `- **${h.topic}** (${h.date.slice(0, 10)}): ${h.snippet}`)
        : ["- (no archived transcript matches)"];
      const block = `Transcript search for "${q}" — ${hits.length} hit(s):\n\n${lines.join("\n")}`;
      setChatLog([...chatLog, { role: "assistant" as const, content: block, model: "transcripts" }]);
      if (!chatSubject) setChatSubject(q.slice(0, 60));
      setChatInput("");
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    }
    setChatBusy(false);
  }

  // "Record that" — explicit consolidation (§4): the backend distills the
  // conversation into a DATED append for the topic's note and writes NOTHING;
  // the proposal lands in a review panel (scratchpad side) to edit, and only
  // the Save button there actually writes (append-only, history intact).
  async function startRecordThat() {
    if (chatLog.length === 0) return;
    setChatError(null);
    setChatBusy(true);
    try {
      setRecordProposal(await recordThat(chatLog, target?.folder, target?.slug));
      setPane("scratch");
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    }
    setChatBusy(false);
  }

  async function saveRecordProposal() {
    if (!recordProposal) return;
    setBusy(true);
    setStatus("recording...");
    try {
      const res = await saveRecordThat(recordProposal.folder, recordProposal.title, recordProposal.append);
      setStatus(res.appended ? `appended to ${res.folder}/${res.slug}` : `created ${res.folder}/${res.slug}`);
      setRecordProposal(null);
    } catch (e) {
      setStatus(`record failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  async function continueInChatWith(folder: string, slug: string, content: string) {
    const firstLine = content.split("\n")[0] ?? "";
    const title = firstLine.replace(/^#\s*/, "").trim() || slug;
    const body = content.slice(firstLine.length).replace(/^\n+/, "");

    await closeChat();
    setChatSubject(`Re: ${title}`);
    setUseKB(true);
    setTarget({ folder, slug, title });
    setScratchpad(body);
    setSuggestion(null);
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
    if (model === CUSTOM_BEDROCK && !customBedrockId.trim()) {
      setChatError("Enter a Bedrock model id first (or pick a model from the list).");
      return;
    }
    if (model === CUSTOM_LOCAL && !customLocalId.trim()) {
      setChatError("Enter an Ollama model name first (or pick a model from the list).");
      return;
    }
    const effectiveModel =
      model === CUSTOM_BEDROCK ? `bedrock:${customBedrockId.trim()}` : model === CUSTOM_LOCAL ? `local:${customLocalId.trim()}` : model;
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

    // The first message names the chat — only ever used as the archive's
    // topic slug when this chat closes; nothing is saved while it's live.
    if (!chatSubject) setChatSubject(inputForTitle.slice(0, 60) || "Chat");

    let finalLog = next;
    try {
      // A chat continued on a note sends its folder+slug — the backend
      // hydrates that topic's content + graph neighborhood (next-wave §4).
      const { reply } = await chatWithKB(next, useKB, false, target?.folder, effectiveModel, target?.slug);
      // `model` is client-side bookkeeping: it labels the answer and, for a
      // `local:` model, enables the per-answer Escalate ↗ affordance.
      finalLog = [...next, { role: "assistant" as const, content: reply, model: effectiveModel }];
    } catch (e) {
      finalLog = [...next, { role: "assistant" as const, content: `(error: ${e instanceof Error ? e.message : String(e)})` }];
    }
    setChatLog(finalLog);
    setChatBusy(false);
  }

  // Choose-to-escalate with context transfer: re-sends the SAME conversation
  // that produced a local answer (everything before it — the messages array
  // already in state IS the context, nothing is retyped) to a cloud model,
  // appending the cloud answer labeled with its model. The local answer is
  // never deleted — the user compares the two.
  async function escalate(messageIndex: number, cloudModel: string) {
    setChatError(null);
    setChatBusy(true);
    try {
      const context = chatLog.slice(0, messageIndex);
      // Same scope as the original ask — the escalation transfers the SAME context.
      const { reply } = await chatWithKB(context, useKB, false, target?.folder, cloudModel, target?.slug);
      setChatLog([...chatLog, { role: "assistant" as const, content: reply, model: cloudModel }]);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    }
    setChatBusy(false);
  }

  function addToScratchpad(text: string) {
    setScratchpad((prev) => (prev ? `${prev}\n\n${text}` : text));
  }

  const label = "font-mono text-[10px] uppercase tracking-[0.14em] text-muted";
  const suggestionButtons = [
    { onClick: suggestMeal, icon: Utensils, text: "Meal" },
    { onClick: suggestOutfit, icon: Shirt, text: "Outfit" },
    { onClick: suggestGrooming, icon: Droplets, text: "Grooming" },
    { onClick: suggestWorkout, icon: Dumbbell, text: "Workout" },
  ];

  return (
    <div className="space-y-3">
      {/* Phone: one pane at a time */}
      <Segmented
        className="lg:hidden"
        value={pane}
        onChange={setPane}
        options={[
          { value: "chat", label: "Chat" },
          { value: "scratch", label: "Scratchpad" },
        ]}
      />

      <div className="grid gap-4 lg:grid-cols-12 h-[calc(100dvh-14rem)] min-h-[380px] lg:h-[calc(100dvh-5rem)]">
        {/* Chat — the main, GPT/Claude-style panel */}
        <div
          className={cn(
            "flex-col overflow-hidden rounded-xl border border-line bg-surface/80 shadow-panel lg:col-span-8 lg:flex",
            pane === "chat" ? "flex" : "hidden"
          )}
        >
          <div className="shrink-0 space-y-2 border-b border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button
                onClick={() => setUseKB(!useKB)}
                title="Ground answers in your knowledge base"
                className={cn(
                  "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors",
                  useKB ? "border-accent/50 bg-accent/10 text-accent" : "border-line text-muted"
                )}
              >
                <Database size={14} /> Knowledge base {useKB ? "on" : "off"}
              </button>
              <label className="flex items-center gap-2" title="Which model answers — price is $ per 1M tokens in / out (Bedrock bills through AWS). Web search is always on for direct-API models.">
                <span className={label}>Model</span>
                <Select className="w-auto py-1 text-xs" value={model ?? ""} onChange={(e) => pickModel(e.target.value)}>
                  <optgroup label="Direct API">
                    {models
                      .filter((m) => m.provider !== "bedrock" && m.provider !== "local")
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label} ({m.price})
                        </option>
                      ))}
                  </optgroup>
                  <optgroup label="AWS Bedrock">
                    {models
                      .filter((m) => m.provider === "bedrock")
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label}
                        </option>
                      ))}
                    <option value={CUSTOM_BEDROCK}>Custom model id…</option>
                  </optgroup>
                  <optgroup label="Local (Ollama)">
                    {models
                      .filter((m) => m.provider === "local")
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label}
                        </option>
                      ))}
                    <option value={CUSTOM_LOCAL}>Custom model…</option>
                  </optgroup>
                </Select>
                {model === CUSTOM_BEDROCK && (
                  <Input
                    className="w-56 py-1 font-mono text-xs"
                    placeholder="e.g. us.meta.llama3-3-70b-instruct-v1:0"
                    value={customBedrockId}
                    onChange={(e) => pickCustomBedrockId(e.target.value)}
                  />
                )}
                {model === CUSTOM_LOCAL && (
                  <Input
                    className="w-56 py-1 font-mono text-xs"
                    placeholder="e.g. qwen3:14b"
                    value={customLocalId}
                    onChange={(e) => pickCustomLocalId(e.target.value)}
                  />
                )}
              </label>
            </div>
            {/* No thread list, ever — the page stays fresh ("talk yap add and
                delete"). Closing archives the transcript (unless "don't keep"),
                then clears. */}
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => setKeepTranscript(!keepTranscript)}
                title={
                  keepTranscript
                    ? "Closing this chat files its transcript in the archive (outside the KB — only deep search ever reads it)"
                    : "Don't keep — closing this chat archives nothing"
                }
                className={cn(
                  "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors",
                  keepTranscript ? "border-line text-muted" : "border-danger/50 bg-danger/10 text-danger"
                )}
              >
                {keepTranscript ? <Archive size={14} /> : <ArchiveX size={14} />}
                {keepTranscript ? "Keep transcript" : "Don't keep"}
              </button>
              <Button size="sm" onClick={closeChat} disabled={chatBusy} title="Archive this chat and start fresh">
                <Plus size={14} /> New chat
              </Button>
              <Button
                size="sm"
                onClick={startRecordThat}
                disabled={chatBusy || chatLog.length === 0}
                title="Distill this conversation into a dated entry for the topic's note — you review and edit the proposed text before anything is saved"
              >
                <BookmarkPlus size={14} /> Record that
              </Button>
            </div>
            {target && (
              <p className="text-xs text-muted">
                Continuing on <strong className="text-foreground">{target.title}</strong> ({target.folder})
              </p>
            )}
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto p-3">
            {chatLog.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-muted">
                <Sparkles size={26} className="text-accent/60" />
                {useKB ? "Ask about anything already in your knowledge base." : "Just banter — nothing here is saved."}
              </div>
            )}
            <ChatLog
              messages={chatLog}
              busy={chatBusy}
              onAddToScratchpad={addToScratchpad}
              onEscalate={escalate}
              escalateModels={models.filter((m) => m.provider !== "local").map((m) => ({ id: m.id, label: m.label }))}
            />
          </div>

          {chatFile && (
            <div className="flex shrink-0 items-center gap-2 px-3 pb-2 text-xs">
              <span className="flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-1 text-muted">
                <Paperclip size={12} /> {chatFile.name}
                <button onClick={() => setChatFile(null)} aria-label="Remove attachment" className="hover:text-foreground">
                  <X size={12} />
                </button>
              </span>
            </div>
          )}

          {chatError && (
            <div className="flex shrink-0 items-center gap-1.5 px-3 pb-2 text-xs text-danger">
              <TriangleAlert size={13} /> {chatError}
            </div>
          )}
          <div className="flex shrink-0 gap-2 border-t border-line p-3">
            <label
              className="flex cursor-pointer items-center rounded-lg border border-line px-2.5 text-muted transition-colors hover:border-accent/50 hover:text-accent"
              title="Attach a photo or PDF"
            >
              <Paperclip size={18} />
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
            <Input
              className="flex-1"
              placeholder="Say something..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendChat()}
            />
            <button
              onClick={diveIntoTranscripts}
              disabled={chatBusy || !chatInput.trim()}
              title="Search the transcript archive for the typed text — hits land in the chat as context for your next question. Transcripts are never read automatically."
              className="flex items-center rounded-lg border border-line px-2.5 text-muted transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              <FileSearch size={18} />
            </button>
            <Button
              variant="primary"
              onClick={sendChat}
              disabled={chatBusy || (!chatInput.trim() && !chatFile)}
              aria-label="Send"
            >
              <SendHorizontal size={18} />
            </Button>
          </div>
        </div>

        {/* Scratchpad — beside the chat on desktop, its own pane on phone */}
        <div
          className={cn(
            "flex-col overflow-y-auto rounded-xl border border-line bg-surface/80 p-3 shadow-panel lg:col-span-4 lg:flex",
            pane === "scratch" ? "flex" : "hidden"
          )}
        >
          <h2 className={cn(label, "mb-2 flex items-center gap-2 text-accent")}>
            <NotebookPen size={14} /> Scratchpad
          </h2>
          {target && (
            <div className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-line bg-surface-2 px-2 py-1 text-xs">
              <span>
                Updating <strong>{target.title}</strong>
              </span>
              <button onClick={stopTargeting} className="shrink-0 text-accent underline-offset-2 hover:underline">
                new entry instead
              </button>
            </div>
          )}
          <Textarea
            className="min-h-40 flex-1"
            rows={10}
            placeholder="Write out whatever you're thinking as you go..."
            value={scratchpad}
            onChange={(e) => setScratchpad(e.target.value)}
          />
          {generatedImagePreviewUrl && (
            <div className="mt-2 space-y-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={generatedImagePreviewUrl} alt="" className="max-w-full rounded-lg border border-line" />
              <button onClick={clearGeneratedImage} className="flex items-center gap-1 text-xs text-muted hover:text-foreground">
                <X size={12} /> remove generated image
              </button>
            </div>
          )}
          <div className="mt-2 space-y-2">
            <Button variant="primary" className="w-full" onClick={sortWithAI} disabled={busy || !scratchpad.trim()}>
              <Sparkles size={16} /> {target ? "Update with AI" : "Sort with AI"}
            </Button>
            <div className="grid grid-cols-3 gap-2">
              {suggestionButtons.map((b) => (
                <Button key={b.text} size="sm" onClick={b.onClick} disabled={busy || !scratchpad.trim()} title={`Suggest ${b.text.toLowerCase()} from the scratchpad`}>
                  <b.icon size={14} /> {b.text}
                </Button>
              ))}
              <Button
                size="sm"
                className="col-span-2"
                onClick={generateImageFromPrompt}
                disabled={busy || !scratchpad.trim()}
                title="Uses the scratchpad text as the image prompt"
              >
                <ImagePlus size={14} /> Generate image
              </Button>
            </div>
          </div>

          {mealSuggestion && (
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <MealCompositionEditor value={mealSuggestion} onChange={setMealSuggestion} />
              <Button variant="primary" className="w-full" onClick={pushMeal} disabled={busy}>
                Save as meal preset
              </Button>
            </div>
          )}

          {outfitSuggestion && (
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <OutfitEditor value={outfitSuggestion} onChange={setOutfitSuggestion} />
              <Button variant="primary" className="w-full" onClick={pushOutfit} disabled={busy}>
                Save as outfit
              </Button>
            </div>
          )}

          {groomingSuggestion && (
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <GroomingRoutineEditor value={groomingSuggestion} onChange={setGroomingSuggestion} />
              <Button variant="primary" className="w-full" onClick={pushGrooming} disabled={busy}>
                Save as grooming routine
              </Button>
            </div>
          )}

          {workoutSuggestion && (
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <Input
                placeholder="routine name"
                value={workoutSuggestion.name}
                onChange={(e) => setWorkoutSuggestion({ ...workoutSuggestion, name: e.target.value })}
              />
              {workoutSuggestion.exercises.map((ex, ei) => (
                <div key={ei} className="flex items-center gap-1.5">
                  <Input
                    className="flex-1 py-1 text-xs"
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
                    aria-label="Remove exercise"
                    className="p-1 text-muted hover:text-danger"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => setWorkoutSuggestion({ ...workoutSuggestion, exercises: [...workoutSuggestion.exercises, ""] })}
                className="flex items-center gap-1 text-xs text-accent hover:underline"
              >
                <Plus size={12} /> add exercise
              </button>
              <Button variant="primary" className="w-full" onClick={pushWorkout} disabled={busy}>
                Save as workout routine
              </Button>
            </div>
          )}

          {recordProposal && (
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <p className={cn(label, "flex items-center gap-2 text-accent")}>
                <BookmarkPlus size={14} /> Record from chat — {recordProposal.date}
              </p>
              <p className="text-xs text-muted">
                A dated entry appended to the note below — existing content is never rewritten.
                {!recordProposal.slug && " No topic was scoped: pick/confirm the folder and note title."}
              </p>
              <label className="block">
                <span className={label}>Folder</span>
                <Input
                  className="mt-1"
                  value={recordProposal.folder}
                  onChange={(e) => setRecordProposal({ ...recordProposal, folder: e.target.value })}
                />
              </label>
              <label className="block">
                <span className={label}>Note</span>
                <Input
                  className="mt-1"
                  value={recordProposal.title}
                  onChange={(e) => setRecordProposal({ ...recordProposal, title: e.target.value })}
                />
              </label>
              <label className="block">
                <span className={label}>Dated entry</span>
                <Textarea
                  className="mt-1"
                  rows={8}
                  value={recordProposal.append}
                  onChange={(e) => setRecordProposal({ ...recordProposal, append: e.target.value })}
                />
              </label>
              <div className="flex gap-2">
                <Button variant="primary" className="flex-1" onClick={saveRecordProposal} disabled={busy}>
                  Append to note
                </Button>
                <Button onClick={() => setRecordProposal(null)} disabled={busy}>
                  Discard
                </Button>
              </div>
            </div>
          )}

          {suggestion && (
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <label className="block">
                <span className={label}>Folder</span>
                <Input className="mt-1" value={suggestion.folder} onChange={(e) => setSuggestion({ ...suggestion, folder: e.target.value })} />
              </label>
              <label className="block">
                <span className={label}>Title</span>
                <Input className="mt-1" value={suggestion.title} onChange={(e) => setSuggestion({ ...suggestion, title: e.target.value })} />
              </label>
              <label className="block">
                <span className={label}>Content</span>
                <Textarea
                  className="mt-1"
                  rows={8}
                  value={suggestion.content}
                  onChange={(e) => setSuggestion({ ...suggestion, content: e.target.value })}
                />
              </label>
              <Button variant="primary" className="w-full" onClick={push} disabled={busy}>
                {target ? "Push update" : "Push to Knowledge Base"}
              </Button>
            </div>
          )}

          {status && <p className="mt-2 text-sm text-muted">{status}</p>}
        </div>
      </div>
    </div>
  );
}
