"use client";

import { useEffect, useState } from "react";
import { GroomingItem, GroomingRoutineStep, listGroomingItems, ParsedGroomingRoutineComposition } from "@/lib/api";

type Props = {
  value: ParsedGroomingRoutineComposition;
  onChange: (next: ParsedGroomingRoutineComposition) => void;
};

const CATEGORIES = ["skincare", "haircare", "shaving", "oral", "fragrance", "tool"];

// Same fuzzy-match-against-the-real-library composer as Outfit/Meal, but
// ORDER matters here (cleanser before moisturizer before sunscreen) — unlike
// an outfit's presence-only set, so this gets reorder controls the others don't.
export default function GroomingRoutineEditor({ value, onChange }: Props) {
  const [library, setLibrary] = useState<GroomingItem[]>([]);
  const [picked, setPicked] = useState("");

  useEffect(() => {
    listGroomingItems().then(setLibrary);
  }, []);

  function setSteps(steps: GroomingRoutineStep[]) {
    onChange({ ...value, steps });
  }

  function updateStep(i: number, patch: Partial<GroomingRoutineStep>) {
    setSteps(value.steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  function removeStep(i: number) {
    setSteps(value.steps.filter((_, idx) => idx !== i));
  }

  function moveStep(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= value.steps.length) return;
    const steps = [...value.steps];
    [steps[i], steps[j]] = [steps[j], steps[i]];
    setSteps(steps);
  }

  function addFromLibrary() {
    const item = library.find((i) => i.name === picked);
    if (!item) return;
    setSteps([...value.steps, { name: item.name, category: item.category, is_new: false }]);
    setPicked("");
  }

  function addManualNew() {
    setSteps([...value.steps, { name: "", category: "skincare", description: "", is_new: true }]);
  }

  return (
    <div className="space-y-2">
      <input
        className="border rounded px-2 py-1 text-sm w-full"
        placeholder="routine name (e.g. AM Routine)"
        value={value.routine_name}
        onChange={(e) => onChange({ ...value, routine_name: e.target.value })}
      />

      {value.steps.map((s, i) => (
        <div key={i} className="flex gap-2 items-center text-xs border-b pb-1 last:border-b-0">
          <span className="opacity-40 w-4 shrink-0">{i + 1}</span>
          <div className="flex flex-col shrink-0">
            <button onClick={() => moveStep(i, -1)} disabled={i === 0} className="opacity-50 hover:opacity-100 disabled:opacity-20 leading-none">
              ▲
            </button>
            <button
              onClick={() => moveStep(i, 1)}
              disabled={i === value.steps.length - 1}
              className="opacity-50 hover:opacity-100 disabled:opacity-20 leading-none"
            >
              ▼
            </button>
          </div>
          {s.is_new ? (
            <>
              <input
                className="border rounded px-1 py-0.5 w-32"
                placeholder="new product name"
                value={s.name}
                onChange={(e) => updateStep(i, { name: e.target.value })}
              />
              <select
                className="border rounded px-1 py-0.5"
                value={s.category}
                onChange={(e) => updateStep(i, { category: e.target.value })}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <input
                className="border rounded px-1 py-0.5 flex-1"
                placeholder="description"
                value={s.description ?? ""}
                onChange={(e) => updateStep(i, { description: e.target.value })}
              />
              <span className="opacity-50 px-1 rounded bg-black/5 dark:bg-white/10">new</span>
            </>
          ) : (
            <>
              <span className="w-32 truncate">{s.name}</span>
              <span className="opacity-60 flex-1">{s.category}</span>
            </>
          )}
          <button onClick={() => removeStep(i)} className="opacity-50 hover:opacity-100 px-1 ml-auto">
            ✕
          </button>
        </div>
      ))}

      <div className="flex gap-2 items-center text-xs">
        <select className="border rounded px-2 py-1 flex-1" value={picked} onChange={(e) => setPicked(e.target.value)}>
          <option value="">add from product library...</option>
          {library.map((i) => (
            <option key={i.name} value={i.name}>
              {i.name} ({i.category})
            </option>
          ))}
        </select>
        <button onClick={addFromLibrary} disabled={!picked} className="border rounded px-2 py-1 disabled:opacity-40">
          + add
        </button>
        <button onClick={addManualNew} className="border rounded px-2 py-1">
          + new product
        </button>
      </div>
    </div>
  );
}
