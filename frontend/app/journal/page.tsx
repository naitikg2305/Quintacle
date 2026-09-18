"use client";

import { useEffect, useState } from "react";
import EntryCard from "@/components/EntryCard";
import { ExerciseSet, getJournal, listExerciseNames, listMeals, Meal, ParsedEntry, parseJournal, saveJournal } from "@/lib/api";
import { commitEntry } from "@/lib/entries";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// The nightly dump — its own page again, distinct from Drop (quick,
// structured, one-off things) and from the KB chat (planning/discussion).
// Journal is: write out how the day went, save it verbatim as the permanent
// record, and separately (optionally) have it parsed into structured log
// entries for review — same review/commit flow Drop uses, just triggered
// from a full day's narrative instead of a single quick note.
export default function JournalPage() {
  const [date, setDate] = useState(today());
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState(false);
  const [entries, setEntries] = useState<ParsedEntry[]>([]);
  const [meals, setMeals] = useState<Meal[]>([]);
  const [exerciseNames, setExerciseNames] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    listMeals().then(setMeals);
    listExerciseNames().then(setExerciseNames);
  }, []);

  useEffect(() => {
    setEntries([]);
    setStatus(null);
    getJournal(date).then((j) => {
      setContent(j.content ?? "");
      setSaved(j.content != null);
    });
  }, [date]);

  async function save() {
    setBusy(true);
    setStatus("saving...");
    await saveJournal(date, content);
    setSaved(true);
    setStatus("saved");
    setBusy(false);
  }

  async function parse() {
    if (!content.trim()) return;
    setBusy(true);
    setStatus("parsing...");
    try {
      const parsed = await parseJournal(date, content);
      setEntries((prev) => [...prev, ...parsed]);
      setStatus(`${parsed.length} entr${parsed.length === 1 ? "y" : "ies"} proposed — review below`);
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
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

  async function saveEntries() {
    setBusy(true);
    setStatus("saving entries...");
    for (const entry of entries) {
      await commitEntry(date, entry);
    }
    setStatus(`saved ${entries.length} entr${entries.length === 1 ? "y" : "ies"}`);
    setEntries([]);
    setBusy(false);
  }

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Journal</h1>
      <p className="text-sm opacity-60 -mt-2">
        The nightly dump — write how the day went, save it verbatim. Parsing it into structured entries is separate and
        optional; nothing here is ever rewritten by AI.
      </p>

      <label className="block text-sm">
        Date
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="block border rounded px-2 py-1 mt-1" />
      </label>

      <textarea
        className="w-full border rounded p-2 text-sm"
        rows={12}
        placeholder="How did today go?"
        value={content}
        onChange={(e) => {
          setContent(e.target.value);
          setSaved(false);
        }}
      />

      <div className="flex flex-wrap gap-2 items-center">
        <button
          onClick={save}
          disabled={busy || !content.trim()}
          className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
        >
          {saved ? "Saved ✓" : "Save Journal"}
        </button>
        <button
          onClick={parse}
          disabled={busy || !content.trim()}
          className="border rounded px-4 py-2 text-sm disabled:opacity-40"
        >
          Parse into entries
        </button>
        {status && <span className="text-sm opacity-70">{status}</span>}
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
            onClick={saveEntries}
            disabled={busy}
            className="w-full bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Save {entries.length} entr{entries.length === 1 ? "y" : "ies"}
          </button>
        </div>
      )}
    </div>
  );
}
