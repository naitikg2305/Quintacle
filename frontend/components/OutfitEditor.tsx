"use client";

import { useEffect, useState } from "react";
import { listWardrobeItems, OutfitItemComponent, ParsedOutfitComposition, WardrobeItem } from "@/lib/api";

type Props = {
  value: ParsedOutfitComposition;
  onChange: (next: ParsedOutfitComposition) => void;
};

const CATEGORIES = ["jacket", "pants", "shirt", "shoes", "sunglasses", "accessory"];

// Presence-only composer — unlike meals, an outfit has no quantity/scaling
// math, just "these items go together". Shared by the Drop page's "outfit:"
// prefix and the KB chat's "Suggest outfit" — same fuzzy-match-against-the-
// real-library pattern as MealCompositionEditor, simpler shape.
export default function OutfitEditor({ value, onChange }: Props) {
  const [library, setLibrary] = useState<WardrobeItem[]>([]);
  const [picked, setPicked] = useState("");

  useEffect(() => {
    listWardrobeItems().then(setLibrary);
  }, []);

  function setItems(items: OutfitItemComponent[]) {
    onChange({ ...value, items });
  }

  function updateItem(i: number, patch: Partial<OutfitItemComponent>) {
    setItems(value.items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  }

  function removeItem(i: number) {
    setItems(value.items.filter((_, idx) => idx !== i));
  }

  function addFromLibrary() {
    const item = library.find((i) => i.name === picked);
    if (!item) return;
    setItems([...value.items, { name: item.name, category: item.category, is_new: false }]);
    setPicked("");
  }

  function addManualNew() {
    setItems([...value.items, { name: "", category: "accessory", description: "", is_new: true }]);
  }

  return (
    <div className="space-y-2">
      <input
        className="border rounded px-2 py-1 text-sm w-full"
        placeholder="outfit name"
        value={value.outfit_name}
        onChange={(e) => onChange({ ...value, outfit_name: e.target.value })}
      />

      {value.items.map((it, i) => (
        <div key={i} className="flex gap-2 items-center text-xs border-b pb-1 last:border-b-0">
          {it.is_new ? (
            <>
              <input
                className="border rounded px-1 py-0.5 w-32"
                placeholder="new item name"
                value={it.name}
                onChange={(e) => updateItem(i, { name: e.target.value })}
              />
              <select
                className="border rounded px-1 py-0.5"
                value={it.category}
                onChange={(e) => updateItem(i, { category: e.target.value })}
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
                value={it.description ?? ""}
                onChange={(e) => updateItem(i, { description: e.target.value })}
              />
              <span className="opacity-50 px-1 rounded bg-black/5 dark:bg-white/10">new</span>
            </>
          ) : (
            <>
              <span className="w-32 truncate">{it.name}</span>
              <span className="opacity-60 flex-1">{it.category}</span>
            </>
          )}
          <button onClick={() => removeItem(i)} className="opacity-50 hover:opacity-100 px-1 ml-auto">
            ✕
          </button>
        </div>
      ))}

      <div className="flex gap-2 items-center text-xs">
        <select className="border rounded px-2 py-1 flex-1" value={picked} onChange={(e) => setPicked(e.target.value)}>
          <option value="">add from item library...</option>
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
          + new item
        </button>
      </div>
    </div>
  );
}
