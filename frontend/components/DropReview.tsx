"use client";

import { useState } from "react";
import EntryCard from "@/components/EntryCard";
import { ExerciseSet, Meal, ParsedEntry } from "@/lib/api";
import { BLANK } from "@/lib/entries";

// Shared review orchestration for every surface that proposes ParsedEntry
// batches — the Drop page and the chat scratchpad (next-wave §8: chat-drop
// parity). Deliberately generic over the whole ParsedEntry union: a new
// entry type only needs its EntryCard case + BLANK/commit entries; nothing
// here enumerates types, so nothing here changes.

// Owns the proposed-entries state and the per-entry edit handlers EntryCard
// needs (moved verbatim from the Drop page). Saving stays caller-side —
// each surface commits differently (assets/journal/faces vs text-only).
export function useParsedEntries() {
  const [entries, setEntries] = useState<ParsedEntry[]>([]);

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

  return { entries, setEntries, addManual, updateEntry, removeEntry, updateSet, addSet, removeSet };
}

type EntryReviewListProps = {
  entries: ParsedEntry[];
  meals: Meal[];
  exerciseNames: string[];
  onUpdate: (i: number, patch: Partial<ParsedEntry>) => void;
  onRemove: (i: number) => void;
  onUpdateSet: (entryIndex: number, setIndex: number, patch: Partial<ExerciseSet>) => void;
  onAddSet: (entryIndex: number) => void;
  onRemoveSet: (entryIndex: number, setIndex: number) => void;
};

// The mapped-EntryCard review block, verbatim from the Drop page. Purely
// presentational; the Save button (and what saving means) stays caller-side.
export function EntryReviewList({
  entries,
  meals,
  exerciseNames,
  onUpdate,
  onRemove,
  onUpdateSet,
  onAddSet,
  onRemoveSet,
}: EntryReviewListProps) {
  return (
    <>
      {entries.map((entry, i) => (
        <EntryCard
          key={i}
          entry={entry}
          index={i}
          meals={meals}
          exerciseNames={exerciseNames}
          onUpdate={onUpdate}
          onRemove={onRemove}
          onUpdateSet={onUpdateSet}
          onAddSet={onAddSet}
          onRemoveSet={onRemoveSet}
        />
      ))}
    </>
  );
}
