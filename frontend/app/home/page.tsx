"use client";

import { useEffect, useState } from "react";
import { createHomeItem, createResidence, HomeItem, homeAssetUrl, listHomeItems, listResidences, Residence } from "@/lib/api";

const CATEGORIES = ["furniture", "decor", "electronics", "kitchen", "appliance", "storage"];

export default function HomePage() {
  const [residences, setResidences] = useState<Residence[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [items, setItems] = useState<HomeItem[]>([]);

  const [showResidenceForm, setShowResidenceForm] = useState(false);
  const [resName, setResName] = useState("");
  const [resCity, setResCity] = useState("");
  const [resAddress, setResAddress] = useState("");
  const [resMovedIn, setResMovedIn] = useState("");

  const [name, setName] = useState("");
  const [category, setCategory] = useState("furniture");
  const [location, setLocation] = useState("");
  const [price, setPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function refreshResidences() {
    const list = await listResidences();
    setResidences(list);
    if (!selected && list.length > 0) {
      const current = list.find((r) => !r.moved_out) ?? list[list.length - 1];
      setSelected(current.name);
    }
  }

  async function refreshItems(residenceName: string) {
    setItems(await listHomeItems(residenceName));
  }

  useEffect(() => {
    refreshResidences();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selected) refreshItems(selected);
  }, [selected]);

  async function submitResidence() {
    if (!resName.trim() || !resCity.trim()) return;
    setBusy(true);
    await createResidence({ name: resName, city: resCity, address: resAddress, moved_in: resMovedIn || null });
    setResName("");
    setResCity("");
    setResAddress("");
    setResMovedIn("");
    setShowResidenceForm(false);
    await refreshResidences();
    setBusy(false);
  }

  async function submitItem() {
    if (!name.trim() || !selected) return;
    setBusy(true);
    setStatus("saving...");
    await createHomeItem(
      { name, residence_name: selected, category, location, purchase_price: price ? Number(price) : null, notes },
      files
    );
    setStatus("saved");
    setName("");
    setLocation("");
    setPrice("");
    setNotes("");
    setFiles([]);
    await refreshItems(selected);
    setBusy(false);
  }

  const currentResidence = residences.find((r) => r.name === selected);

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Home</h1>
      <p className="text-sm opacity-60 -mt-4">
        Apartments/living spaces over time, and what's in them — ask "where's my Halloween decor" and get "closet, box 3," not
        a chat search.
      </p>

      <div className="flex items-center gap-2 flex-wrap">
        <select
          className="border rounded px-2 py-1 text-sm"
          value={selected ?? ""}
          onChange={(e) => setSelected(e.target.value || null)}
        >
          {residences.length === 0 && <option value="">No residences yet</option>}
          {residences.map((r) => (
            <option key={r.name} value={r.name}>
              {r.name} ({r.city}){!r.moved_out ? " — current" : ""}
            </option>
          ))}
        </select>
        <button onClick={() => setShowResidenceForm((s) => !s)} className="border rounded px-3 py-1 text-sm">
          + Residence
        </button>
      </div>

      {showResidenceForm && (
        <div className="border rounded p-4 space-y-2">
          <div className="flex gap-2">
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="name (e.g. Iris 307)"
              value={resName}
              onChange={(e) => setResName(e.target.value)}
            />
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="city"
              value={resCity}
              onChange={(e) => setResCity(e.target.value)}
            />
          </div>
          <input
            className="w-full border rounded px-2 py-1 text-sm"
            placeholder="address (optional)"
            value={resAddress}
            onChange={(e) => setResAddress(e.target.value)}
          />
          <label className="block text-sm">
            moved in
            <input
              type="date"
              className="block border rounded px-2 py-1 mt-1"
              value={resMovedIn}
              onChange={(e) => setResMovedIn(e.target.value)}
            />
          </label>
          <button
            onClick={submitResidence}
            disabled={busy || !resName.trim() || !resCity.trim()}
            className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Save residence
          </button>
        </div>
      )}

      {currentResidence && (
        <>
          <div className="border rounded p-4 space-y-3">
            <h2 className="font-medium text-sm">Add an item to {currentResidence.name}</h2>
            <div className="flex gap-2">
              <input
                className="flex-1 border rounded px-2 py-1 text-sm"
                placeholder="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <select className="border rounded px-2 py-1 text-sm" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex gap-2">
              <input
                className="flex-1 border rounded px-2 py-1 text-sm"
                placeholder="location (e.g. closet, box 3)"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
              <input
                type="number"
                className="w-28 border rounded px-2 py-1 text-sm"
                placeholder="price"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={2}
              placeholder="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
            <input
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="text-sm"
            />
            {files.length > 0 && <p className="text-xs opacity-60">{files.length} photo{files.length === 1 ? "" : "s"} selected</p>}
            <button
              onClick={submitItem}
              disabled={busy || !name.trim()}
              className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Save item
            </button>
            {status && <p className="text-sm opacity-70">{status}</p>}
          </div>

          <div className="space-y-2">
            {items.length === 0 && <p className="text-sm opacity-60">Nothing cataloged here yet.</p>}
            {items.map((item) => (
              <div key={item.slug} className="border rounded p-3 flex items-start gap-3">
                {(item.assets ?? []).length > 0 && (
                  <div className="flex gap-1 shrink-0">
                    {(item.assets ?? []).map((asset) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img key={asset} src={homeAssetUrl(currentResidence.folder, asset)} alt="" className="w-16 h-16 object-cover rounded" />
                    ))}
                  </div>
                )}
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{item.name}</span>
                    <span className="text-xs opacity-50">{item.category}</span>
                  </div>
                  {item.notes && <p className="text-xs opacity-70 mt-1">{item.notes}</p>}
                  <div className="text-xs opacity-50 mt-1 flex gap-3">
                    {item.location && <span>📍 {item.location}</span>}
                    {item.purchase_price != null && <span>${item.purchase_price}</span>}
                    {item.purchase_date && <span>bought {item.purchase_date}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
