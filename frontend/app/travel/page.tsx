"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CalendarDays, CircleCheck, Map as MapIcon, Plane, Plus, Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Badge, EmptyState, PageHeader, Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { formatIsoDate } from "@/lib/date";
import {
  addBucketPlace,
  BucketPlace,
  createExperience,
  deleteBucketPlace,
  Experience,
  listBucketPlaces,
  listExperiences,
  listPlannedTrips,
  listUnsortedTravel,
  movePlannedTrip,
  PlannedTrip,
} from "@/lib/api";

const EXPERIENCE_KINDS = ["restaurant", "bar", "club", "activity", "historic"];

type Tab = "experiences" | "planned" | "bucket";

export default function TravelPage() {
  return (
    <Suspense>
      <TravelPageInner />
    </Suspense>
  );
}

function TravelPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const raw = searchParams.get("tab");
  const tab: Tab = raw === "planned" || raw === "bucket" ? raw : "experiences";
  const cityParam = searchParams.get("city");

  function setTab(t: Tab) {
    router.replace(t === "experiences" ? pathname : `${pathname}?tab=${t}`);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageHeader title="Travel" icon={Plane} subtitle="Where you've been, where you're going, and where you want to go." />
      <Segmented<Tab>
        value={tab}
        onChange={setTab}
        options={[
          { value: "experiences", label: "Experiences" },
          { value: "planned", label: "Planned" },
          { value: "bucket", label: "Bucket list" },
        ]}
      />
      {tab === "experiences" && <ExperiencesTab key={cityParam ?? ""} initialCity={cityParam} />}
      {tab === "planned" && <PlannedTab />}
      {tab === "bucket" && <BucketTab />}
    </div>
  );
}

function kbLink(folder: string, slug: string) {
  return `/kb/browse?path=${encodeURIComponent(folder)}&open=${encodeURIComponent(slug)}`;
}

function dateRange(start: string | null, end: string | null): string | null {
  if (start && end && start.slice(0, 10) !== end.slice(0, 10)) return `${formatIsoDate(start)} – ${formatIsoDate(end)}`;
  if (start) return formatIsoDate(start);
  if (end) return `until ${formatIsoDate(end)}`;
  return null;
}

function statusTone(status: string): "accent" | "ok" | "warn" | "danger" | "muted" {
  const s = status.toLowerCase();
  if (/(booked|confirmed|done|paid)/.test(s)) return "ok";
  if (/(idea|maybe|draft|tentative)/.test(s)) return "muted";
  if (/(cancel)/.test(s)) return "danger";
  if (/(planning|pending|todo)/.test(s)) return "warn";
  return "accent";
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function PlannedTab() {
  const [trips, setTrips] = useState<PlannedTrip[] | null>(null);
  const [unsorted, setUnsorted] = useState<PlannedTrip[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [groupDraft, setGroupDraft] = useState<Record<string, string>>({});
  const [moving, setMoving] = useState<string | null>(null);

  async function refresh() {
    try {
      const [p, u] = await Promise.all([listPlannedTrips(), listUnsortedTravel().catch(() => [] as PlannedTrip[])]);
      setTrips(p);
      setUnsorted(u);
      setError(null);
    } catch (e) {
      setTrips([]);
      setError(errorText(e));
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, []);

  // Groups keep the API's start-date order (first trip in a group places the group).
  const groups = useMemo(() => {
    const m = new Map<string, PlannedTrip[]>();
    for (const t of trips ?? []) {
      const g = t.group.trim() || "Other";
      const list = m.get(g) ?? [];
      list.push(t);
      m.set(g, list);
    }
    return Array.from(m.entries());
  }, [trips]);

  const groupNames = useMemo(
    () => Array.from(new Set((trips ?? []).map((t) => t.group.trim()).filter(Boolean))).sort(),
    [trips]
  );

  async function move(t: PlannedTrip) {
    const key = `${t.folder}/${t.slug}`;
    setMoving(key);
    try {
      await movePlannedTrip({ folder: t.folder, slug: t.slug, group: (groupDraft[key] ?? "").trim() });
      await refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setMoving(null);
    }
  }

  if (trips === null) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      {error && <p className="break-words text-xs text-danger">{error}</p>}

      {trips.length === 0 ? (
        <EmptyState icon={CalendarDays}>
          No planned trips yet — drop an itinerary or flight ticket and file it under Fun/Travel/Planned.
        </EmptyState>
      ) : (
        <>
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">Upcoming</p>
          {groups.map(([g, items]) => (
            <Panel key={g} title={g} icon={MapIcon} bodyClassName="space-y-2">
              {items.map((t) => {
                const dates = dateRange(t.start, t.end);
                return (
                  <Link
                    key={`${t.folder}/${t.slug}`}
                    href={kbLink(t.folder, t.slug)}
                    className="block rounded-lg border border-line bg-surface-2/60 p-3 transition-colors hover:border-accent/60"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="min-w-0 break-words text-sm font-medium">{t.title}</span>
                      {t.status && <Badge tone={statusTone(t.status)}>{t.status}</Badge>}
                    </div>
                    {dates && <p className="mt-1 font-mono text-xs text-accent">{dates}</p>}
                    {t.destinations && <p className="mt-1 break-words text-xs text-muted">{t.destinations}</p>}
                  </Link>
                );
              })}
            </Panel>
          ))}
        </>
      )}

      {unsorted.length > 0 && (
        <Panel title="In Fun/Travel but not filed as planned" bodyClassName="space-y-3">
          <datalist id="travel-groups">
            {groupNames.map((g) => (
              <option key={g} value={g} />
            ))}
          </datalist>
          {unsorted.map((t) => {
            const key = `${t.folder}/${t.slug}`;
            const dates = dateRange(t.start, t.end);
            return (
              <div key={key} className="space-y-2 rounded-lg border border-line bg-surface-2/60 p-3">
                <div className="min-w-0">
                  <Link href={kbLink(t.folder, t.slug)} className="break-words text-sm font-medium hover:text-accent">
                    {t.title}
                  </Link>
                  {dates && <p className="font-mono text-xs text-muted">{dates}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    list="travel-groups"
                    placeholder="group (e.g. Europe)"
                    className="w-auto min-w-0 flex-1"
                    value={groupDraft[key] ?? ""}
                    onChange={(e) => setGroupDraft((d) => ({ ...d, [key]: e.target.value }))}
                  />
                  <Button size="sm" variant="primary" disabled={moving === key} onClick={() => move(t)}>
                    {moving === key ? "Moving…" : "Move to Planned"}
                  </Button>
                </div>
              </div>
            );
          })}
        </Panel>
      )}
    </div>
  );
}

function BucketTab() {
  const [places, setPlaces] = useState<BucketPlace[] | null>(null);
  const [place, setPlace] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() {
    try {
      setPlaces(await listBucketPlaces());
    } catch (e) {
      setPlaces([]);
      setMessage(errorText(e));
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, []);

  // Not-yet-visited first; stable otherwise (keeps the API's order).
  const sorted = useMemo(
    () => [...(places ?? [])].sort((a, b) => Number(a.visited) - Number(b.visited)),
    [places]
  );
  const visitedCount = (places ?? []).filter((p) => p.visited).length;

  async function add() {
    const name = place.trim();
    if (!name) return;
    setBusy(true);
    setMessage(null);
    try {
      await addBucketPlace({ place: name, notes: notes.trim() || undefined });
      setPlace("");
      setNotes("");
      await refresh();
    } catch (e) {
      const msg = errorText(e);
      setMessage(/ 409 /.test(msg) ? `${name} is already on your list.` : msg);
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: BucketPlace) {
    if (!window.confirm(`Remove ${p.place} from your bucket list?`)) return;
    try {
      await deleteBucketPlace(p.slug);
      await refresh();
    } catch (e) {
      setMessage(errorText(e));
    }
  }

  return (
    <div className="space-y-4">
      <Panel title="Add a place" icon={Plus} bodyClassName="space-y-2">
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <Input placeholder="place (e.g. Kyoto)" value={place} onChange={(e) => setPlace(e.target.value)} />
          <Input placeholder="notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <Button type="submit" size="sm" variant="primary" disabled={busy || !place.trim()}>
            {busy ? "Adding…" : "Add to bucket list"}
          </Button>
        </form>
        {message && <p className="break-words text-xs text-warn">{message}</p>}
      </Panel>

      {places === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : places.length === 0 ? (
        <EmptyState icon={Star}>Your bucket list is empty — add somewhere you want to go.</EmptyState>
      ) : (
        <Panel
          title="Bucket list"
          icon={Star}
          actions={
            <span className="font-mono text-[11px] text-muted">
              {places.length} place{places.length === 1 ? "" : "s"} · {visitedCount} visited
            </span>
          }
          bodyClassName="space-y-2"
        >
          {sorted.map((p) => (
            <div
              key={p.slug}
              className="flex items-start justify-between gap-2 rounded-lg border border-line bg-surface-2/60 p-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={kbLink(p.folder, p.slug)} className="break-words text-sm font-medium hover:text-accent">
                    {p.place}
                  </Link>
                  {p.visited && (
                    <Link href={`/travel?city=${encodeURIComponent(p.place)}`}>
                      <Badge tone="ok" className="gap-1">
                        <CircleCheck size={11} />
                        Visited{p.visited_on ? ` ${formatIsoDate(p.visited_on)}` : ""}
                      </Badge>
                    </Link>
                  )}
                </div>
                {p.notes && <p className="mt-1 break-words text-xs text-muted">{p.notes}</p>}
              </div>
              <Button size="sm" variant="ghost" aria-label={`Remove ${p.place}`} onClick={() => remove(p)}>
                <Trash2 size={14} />
              </Button>
            </div>
          ))}
        </Panel>
      )}
    </div>
  );
}

function ExperiencesTab({ initialCity }: { initialCity: string | null }) {
  const [experiences, setExperiences] = useState<Experience[]>([]);
  const [city, setCity] = useState<string | null>(initialCity);
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
    <div className="space-y-6">
      <p className="text-sm opacity-60">
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
