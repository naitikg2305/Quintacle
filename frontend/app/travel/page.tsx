"use client";

import { useEffect, useMemo, useState } from "react";
import { createExperience, Experience, listExperiences } from "@/lib/api";

const EXPERIENCE_KINDS = ["restaurant", "bar", "club", "activity", "historic"];

export default function TravelPage() {
  const [experiences, setExperiences] = useState<Experience[]>([]);
  const [city, setCity] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("restaurant");
  const [formCity, setFormCity] = useState("");
  const [rating, setRating] = useState("");
  const [wouldReturn, setWouldReturn] = useState<boolean | null>(null);
  const [visitedDate, setVisitedDate] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setExperiences(await listExperiences());
  }

  useEffect(() => {
    refresh();
  }, []);

  const cities = useMemo(() => Array.from(new Set(experiences.map((e) => e.city))).sort(), [experiences]);

  const inCity = useMemo(() => (city ? experiences.filter((e) => e.city === city) : experiences), [experiences, city]);

  // Counts scoped to whichever city is currently selected, so the filter
  // row reflects "what's actually here," not global totals across every city.
  const kindCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of inCity) {
      const key = EXPERIENCE_KINDS.includes(e.kind.toLowerCase()) ? e.kind.toLowerCase() : "other";
      m.set(key, (m.get(key) ?? 0) + 1);
    }
    return m;
  }, [inCity]);

  const visible = useMemo(() => {
    if (!kindFilter) return inCity;
    if (kindFilter === "other") return inCity.filter((e) => !EXPERIENCE_KINDS.includes(e.kind.toLowerCase()));
    return inCity.filter((e) => e.kind.toLowerCase() === kindFilter);
  }, [inCity, kindFilter]);

  const byKind = useMemo(() => {
    const grouped = new Map<string, Experience[]>();
    for (const e of visible) {
      const list = grouped.get(e.kind) ?? [];
      list.push(e);
      grouped.set(e.kind, list);
    }
    return grouped;
  }, [visible]);

  async function submit() {
    if (!name.trim() || !formCity.trim()) return;
    setBusy(true);
    await createExperience({
      name,
      city: formCity,
      kind,
      rating,
      would_return: wouldReturn,
      visited_date: visitedDate || null,
      notes,
    });
    setName("");
    setFormCity("");
    setRating("");
    setWouldReturn(null);
    setVisitedDate("");
    setNotes("");
    setShowForm(false);
    await refresh();
    setBusy(false);
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Travel &amp; Experiences</h1>
      <p className="text-sm opacity-60 -mt-4">
        Pick a city, then filter between restaurants, bars, clubs, activities, and historic spots.
      </p>

      <div className="flex items-center gap-2 flex-wrap">
        <select className="border rounded px-2 py-1 text-sm" value={city ?? ""} onChange={(e) => setCity(e.target.value || null)}>
          <option value="">All cities</option>
          {cities.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <button onClick={() => setShowForm((s) => !s)} className="border rounded px-3 py-1 text-sm">
          + Experience
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setKindFilter(null)}
          className={`text-xs border rounded px-2 py-1 ${!kindFilter ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
        >
          All ({inCity.length})
        </button>
        {[...EXPERIENCE_KINDS, "other"]
          .filter((k) => kindCounts.has(k))
          .map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              className={`text-xs border rounded px-2 py-1 capitalize ${kindFilter === k ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
            >
              {k}s ({kindCounts.get(k)})
            </button>
          ))}
      </div>

      {showForm && (
        <div className="border rounded p-4 space-y-2">
          <div className="flex gap-2">
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="name (e.g. Nobu)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <select className="border rounded px-2 py-1 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
              {[...EXPERIENCE_KINDS, "other"].map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="city"
              value={formCity}
              onChange={(e) => setFormCity(e.target.value)}
            />
          </div>
          <div className="flex gap-2 items-center">
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="rating / vibe"
              value={rating}
              onChange={(e) => setRating(e.target.value)}
            />
            <label className="flex items-center gap-1 text-xs shrink-0">
              <input type="checkbox" checked={wouldReturn === true} onChange={(e) => setWouldReturn(e.target.checked)} />
              would return
            </label>
            <input
              type="date"
              className="border rounded px-2 py-1 text-xs"
              value={visitedDate}
              onChange={(e) => setVisitedDate(e.target.value)}
            />
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <button
            onClick={submit}
            disabled={busy || !name.trim() || !formCity.trim()}
            className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Save experience
          </button>
        </div>
      )}

      <div className="space-y-4">
        {visible.length === 0 && <p className="text-sm opacity-60">Nothing logged yet.</p>}
        {Array.from(byKind.entries()).map(([k, items]) => (
          <div key={k} className="space-y-2">
            <h2 className="text-sm font-medium opacity-70 capitalize">{k}</h2>
            {items.map((e) => (
              <div key={e.slug} className="border rounded p-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm">{e.name}</span>
                  <span className="text-xs opacity-50">{e.city}</span>
                  {e.would_return === true && <span className="text-xs">↩️ would return</span>}
                  {e.would_return === false && <span className="text-xs opacity-50">wouldn&apos;t return</span>}
                  {e.visited_date && <span className="text-xs opacity-50">{e.visited_date}</span>}
                </div>
                {e.rating && <p className="text-xs opacity-70 mt-1">{e.rating}</p>}
                {e.notes && <p className="text-xs opacity-70 mt-1">{e.notes}</p>}
                {e.links.length > 0 && <p className="text-xs opacity-50 mt-1">🔗 {e.links.join(", ")}</p>}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
