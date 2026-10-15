"use client";

import { useEffect, useState } from "react";
import EntryCard from "@/components/EntryCard";
import ScribblePad from "@/components/ScribblePad";
import {
  addKBEntryAsset,
  ExerciseSet,
  listExerciseNames,
  listMeals,
  listPeople,
  Meal,
  ParsedEntry,
  PerceptionSummary,
  proposeDrop,
  pushKBEntry,
  saveJournal,
  sortKBEntry,
  tagUnknownFace,
} from "@/lib/api";
import Link from "next/link";
import {
  Activity,
  Apple,
  Armchair,
  BookOpen,
  Building2,
  Camera,
  ChefHat,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  CreditCard,
  Droplets,
  Dumbbell,
  FileText,
  ImagePlus,
  Inbox,
  ListChecks,
  ListOrdered,
  MapPin,
  Pill,
  PenLine,
  Paperclip,
  Plus,
  Scale,
  Shirt,
  Sparkles,
  Tag,
  TrendingUp,
  Upload,
  User,
  Utensils,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { EmptyState, PageHeader, Panel } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";
import { BLANK, commitEntry } from "@/lib/entries";
import { todayIso } from "@/lib/date";

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];
const VIDEO_EXT = ["mp4", "webm", "mov", "m4v"];

function extFor(file: File): string {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

const MANUAL: { type: ParsedEntry["type"]; label: string; icon: LucideIcon }[] = [
  { type: "activity", label: "Activity", icon: Activity },
  { type: "food", label: "Food", icon: Utensils },
  { type: "exercise", label: "Exercise", icon: Dumbbell },
  { type: "substance", label: "Substance", icon: Pill },
  { type: "todo", label: "Todo", icon: ListChecks },
  { type: "body_stat", label: "Weight", icon: Scale },
  { type: "ingredient_preset", label: "Ingredient", icon: Apple },
  { type: "meal_composition", label: "Composed meal", icon: ChefHat },
  { type: "workout_routine", label: "Routine", icon: ClipboardList },
  { type: "wardrobe_item", label: "Wardrobe item", icon: Shirt },
  { type: "outfit_composition", label: "Outfit", icon: Tag },
  { type: "outfit_photo", label: "Outfit photo", icon: Camera },
  { type: "grooming_item", label: "Product", icon: Droplets },
  { type: "grooming_routine_composition", label: "Grooming routine", icon: ListOrdered },
  { type: "document_entry", label: "Document", icon: FileText },
  { type: "home_item", label: "Home item", icon: Armchair },
  { type: "residence_entry", label: "Residence", icon: Building2 },
  { type: "experience_entry", label: "Experience", icon: MapPin },
  { type: "person_entry", label: "Person", icon: User },
  { type: "credit_card_entry", label: "Credit card", icon: CreditCard },
  { type: "investment_entry", label: "Investment", icon: TrendingUp },
];

// Long text is almost always a day's narrative worth keeping verbatim.
const JOURNAL_AUTO_CHARS = 200;

// The one general drop: quick structured things — a single todo, meal,
// expense, item, document, experience — plus optional photo/PDF/DOCX. A
// recognized "keyword: ..." prefix (todo/food/exercise/substance/activity/
// weight/finance/note/label/...) routes deterministically with no AI call;
// an unprefixed photo gets one cheap vision classification; anything else
// falls through to full AI text classification. Nothing is written until
// you review and Save below. Drop also covers everything the Journal page
// does: a day's narrative is parsed with the same parse_journal_dump, "yesterday"
// resolves against the date picked here, and "save to journal" keeps the raw
// text verbatim as that day's journal (appended, never overwritten).
export default function DropPage() {
  const [date, setDate] = useState(todayIso());
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  // Beyond the primary `file` — as many additional photos as you want (a
  // multi-page note, several angles of the same thing); every asset-carrying
  // entry type keeps all of them (see commitEntry).
  const [extraPhotos, setExtraPhotos] = useState<File[]>([]);
  const [extraPreviewUrls, setExtraPreviewUrls] = useState<string[]>([]);
  const [entries, setEntries] = useState<ParsedEntry[]>([]);
  const [meals, setMeals] = useState<Meal[]>([]);
  const [exerciseNames, setExerciseNames] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [keepAsIs, setKeepAsIs] = useState(false);
  const [showScribble, setShowScribble] = useState(false);
  const [showManual, setShowManual] = useState(false);
  // Journal: also keep the raw text verbatim as this day's journal entry.
  // Auto-ticks for long text until the user decides either way.
  const [saveToJournal, setSaveToJournal] = useState(false);
  const [journalTouched, setJournalTouched] = useState(false);

  // After a single-note drop commits, keep the entry open for more rounds —
  // a lecture, a live-evolving trip record — instead of forcing a fresh drop
  // (and a fresh AI classification) for every new sentence or photo. Folds
  // more text in via the same merge-update /kb/sort already uses for Browse's
  // "add to this note", and attaches more files via the same endpoint Browse
  // uses to add a photo to an existing entry after the fact.
  const [activeSession, setActiveSession] = useState<{ folder: string; slug: string; title: string } | null>(null);
  const [sessionText, setSessionText] = useState("");
  const [sessionFile, setSessionFile] = useState<File | null>(null);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [sessionStatus, setSessionStatus] = useState<string | null>(null);

  // The "who is this?" tag flow — a saved photo's unrecognized faces come
  // back on the commit response; each one can be tagged (an existing person
  // or a new name) or dismissed. Tagging is never required for the save —
  // the photo is already committed by the time this panel appears.
  type PendingFace = {
    embeddingId: string;
    suggestedName: string | null;
    photo: { folder: string; slug: string };
    photoTitle: string;
    pick: string; // dropdown choice ("" = type a new name)
    newName: string;
  };
  const [pendingFaces, setPendingFaces] = useState<PendingFace[]>([]);
  const [peopleNames, setPeopleNames] = useState<string[]>([]);
  const [faceBusy, setFaceBusy] = useState(false);
  const [faceStatus, setFaceStatus] = useState<string | null>(null);

  useEffect(() => {
    if (pendingFaces.length > 0) listPeople().then((ps) => setPeopleNames(ps.map((p) => p.name)));
  }, [pendingFaces.length]);

  useEffect(() => {
    listMeals().then(setMeals);
    listExerciseNames().then(setExerciseNames);
  }, []);

  useEffect(() => {
    if (!journalTouched) setSaveToJournal(text.trim().length >= JOURNAL_AUTO_CHARS);
  }, [text, journalTouched]);

  useEffect(() => {
    const urls = extraPhotos.map((f) => URL.createObjectURL(f));
    setExtraPreviewUrls(urls);
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, [extraPhotos]);

  function onFileChosen(f: File | null) {
    setFile(f);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(f && IMAGE_EXT.includes(extFor(f)) ? URL.createObjectURL(f) : null);
    if (videoPreviewUrl) URL.revokeObjectURL(videoPreviewUrl);
    setVideoPreviewUrl(f && VIDEO_EXT.includes(extFor(f)) ? URL.createObjectURL(f) : null);
    if (!f) setExtraPhotos([]);
  }

  function addExtraPhoto(f: File | null) {
    if (f) setExtraPhotos((prev) => [...prev, f]);
  }

  function removeExtraPhoto(i: number) {
    setExtraPhotos((prev) => prev.filter((_, idx) => idx !== i));
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFileChosen(dropped);
  }

  async function sortWithAI() {
    if (!text.trim() && !file) return;
    setBusy(true);
    setStatus("routing...");
    try {
      // Classification only ever reads at most two images together (the
      // vision call needs just enough to recognize what this is, not every
      // page) — extraPhotos beyond the first are still attached in full at
      // save time below, they just aren't part of what AI looks at here.
      const { entries: proposed } = await proposeDrop(text, file, keepAsIs, extraPhotos[0] ?? null, date);
      setEntries((prev) => [...prev, ...proposed]);
      setStatus(`${proposed.length} entr${proposed.length === 1 ? "y" : "ies"} proposed — review below`);
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  // The journal store appends a timestamped block on every save (it never
  // overwrites), so just send the new text — re-sending existing content
  // would duplicate it.
  async function appendToJournal() {
    await saveJournal(date, text.trim());
  }

  async function saveJournalOnly() {
    if (!text.trim()) return;
    setBusy(true);
    setStatus("saving to journal...");
    try {
      await appendToJournal();
      setStatus(`saved to your ${date} journal`);
      setText("");
      setJournalTouched(false);
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  function addManual(type: ParsedEntry["type"]) {
    setEntries((prev) => [...prev, { ...BLANK[type] }]);
  }

  function updateEntry(i: number, patch: Partial<ParsedEntry>) {
    setEntries((prev) => prev.map((e, idx) => (idx === i ? ({ ...e, ...patch } as ParsedEntry) : e)));
  }

  function removeEntry(i: number) {
    setEntries((prev) => prev.filter((_, idx) => idx !== i));
  }

  function updateSet(entryIndex: number, setIndex: number, patch: Partial<ExerciseSet>) {
    setEntries((prev) =>
      prev.map((e, idx) => {
        if (idx !== entryIndex || e.type !== "exercise") return e;
        return { ...e, sets: e.sets.map((s, si) => (si === setIndex ? { ...s, ...patch } : s)) };
      })
    );
  }

  function addSet(entryIndex: number) {
    setEntries((prev) =>
      prev.map((e, idx) =>
        idx === entryIndex && e.type === "exercise"
          ? { ...e, sets: [...e.sets, { reps: null, weight: null, weight_unit: "lb", duration_min: null, distance: null, distance_unit: "mi", calories_burned: null }] }
          : e
      )
    );
  }

  function removeSet(entryIndex: number, setIndex: number) {
    setEntries((prev) =>
      prev.map((e, idx) =>
        idx === entryIndex && e.type === "exercise" ? { ...e, sets: e.sets.filter((_, si) => si !== setIndex) } : e
      )
    );
  }

  async function saveAll() {
    setBusy(true);
    setStatus("saving...");
    // The dropped file attaches to kb_entry/document_entry/wardrobe_item/
    // grooming_item/home_item proposals — those keep the photo (what does
    // this thing actually look like stays useful). ingredient_preset/finance
    // extract structured data and don't need the file itself. A drop only
    // ever produces one entry when a file was involved, so this attaches to
    // the right one unambiguously.
    if (saveToJournal && text.trim()) await appendToJournal();
    const ASSET_TYPES = new Set(["kb_entry", "document_entry", "wardrobe_item", "grooming_item", "home_item", "outfit_photo"]);
    // A single kb_entry drop is the common "one note, maybe more to add
    // later" case — capture where it landed so the keep-adding session below
    // can target it. Multiple entries (a journal dump exploding into several
    // things) don't have one obvious entry to keep extending, so no session.
    const singleNote = entries.length === 1 && entries[0].type === "kb_entry" ? entries[0] : null;
    let newSession: typeof activeSession = null;
    const newFaces: PendingFace[] = [];
    for (const entry of entries) {
      const assets = ASSET_TYPES.has(entry.type) && file ? [file, ...extraPhotos] : [];
      const result = await commitEntry(date, entry, assets);
      if (singleNote && result && typeof result === "object" && "slug" in result) {
        const r = result as { folder: string; slug: string };
        newSession = { folder: r.folder, slug: r.slug, title: singleNote.title };
      }
      // A committed photo reports faces it couldn't match — queue them for
      // the optional tag flow below (never blocks the save, which is done).
      if (result && typeof result === "object" && "perception" in result) {
        const r = result as { folder: string; slug: string; perception: PerceptionSummary };
        for (const f of r.perception?.unknown_faces ?? []) {
          newFaces.push({
            embeddingId: f.embedding_id,
            suggestedName: f.suggested_name ?? null,
            photo: { folder: r.folder, slug: r.slug },
            photoTitle: entry.type === "kb_entry" ? entry.title : r.slug,
            pick: f.suggested_name ?? "",
            newName: "",
          });
        }
      }
    }
    setStatus(`saved ${entries.length} entr${entries.length === 1 ? "y" : "ies"}`);
    setEntries([]);
    setText("");
    setJournalTouched(false);
    onFileChosen(null);
    setActiveSession(newSession);
    setSessionStatus(null);
    if (newFaces.length > 0) {
      setPendingFaces((prev) => [...prev, ...newFaces]);
      setFaceStatus(null);
    }
    setBusy(false);
  }

  function updateFace(i: number, patch: Partial<PendingFace>) {
    setPendingFaces((prev) => prev.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  }

  function dismissFace(i: number) {
    setPendingFaces((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function tagFace(i: number) {
    const face = pendingFaces[i];
    const name = (face.pick || face.newName).trim();
    if (!name) return;
    setFaceBusy(true);
    setFaceStatus("tagging...");
    try {
      const result = await tagUnknownFace(face.embeddingId, name, face.photo);
      dismissFace(i);
      setFaceStatus(
        `tagged ${result.person_name}${result.created_person ? " (new person)" : ""}${
          result.journal_updated ? " — journal updated" : ""
        }`
      );
      if (result.created_person) setPeopleNames((prev) => [...prev, result.person_name]);
    } catch (e) {
      setFaceStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setFaceBusy(false);
  }

  async function foldIntoSession() {
    if (!activeSession || !sessionText.trim()) return;
    setSessionBusy(true);
    setSessionStatus("adding...");
    try {
      const suggestion = await sortKBEntry(sessionText.trim(), { folder: activeSession.folder, slug: activeSession.slug });
      await pushKBEntry(suggestion);
      setSessionText("");
      setSessionStatus("added");
    } catch (e) {
      setSessionStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setSessionBusy(false);
  }

  async function attachToSession() {
    if (!activeSession || !sessionFile) return;
    setSessionBusy(true);
    setSessionStatus("attaching...");
    try {
      await addKBEntryAsset(activeSession.folder, activeSession.slug, sessionFile);
      setSessionFile(null);
      setSessionStatus("attached");
    } catch (e) {
      setSessionStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setSessionBusy(false);
  }

  function endSession() {
    setActiveSession(null);
    setSessionText("");
    setSessionFile(null);
    setSessionStatus(null);
  }

  const mono = "font-mono text-[10px] uppercase tracking-[0.14em] text-muted";

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageHeader
        title="Drop"
        icon={Inbox}
        subtitle='Everything goes in here — todos, food, workouts, expenses, notes, a full day, photos, PDFs. A prefix like "food:" or "todo:" routes instantly with no AI.'
      />

      <Panel title="What happened">
        <div className="space-y-3">
          <Textarea
            rows={5}
            placeholder={'Type anything — "food: had a burrito", "expense: $12 at chipotle", "note: monitor arm height is 47cm", or write out your whole day...'}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <label className="flex items-center gap-2">
              <span className={mono}>Date</span>
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-auto py-1 text-xs" />
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={saveToJournal}
                onChange={(e) => {
                  setJournalTouched(true);
                  setSaveToJournal(e.target.checked);
                }}
                className="accent-[var(--color-accent)]"
              />
              Also save this text to my journal for {date}
            </label>
            <Link href="/journal" className="text-xs text-accent hover:underline">
              open journal →
            </Link>
          </div>
          <p className="text-xs text-muted">
            Dates like &quot;yesterday&quot; resolve against the date above. Todos use their own due date.
          </p>
        </div>
      </Panel>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="space-y-3 rounded-xl border-2 border-dashed border-line-strong bg-accent/[0.03] p-5 text-center"
      >
        {previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={previewUrl} alt="" className="mx-auto max-h-64 rounded-lg" />
        ) : videoPreviewUrl ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <video src={videoPreviewUrl} controls className="mx-auto max-h-64 rounded-lg" />
        ) : file ? (
          <p className="flex items-center justify-center gap-2 text-sm">
            <FileText size={16} className="text-accent" /> {file.name}
          </p>
        ) : (
          <div className="flex flex-col items-center gap-2 text-sm text-muted">
            <Upload size={26} className="text-accent/70" />
            Drag a photo, video, PDF or DOCX here — or choose one (optional)
          </div>
        )}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-line-strong px-4 py-2 text-sm transition-colors hover:border-accent/60 hover:bg-accent/10">
            <Upload size={15} /> Choose file
            <input
              type="file"
              accept="image/*,video/*,.pdf,.docx,.stl"
              capture="environment"
              onChange={(e) => onFileChosen(e.target.files?.[0] ?? null)}
              className="hidden"
            />
          </label>
          <Button onClick={() => setShowScribble((v) => !v)}>
            <PenLine size={15} /> {showScribble ? "Hide scribble pad" : "Scribble"}
          </Button>
          {file && (
            <Button variant="ghost" onClick={() => onFileChosen(null)}>
              <X size={15} /> Clear
            </Button>
          )}
        </div>
      </div>

      {file && extraPhotos.length > 0 && (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {extraPhotos.map((f, i) =>
            IMAGE_EXT.includes(extFor(f)) ? (
              <div key={i} className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={extraPreviewUrls[i]} alt="" className="h-28 w-full rounded-lg border border-line object-cover" />
                <button
                  onClick={() => removeExtraPhoto(i)}
                  aria-label="Remove attachment"
                  className="absolute right-1 top-1 rounded-full bg-black/70 p-1 text-white hover:bg-danger"
                >
                  <X size={12} />
                </button>
              </div>
            ) : (
              <div key={i} className="relative flex h-28 flex-col items-center justify-center gap-1 rounded-lg border border-line p-2 text-center">
                <Paperclip size={18} className="text-accent" />
                <span className="line-clamp-2 break-all text-[11px] text-muted">{f.name}</span>
                <button
                  onClick={() => removeExtraPhoto(i)}
                  aria-label="Remove attachment"
                  className="absolute right-1 top-1 rounded-full bg-black/70 p-1 text-white hover:bg-danger"
                >
                  <X size={12} />
                </button>
              </div>
            )
          )}
        </div>
      )}

      {file && (
        <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-accent hover:underline">
          <Paperclip size={14} /> add another attachment (photo, video, PDF, DOCX — a ticket, a QR code, another page) — as many as you want
          <input
            type="file"
            accept="image/*,video/*,.pdf,.docx,.stl"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              addExtraPhoto(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
        </label>
      )}

      {showScribble && (
        <ScribblePad
          onUse={(f) => {
            onFileChosen(f);
            setShowScribble(false);
          }}
        />
      )}

      <label className="flex cursor-pointer items-center gap-2 text-sm text-muted">
        <input type="checkbox" checked={keepAsIs} onChange={(e) => setKeepAsIs(e.target.checked)} className="accent-[var(--color-accent)]" />
        Already-finished document — don&apos;t let AI rewrite it, just suggest where it goes
      </label>

      <div className="flex flex-wrap gap-2">
        <Button variant="primary" className="flex-1 sm:flex-none" onClick={sortWithAI} disabled={busy || (!text.trim() && !file)}>
          <Sparkles size={16} /> Sort
        </Button>
        {saveToJournal && text.trim() && (
          <Button className="flex-1 sm:flex-none" onClick={saveJournalOnly} disabled={busy} title="Keep the text as this day's journal without parsing it into entries">
            <BookOpen size={16} /> Save to journal only
          </Button>
        )}
      </div>

      <div>
        <button
          onClick={() => setShowManual((v) => !v)}
          className="flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-accent"
        >
          {showManual ? <ChevronUp size={16} /> : <ChevronDown size={16} />} or add manually
        </button>
        {showManual && (
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
            {MANUAL.map((m) => (
              <button
                key={m.type}
                onClick={() => addManual(m.type)}
                className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-left text-xs text-muted transition-colors hover:border-accent/50 hover:bg-accent/10 hover:text-foreground"
              >
                <m.icon size={15} className="shrink-0 text-accent" />
                {m.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {entries.length > 0 && (
        <Panel title="Review before saving" className={cn("border-line-strong")}>
          <div className="space-y-3">
            {entries.map((entry, i) => (
              <EntryCard
                key={i}
                entry={entry}
                index={i}
                meals={meals}
                exerciseNames={exerciseNames}
                onUpdate={updateEntry}
                onRemove={removeEntry}
                onUpdateSet={updateSet}
                onAddSet={addSet}
                onRemoveSet={removeSet}
              />
            ))}
            <Button variant="primary" className="w-full" onClick={saveAll} disabled={busy}>
              Save {entries.length} entr{entries.length === 1 ? "y" : "ies"}
              {saveToJournal && text.trim() ? " + journal" : ""}
            </Button>
          </div>
        </Panel>
      )}

      {entries.length === 0 && !status && !text.trim() && !file && !activeSession && (
        <EmptyState icon={Inbox}>Nothing queued. Type, drop a file, or add an entry by hand — nothing is saved until you review it.</EmptyState>
      )}

      {status && <p className="text-sm text-muted">{status}</p>}

      {pendingFaces.length > 0 && (
        <Panel title={`Unknown faces (${pendingFaces.length})`} className={cn("border-accent/40")}>
          <div className="space-y-3">
            <p className="text-xs text-muted">
              Someone in a saved photo wasn&apos;t recognized. Tell me who they are — pick a person or type a new name —
              and they get connected to the photo and that day&apos;s journal. Or dismiss; the photo is already saved.
            </p>
            {pendingFaces.map((face, i) => (
              <div key={`${face.embeddingId}-${i}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-2">
                <User size={15} className="shrink-0 text-accent" />
                <span className="text-xs text-muted">
                  in &quot;{face.photoTitle}&quot;
                  {face.suggestedName ? ` — maybe ${face.suggestedName}?` : ""}
                </span>
                <select
                  value={face.pick}
                  onChange={(e) => updateFace(i, { pick: e.target.value })}
                  className="rounded-lg border border-line bg-transparent px-2 py-1 text-sm"
                >
                  <option value="">new person…</option>
                  {peopleNames.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
                {!face.pick && (
                  <Input
                    placeholder="their name"
                    value={face.newName}
                    onChange={(e) => updateFace(i, { newName: e.target.value })}
                    className="w-36 py-1 text-sm"
                  />
                )}
                <Button variant="primary" onClick={() => tagFace(i)} disabled={faceBusy || !(face.pick || face.newName.trim())}>
                  Tag
                </Button>
                <Button variant="ghost" onClick={() => dismissFace(i)} aria-label="Dismiss unknown face">
                  <X size={14} />
                </Button>
              </div>
            ))}
            {faceStatus && <p className="text-xs text-muted">{faceStatus}</p>}
          </div>
        </Panel>
      )}

      {activeSession && (
        <Panel title={`Still going — "${activeSession.title}"`} className={cn("border-accent/40")}>
          <div className="space-y-3">
            <p className="text-xs text-muted">
              A lecture, a live trip record, anything you keep adding to — fold in more text or attach more photos
              without starting a new drop. Each round saves straight into this entry.
            </p>
            <Textarea
              rows={3}
              placeholder="More notes to fold into this entry..."
              value={sessionText}
              onChange={(e) => setSessionText(e.target.value)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={foldIntoSession} disabled={sessionBusy || !sessionText.trim()}>
                <Plus size={15} /> Add to note
              </Button>
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-line-strong px-4 py-2 text-sm transition-colors hover:border-accent/60 hover:bg-accent/10">
                <Paperclip size={15} /> {sessionFile ? sessionFile.name : "Choose attachment"}
                <input
                  type="file"
                  accept="image/*,video/*,.pdf,.docx,.stl"
                  capture="environment"
                  className="hidden"
                  onChange={(e) => setSessionFile(e.target.files?.[0] ?? null)}
                />
              </label>
              {sessionFile && (
                <Button onClick={attachToSession} disabled={sessionBusy}>
                  <ImagePlus size={15} /> Attach
                </Button>
              )}
              <Button variant="ghost" onClick={endSession}>
                Done
              </Button>
            </div>
            {sessionStatus && <p className="text-xs text-muted">{sessionStatus}</p>}
          </div>
        </Panel>
      )}
    </div>
  );
}
