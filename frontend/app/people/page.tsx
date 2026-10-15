"use client";

import { useEffect, useMemo, useState } from "react";
import { createPerson, listPeople, Person, personAppearances, PersonAppearances } from "@/lib/api";

const CATEGORIES = ["friend", "dating", "family", "coworker", "acquaintance", "other"];
const OTHER_CATEGORIES = ["family", "coworker", "acquaintance", "other"];

// Two separate rosters, not just a filter among six equal options — friends
// and dating are the two you actually want to scan independently at a
// glance. Everything else (family/coworker/acquaintance/other) lives in a
// third "Other" roster with its own sub-filter, since it's a real mixed bag.
type Roster = "friend" | "dating" | "other";

export default function PeoplePage() {
  const [people, setPeople] = useState<Person[]>([]);
  const [roster, setRoster] = useState<Roster>("friend");
  const [otherCategory, setOtherCategory] = useState<string | null>(null);

  // "Appears in" is COMPUTED from the graph's pictured_with edges (nothing
  // is written into the person's file) — fetched lazily per person on
  // expand, keyed by slug. null while loading.
  const [appearances, setAppearances] = useState<Record<string, PersonAppearances | null>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [formCategory, setFormCategory] = useState("friend");
  const [howMet, setHowMet] = useState("");
  const [metDate, setMetDate] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setPeople(await listPeople());
  }

  useEffect(() => {
    refresh();
  }, []);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of people) m.set(p.category, (m.get(p.category) ?? 0) + 1);
    return m;
  }, [people]);

  const otherCount = OTHER_CATEGORIES.reduce((sum, c) => sum + (counts.get(c) ?? 0), 0);

  const visible = useMemo(() => {
    if (roster === "other") {
      const inOther = people.filter((p) => OTHER_CATEGORIES.includes(p.category));
      return otherCategory ? inOther.filter((p) => p.category === otherCategory) : inOther;
    }
    return people.filter((p) => p.category === roster);
  }, [people, roster, otherCategory]);

  async function toggleAppearances(p: Person) {
    const open = !expanded[p.slug];
    setExpanded((prev) => ({ ...prev, [p.slug]: open }));
    if (open && appearances[p.slug] === undefined) {
      setAppearances((prev) => ({ ...prev, [p.slug]: null }));
      try {
        const result = await personAppearances(p.name);
        setAppearances((prev) => ({ ...prev, [p.slug]: result }));
      } catch {
        setAppearances((prev) => ({ ...prev, [p.slug]: { name: p.name, photos: [], dates: [] } }));
      }
    }
  }

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    await createPerson({ name, category: formCategory, how_met: howMet, met_date: metDate || null, notes });
    setName("");
    setHowMet("");
    setMetDate("");
    setNotes("");
    setShowForm(false);
    await refresh();
    setBusy(false);
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">People</h1>
      <p className="text-sm opacity-60 -mt-4">
        Two separate rosters, plus everything else. Each person gets their own folder — chat about them there, and anything
        substantive you mention about them in a journal/drop gets filed in automatically.
      </p>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setRoster("friend")}
          className={`border rounded px-4 py-2 text-sm font-medium ${roster === "friend" ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
        >
          Friends ({counts.get("friend") ?? 0})
        </button>
        <button
          onClick={() => setRoster("dating")}
          className={`border rounded px-4 py-2 text-sm font-medium ${roster === "dating" ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
        >
          Dating ({counts.get("dating") ?? 0})
        </button>
        <button
          onClick={() => setRoster("other")}
          className={`border rounded px-4 py-2 text-sm font-medium ${roster === "other" ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
        >
          Other ({otherCount})
        </button>
        <button onClick={() => setShowForm((s) => !s)} className="border rounded px-3 py-1.5 text-sm ml-auto">
          + Person
        </button>
      </div>

      {roster === "other" && (
        <div className="flex items-center gap-2 flex-wrap -mt-2">
          <button
            onClick={() => setOtherCategory(null)}
            className={`text-xs border rounded px-2 py-1 ${!otherCategory ? "bg-black/10 dark:bg-white/10" : ""}`}
          >
            all
          </button>
          {OTHER_CATEGORIES.filter((c) => counts.has(c)).map((c) => (
            <button
              key={c}
              onClick={() => setOtherCategory(c)}
              className={`text-xs border rounded px-2 py-1 ${otherCategory === c ? "bg-black/10 dark:bg-white/10" : ""}`}
            >
              {c} ({counts.get(c)})
            </button>
          ))}
        </div>
      )}

      {showForm && (
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
            <input
              type="date"
              className="border rounded px-2 py-1 text-sm"
              value={metDate}
              onChange={(e) => setMetDate(e.target.value)}
            />
          </div>
          <input
            className="w-full border rounded px-2 py-1 text-sm"
            placeholder="how you met"
            value={howMet}
            onChange={(e) => setHowMet(e.target.value)}
          />
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={3}
            placeholder="notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <button
            onClick={submit}
            disabled={busy || !name.trim()}
            className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Save person
          </button>
        </div>
      )}

      <div className="space-y-2">
        {visible.length === 0 && <p className="text-sm opacity-60">Nobody in this roster yet.</p>}
        {visible.map((p) => (
          <div key={p.slug} className="border rounded p-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm">{p.name}</span>
                {roster === "other" && <span className="text-xs opacity-50">{p.category}</span>}
                {p.met_date && <span className="text-xs opacity-50">met {p.met_date}</span>}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => toggleAppearances(p)}
                  className="text-xs border rounded px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5"
                >
                  📷 Appears in {expanded[p.slug] ? "▴" : "▾"}
                </button>
                <a
                  href={`/kb/folder?path=${encodeURIComponent(p.folder)}`}
                  className="text-xs border rounded px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5"
                >
                  💬 Chat about {p.name} →
                </a>
              </div>
            </div>
            {p.how_met && <p className="text-xs opacity-60 mt-1">met via {p.how_met}</p>}
            {p.notes && <p className="text-sm mt-1 whitespace-pre-wrap">{p.notes}</p>}
            {expanded[p.slug] && (
              <div className="mt-2 border-t pt-2">
                {appearances[p.slug] === null || appearances[p.slug] === undefined ? (
                  <p className="text-xs opacity-60">loading…</p>
                ) : appearances[p.slug]!.photos.length === 0 ? (
                  <p className="text-xs opacity-60">No tagged photos yet — drop one and tag the face.</p>
                ) : (
                  <ul className="space-y-1">
                    {appearances[p.slug]!.photos.map((photo) => (
                      <li key={`${photo.folder}/${photo.slug}`}>
                        <a
                          href={`/kb/browse?path=${encodeURIComponent(photo.folder)}&open=${encodeURIComponent(photo.slug)}`}
                          className="text-xs underline hover:opacity-70"
                        >
                          📷 {photo.title}
                        </a>
                        <span className="text-xs opacity-50 ml-1">({photo.folder})</span>
                      </li>
                    ))}
                  </ul>
                )}
                {appearances[p.slug] && appearances[p.slug]!.dates.length > 0 && (
                  <p className="text-xs opacity-60 mt-1">In your journal on {appearances[p.slug]!.dates.join(", ")}</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
