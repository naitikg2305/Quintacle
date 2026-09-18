"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createOutfit,
  createWardrobeItem,
  listOutfits,
  listWardrobeItems,
  Outfit,
  outfitAssetUrl,
  wardrobeAssetUrl,
  WardrobeItem,
} from "@/lib/api";
import ImageLightbox from "@/components/ImageLightbox";

const CATEGORIES = ["jacket", "pants", "shirt", "shoes", "sunglasses", "accessory"];

function ItemThumb({ item, size = "w-full aspect-square" }: { item: WardrobeItem; size?: string }) {
  const asset = item.assets?.[0];
  if (asset) {
    return <ImageLightbox src={wardrobeAssetUrl(asset)} alt={item.name} className={`${size} object-cover rounded border`} />;
  }
  return (
    <div className={`${size} rounded border flex items-center justify-center text-xs opacity-50 bg-black/5 dark:bg-white/10`}>
      {item.name}
    </div>
  );
}

export default function WardrobePage() {
  const [items, setItems] = useState<WardrobeItem[]>([]);
  const [outfits, setOutfits] = useState<Outfit[]>([]);
  const [category, setCategory] = useState<string | null>(null);

  const [selected, setSelected] = useState<string[]>([]);
  const [outfitName, setOutfitName] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [formCategory, setFormCategory] = useState("jacket");
  const [description, setDescription] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);

  const byName = useMemo(() => new Map(items.map((i) => [i.name, i])), [items]);

  async function refresh() {
    setItems(await listWardrobeItems());
    setOutfits(await listOutfits());
  }

  useEffect(() => {
    refresh();
  }, []);

  const visible = category ? items.filter((i) => i.category === category) : items;

  function toggle(name: string) {
    setSelected((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]));
  }

  async function saveOutfit() {
    if (!outfitName.trim() || selected.length === 0) return;
    setBusy(true);
    await createOutfit(outfitName, selected);
    setStatus(`saved "${outfitName}"`);
    setOutfitName("");
    setSelected([]);
    await refresh();
    setBusy(false);
  }

  async function submitItem() {
    if (!name.trim()) return;
    setBusy(true);
    await createWardrobeItem(name, formCategory, description, photos);
    setName("");
    setDescription("");
    setPhotos([]);
    setShowAdd(false);
    await refresh();
    setBusy(false);
  }

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      <div>
        <h1 className="text-2xl font-semibold">Wardrobe</h1>
        <p className="text-sm opacity-60 -mt-1">Your real item library, and an outfit builder on top of it.</p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setCategory(null)}
            className={`border rounded px-3 py-1.5 text-sm ${!category ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
          >
            All
          </button>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`border rounded px-3 py-1.5 text-sm ${category === c ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
            >
              {c}
            </button>
          ))}
          <button onClick={() => setShowAdd((s) => !s)} className="border rounded px-3 py-1.5 text-sm ml-auto">
            + Item
          </button>
        </div>

        {showAdd && (
          <div className="border rounded p-4 space-y-2">
            <div className="flex gap-2">
              <input
                className="flex-1 border rounded px-2 py-1 text-sm"
                placeholder="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <select className="border rounded px-2 py-1 text-sm" value={formCategory} onChange={(e) => setFormCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <input
              className="w-full border rounded px-2 py-1 text-sm"
              placeholder="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <input
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => setPhotos(Array.from(e.target.files ?? []))}
              className="text-sm"
            />
            {photos.length > 0 && <p className="text-xs opacity-60">{photos.length} photo{photos.length === 1 ? "" : "s"} selected</p>}
            <button
              onClick={submitItem}
              disabled={busy || !name.trim()}
              className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Save item
            </button>
          </div>
        )}

        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
          {visible.length === 0 && <p className="text-sm opacity-60 col-span-full">No items here yet.</p>}
          {visible.map((item) => (
            <button
              key={item.name}
              onClick={() => toggle(item.name)}
              className={`space-y-1 text-left rounded p-1 ${selected.includes(item.name) ? "ring-2 ring-black dark:ring-white" : ""}`}
            >
              <ItemThumb item={item} />
              <p className="text-xs truncate">{item.name}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="border rounded p-4 space-y-3">
        <h2 className="font-medium text-sm">Build an outfit</h2>
        <p className="text-xs opacity-60">Click items above to add/remove them here.</p>
        {selected.length === 0 ? (
          <p className="text-sm opacity-50">Nothing selected yet.</p>
        ) : (
          <div className="flex gap-2 flex-wrap">
            {selected.map((n) => {
              const item = byName.get(n);
              return (
                <div key={n} className="w-20 space-y-1">
                  {item ? <ItemThumb item={item} size="w-20 h-20" /> : <div className="w-20 h-20 rounded border" />}
                  <p className="text-[10px] truncate text-center">{n}</p>
                </div>
              );
            })}
          </div>
        )}
        <div className="flex gap-2">
          <input
            className="flex-1 border rounded px-2 py-1 text-sm"
            placeholder="outfit name"
            value={outfitName}
            onChange={(e) => setOutfitName(e.target.value)}
          />
          <button
            onClick={saveOutfit}
            disabled={busy || !outfitName.trim() || selected.length === 0}
            className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Save outfit
          </button>
        </div>
        {status && <p className="text-xs opacity-60">{status}</p>}
      </div>

      <div className="space-y-2">
        <h2 className="font-medium text-sm">Saved outfits</h2>
        {outfits.length === 0 && <p className="text-sm opacity-60">None yet.</p>}
        {outfits.map((o) => (
          <div key={o.name} className="border rounded p-3">
            <p className="text-sm font-medium mb-2">{o.name}</p>
            {o.asset ? (
              // A full-outfit photo (mirror selfie) saved as is — the photo
              // itself is the record, no item breakdown to show.
              <ImageLightbox src={outfitAssetUrl(o.asset)} alt={o.name} className="w-32 h-32 object-cover rounded border" />
            ) : (
              <div className="flex gap-2 flex-wrap">
                {o.items.map((n) => {
                  const item = byName.get(n);
                  return (
                    <div key={n} className="w-16">
                      {item ? <ItemThumb item={item} size="w-16 h-16" /> : <div className="w-16 h-16 rounded border" />}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
