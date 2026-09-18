"use client";

import { useEffect, useState } from "react";
import EntryCard from "@/components/EntryCard";
import ScribblePad from "@/components/ScribblePad";
import { ExerciseSet, listExerciseNames, listMeals, Meal, ParsedEntry, proposeDrop, saveJournal } from "@/lib/api";
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

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

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
  const [date, setDate] = useState(today());
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
    for (const entry of entries) {
      const assets = ASSET_TYPES.has(entry.type) && file ? [file, ...extraPhotos] : [];
      await commitEntry(date, entry, assets);
    }
    setStatus(`saved ${entries.length} entr${entries.length === 1 ? "y" : "ies"}`);
    setEntries([]);
    setText("");
    setJournalTouched(false);
    onFileChosen(null);
    setBusy(false);
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

      {previewUrl && extraPhotos.length > 0 && (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {extraPreviewUrls.map((url, i) => (
            <div key={i} className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url} alt="" className="h-28 w-full rounded-lg border border-line object-cover" />
              <button
                onClick={() => removeExtraPhoto(i)}
                aria-label="Remove photo"
                className="absolute right-1 top-1 rounded-full bg-black/70 p-1 text-white hover:bg-danger"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {previewUrl && (
        <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-accent hover:underline">
          <ImagePlus size={14} /> add another photo (back / label / another angle / another page) — as many as you want
          <input
            type="file"
            accept="image/*"
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

      {entries.length === 0 && !status && !text.trim() && !file && (
        <EmptyState icon={Inbox}>Nothing queued. Type, drop a file, or add an entry by hand — nothing is saved until you review it.</EmptyState>
      )}

      {status && <p className="text-sm text-muted">{status}</p>}
    </div>
  );
}
