"use client";

import { useEffect, useState } from "react";
import EntryCard from "@/components/EntryCard";
import ScribblePad from "@/components/ScribblePad";
import { ExerciseSet, listExerciseNames, listMeals, Meal, ParsedEntry, proposeDrop } from "@/lib/api";
import { BLANK, commitEntry } from "@/lib/entries";

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];
const VIDEO_EXT = ["mp4", "webm", "mov", "m4v"];

function extFor(file: File): string {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// The one general drop: quick structured things — a single todo, meal,
// expense, item, document, experience — plus optional photo/PDF/DOCX. A
// recognized "keyword: ..." prefix (todo/food/exercise/substance/activity/
// weight/finance/note/label/...) routes deterministically with no AI call;
// an unprefixed photo gets one cheap vision classification; anything else
// falls through to full AI text classification. Nothing is written until
// you review and Save below. Distinct from Journal (the nightly narrative
// dump) — Drop never touches the journal.
export default function DropPage() {
  const [date, setDate] = useState(today());
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  // Beyond the primary `file` — as many additional photos as you want (a
  // multi-page note, several angles of the same thing). Only kb_entry
  // actually keeps all of them; document/wardrobe/grooming/home items still
  // cap at 2 total (see commitEntry's comment) — extras beyond that are
  // silently unused for those types.
  const [extraPhotos, setExtraPhotos] = useState<File[]>([]);
  const [extraPreviewUrls, setExtraPreviewUrls] = useState<string[]>([]);
  const [entries, setEntries] = useState<ParsedEntry[]>([]);
  const [meals, setMeals] = useState<Meal[]>([]);
  const [exerciseNames, setExerciseNames] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [keepAsIs, setKeepAsIs] = useState(false);
  const [showScribble, setShowScribble] = useState(false);

  useEffect(() => {
    listMeals().then(setMeals);
    listExerciseNames().then(setExerciseNames);
  }, []);

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
      const { entries: proposed } = await proposeDrop(text, file, keepAsIs, extraPhotos[0] ?? null);
      setEntries((prev) => [...prev, ...proposed]);
      setStatus(`${proposed.length} entr${proposed.length === 1 ? "y" : "ies"} proposed — review below`);
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
    const ASSET_TYPES = new Set(["kb_entry", "document_entry", "wardrobe_item", "grooming_item", "home_item", "outfit_photo"]);
    for (const entry of entries) {
      const assets = ASSET_TYPES.has(entry.type) && file ? [file, ...extraPhotos] : [];
      await commitEntry(date, entry, assets);
    }
    setStatus(`saved ${entries.length} entr${entries.length === 1 ? "y" : "ies"}`);
    setEntries([]);
    setText("");
    onFileChosen(null);
    setBusy(false);
  }

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Drop</h1>
      <p className="text-sm opacity-60 -mt-2">
        Everything goes in here — todos, food, workouts, expenses, notes, a full dump of your day, photos, PDFs, DOCX. A
        recognized prefix ("food:", "todo:", "expense:", "note:"...) routes instantly with no AI; an unprefixed photo gets
        classified; anything else falls back to full AI classification.
      </p>

      <label className="block text-sm">
        Date (for logged entries — todos use their own due date)
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="block border rounded px-2 py-1 mt-1" />
      </label>

      <textarea
        className="w-full border rounded p-2 text-sm"
        rows={4}
        placeholder={'Type anything — "food: had a burrito", "expense: $12 at chipotle", "note: my monitor arm height is 47cm", or just describe what\'s being dropped... (for the day\'s full narrative, use Journal instead)'}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <div onDragOver={(e) => e.preventDefault()} onDrop={onDrop} className="border-2 border-dashed rounded p-6 text-center space-y-3">
        {previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={previewUrl} alt="" className="max-h-64 mx-auto rounded" />
        ) : videoPreviewUrl ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <video src={videoPreviewUrl} controls className="max-h-64 mx-auto rounded" />
        ) : file ? (
          <p className="text-sm">📄 {file.name}</p>
        ) : (
          <p className="text-sm opacity-60">Drag a photo/video/PDF/DOCX here, or choose one below (optional)</p>
        )}
        <input
          type="file"
          accept="image/*,video/*,.pdf,.docx,.stl"
          capture="environment"
          onChange={(e) => onFileChosen(e.target.files?.[0] ?? null)}
          className="text-sm mx-auto"
        />
        <button onClick={() => setShowScribble((s) => !s)} className="text-xs underline opacity-70 hover:opacity-100">
          {showScribble ? "hide scribble pad" : "or scribble something instead ✏️"}
        </button>
      </div>

      {previewUrl && extraPhotos.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {extraPreviewUrls.map((url, i) => (
            <div key={i} className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url} alt="" className="w-full h-32 object-cover rounded border" />
              <button
                onClick={() => removeExtraPhoto(i)}
                className="absolute top-1 right-1 bg-black/70 text-white rounded-full w-5 h-5 text-xs leading-5"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {previewUrl && (
        <label className="text-xs underline opacity-70 hover:opacity-100 cursor-pointer inline-block">
          + add another photo (back / label / another angle / another page) — as many as you want
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

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={keepAsIs} onChange={(e) => setKeepAsIs(e.target.checked)} />
        This is an already-finished document — don&apos;t let AI rewrite it, just suggest where it goes
      </label>

      <div className="flex flex-wrap gap-2 items-center">
        <button
          onClick={sortWithAI}
          disabled={busy || (!text.trim() && !file)}
          className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
        >
          Sort
        </button>
      </div>
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-sm opacity-50">or add manually:</span>
        <button onClick={() => addManual("activity")} className="border rounded px-3 py-1 text-sm">
          + Activity
        </button>
        <button onClick={() => addManual("food")} className="border rounded px-3 py-1 text-sm">
          + Food
        </button>
        <button onClick={() => addManual("exercise")} className="border rounded px-3 py-1 text-sm">
          + Exercise
        </button>
        <button onClick={() => addManual("substance")} className="border rounded px-3 py-1 text-sm">
          + Substance
        </button>
        <button onClick={() => addManual("todo")} className="border rounded px-3 py-1 text-sm">
          + Todo
        </button>
        <button onClick={() => addManual("body_stat")} className="border rounded px-3 py-1 text-sm">
          + Weight
        </button>
        <button onClick={() => addManual("ingredient_preset")} className="border rounded px-3 py-1 text-sm">
          + Ingredient
        </button>
        <button onClick={() => addManual("meal_composition")} className="border rounded px-3 py-1 text-sm">
          + Composed meal
        </button>
        <button onClick={() => addManual("workout_routine")} className="border rounded px-3 py-1 text-sm">
          + Routine
        </button>
        <button onClick={() => addManual("wardrobe_item")} className="border rounded px-3 py-1 text-sm">
          + Item
        </button>
        <button onClick={() => addManual("outfit_composition")} className="border rounded px-3 py-1 text-sm">
          + Outfit
        </button>
        <button onClick={() => addManual("outfit_photo")} className="border rounded px-3 py-1 text-sm">
          + Outfit Photo
        </button>
        <button onClick={() => addManual("grooming_item")} className="border rounded px-3 py-1 text-sm">
          + Product
        </button>
        <button onClick={() => addManual("grooming_routine_composition")} className="border rounded px-3 py-1 text-sm">
          + Grooming Routine
        </button>
        <button onClick={() => addManual("document_entry")} className="border rounded px-3 py-1 text-sm">
          + Document
        </button>
        <button onClick={() => addManual("home_item")} className="border rounded px-3 py-1 text-sm">
          + Home Item
        </button>
        <button onClick={() => addManual("residence_entry")} className="border rounded px-3 py-1 text-sm">
          + Residence
        </button>
        <button onClick={() => addManual("experience_entry")} className="border rounded px-3 py-1 text-sm">
          + Experience
        </button>
        <button onClick={() => addManual("person_entry")} className="border rounded px-3 py-1 text-sm">
          + Person
        </button>
        <button onClick={() => addManual("credit_card_entry")} className="border rounded px-3 py-1 text-sm">
          + Credit Card
        </button>
        <button onClick={() => addManual("investment_entry")} className="border rounded px-3 py-1 text-sm">
          + Investment
        </button>
      </div>

      {entries.length > 0 && (
        <div className="border rounded p-4 space-y-3">
          <h2 className="font-medium">Review before saving</h2>
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
          <button
            onClick={saveAll}
            disabled={busy}
            className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Save {entries.length} entr{entries.length === 1 ? "y" : "ies"}
          </button>
        </div>
      )}

      {status && <p className="text-sm opacity-70">{status}</p>}
    </div>
  );
}
