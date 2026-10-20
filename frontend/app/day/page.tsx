"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CalendarDays, ChevronLeft, ChevronRight, CircleCheck, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge, PageHeader, Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { cn } from "@/lib/cn";
import {
  DayDetail,
  formatSets,
  getDayCounts,
  getDayDetail,
  getHabitsLedger,
  getNutritionForDate,
  HabitsLedger,
  kbAssetUrl,
  LedgerCell,
  LedgerHabit,
  listTodos,
  NutritionForDate,
  Todo,
} from "@/lib/api";
import { addDaysIso, calendarIso, currentMonthStart, mondayOfWeek, todayIso } from "@/lib/date";

type Tab = "regular" | "action" | "habits";

// Status is never color alone (same convention as the habits page's
// GoalStatus): a word — and an icon on settled states — rides with the tone.
function CellStatus({ cell, direction }: { cell: LedgerCell; direction: LedgerHabit["direction"] }) {
  if (cell.in_progress) return <Badge tone="muted">in progress</Badge>;
  if (cell.met)
    return (
      <Badge tone="ok">
        <CircleCheck size={11} className="mr-1" /> {direction === "at_most" ? "under cap" : "met"}
      </Badge>
    );
  return (
    <Badge tone="danger">
      <TriangleAlert size={11} className="mr-1" /> {direction === "at_most" ? "over cap" : "missed"}
    </Badge>
  );
}

function cellNumbers(cell: LedgerCell, habit: LedgerHabit): string {
  // Formatting only — every number here was computed by the backend.
  if (cell.days_total !== undefined) return `${cell.days_met}/${cell.days_total} days`;
  return `${cell.actual} / ${cell.target} ${habit.unit}`;
}

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];

function firstImageAsset(assets: string[]): string | undefined {
  return assets.find((a) => IMAGE_EXT.includes(a.split(".").pop()?.toLowerCase() ?? ""));
}

function monthLabel(d: Date): string {
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function DayViewPage() {
  const [monthCursor, setMonthCursor] = useState(currentMonthStart);
  const [tab, setTab] = useState<Tab>("regular");
  const [todos, setTodos] = useState<Todo[]>([]);
  const [actionCounts, setActionCounts] = useState<Record<string, number>>({});
  const [expandedDate, setExpandedDate] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<DayDetail | null>(null);
  const [expandedNutrition, setExpandedNutrition] = useState<NutritionForDate | null>(null);
  const [ledger, setLedger] = useState<HabitsLedger | null>(null);

  const monthStart = useMemo(
    () => new Date(monthCursor.getFullYear(), monthCursor.getMonth(), 1),
    [monthCursor]
  );
  const monthEnd = useMemo(
    () => new Date(monthCursor.getFullYear(), monthCursor.getMonth() + 1, 0),
    [monthCursor]
  );

  useEffect(() => {
    listTodos().then(setTodos);
    getDayCounts(calendarIso(monthStart), calendarIso(monthEnd)).then(setActionCounts);
    setExpandedDate(null);
    setExpandedDetail(null);
  }, [monthStart, monthEnd]);

  useEffect(() => {
    if (tab !== "habits") return;
    // One ledger call sized to reach back past the visible month: weeks
    // between today's Monday and the month's first Monday, plus slack. The
    // backend owns all habit arithmetic; this is only a request size.
    const diffWeeks = Math.round(
      (Date.parse(mondayOfWeek(todayIso())) - Date.parse(mondayOfWeek(calendarIso(monthStart)))) / (7 * 86400000)
    );
    getHabitsLedger(Math.max(2, diffWeeks + 6)).then(setLedger);
  }, [tab, monthStart]);

  const todosByDate = useMemo(() => {
    const map: Record<string, Todo[]> = {};
    for (const t of todos) {
      if (!t.due_date) continue;
      (map[t.due_date] ??= []).push(t);
    }
    return map;
  }, [todos]);

  const cells: (string | null)[] = [];
  for (let i = 0; i < monthStart.getDay(); i++) cells.push(null);
  for (let day = 1; day <= monthEnd.getDate(); day++) {
    cells.push(calendarIso(new Date(monthCursor.getFullYear(), monthCursor.getMonth(), day)));
  }

  function countFor(dateStr: string): number {
    return tab === "regular" ? (todosByDate[dateStr]?.length ?? 0) : (actionCounts[dateStr] ?? 0);
  }

  function shiftMonth(delta: number) {
    setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() + delta, 1));
  }

  function toggleExpanded(dateStr: string) {
    if (expandedDate === dateStr) {
      setExpandedDate(null);
      setExpandedDetail(null);
      setExpandedNutrition(null);
      return;
    }
    setExpandedDate(dateStr);
    setExpandedDetail(null);
    setExpandedNutrition(null);
    if (tab === "habits") return; // a week row — the ledger is already loaded
    getDayDetail(dateStr).then(setExpandedDetail);
    getNutritionForDate(dateStr).then(setExpandedNutrition);
  }

  function switchTab(next: Tab) {
    setTab(next);
    setExpandedDate(null);
    setExpandedDetail(null);
    setExpandedNutrition(null);
  }

  // Monday-anchored weeks overlapping the visible month, each mapped to its
  // column in the ledger (null = a week the ledger doesn't cover, i.e. future).
  const weekRows = useMemo(() => {
    if (!ledger) return [];
    const monthEndIso = calendarIso(monthEnd);
    const idxByStart = new Map(ledger.weeks.map((w, i) => [w.start, i]));
    const rows: { start: string; end: string; idx: number | null }[] = [];
    for (let ws = mondayOfWeek(calendarIso(monthStart)); ws <= monthEndIso; ws = addDaysIso(ws, 7)) {
      rows.push({ start: ws, end: addDaysIso(ws, 6), idx: idxByStart.get(ws) ?? null });
    }
    return rows;
  }, [ledger, monthStart, monthEnd]);

  const currentWeekStart = ledger?.weeks[ledger.weeks.length - 1]?.start;

  const expandedActivitiesByCategory = useMemo(() => {
    if (!expandedDetail) return {};
    const grouped: Record<string, DayDetail["activities"]> = {};
    for (const a of expandedDetail.activities) {
      (grouped[a.category] ??= []).push(a);
    }
    return grouped;
  }, [expandedDetail]);

  const today = todayIso();
  const heat = (n: number) => (n <= 0 ? "" : n === 1 ? "bg-accent/[0.07]" : n <= 3 ? "bg-accent/15" : "bg-accent/25");

  const detail = expandedDate ? (
    <div className="space-y-3">

    {tab === "habits" && ledger && (
      <>
        {(() => {
          const idx = weekRows.find((w) => w.start === expandedDate)?.idx ?? null;
          if (idx === null) return <p className="text-sm text-muted">No habit data for this week yet.</p>;
          const rows = ledger.habits
            .map((h) => ({ habit: h, cell: h.cells[idx] }))
            .filter((r) => r.cell?.active);
          if (rows.length === 0) return <p className="text-sm text-muted">No habits were active this week.</p>;
          return (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
                  <th className="py-1 pr-2 font-normal">Habit</th>
                  <th className="py-1 pr-2 font-normal">Target in force</th>
                  <th className="py-1 pr-2 font-normal">Actual</th>
                  <th className="py-1 font-normal">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ habit, cell }) => {
                  // A target that isn't the habit's current one gets its
                  // effective date shown — the week was judged under it.
                  const currentCell = currentWeekStart ? habit.cells[ledger.weeks.length - 1] : undefined;
                  const oldVersion = currentCell && cell.effective_from !== currentCell.effective_from;
                  return (
                    <tr key={habit.id} className="border-t border-line align-top">
                      <td className="py-1.5 pr-2">{habit.name}</td>
                      <td className="py-1.5 pr-2">
                        <span className="font-mono">
                          {habit.direction === "at_most" ? "≤" : "≥"} {cell.target} {habit.unit}
                        </span>
                        {cell.days_total !== undefined && <span className="text-muted"> /day</span>}
                        {cell.window.start !== expandedDate && (
                          <p className="text-xs text-muted">
                            {cell.window.start} → {cell.window.end}
                          </p>
                        )}
                        {oldVersion && cell.effective_from && (
                          <p className="text-xs text-muted">in force since {cell.effective_from}</p>
                        )}
                      </td>
                      <td className="py-1.5 pr-2 font-mono">{cellNumbers(cell, habit)}</td>
                      <td className="py-1.5">
                        <CellStatus cell={cell} direction={habit.direction} />
                        {cell.in_progress && cell.prorated_target !== null && (
                          <p className="mt-1 text-xs text-muted">
                            pace: <span className="font-mono text-foreground">{cell.actual}</span> vs{" "}
                            <span className="font-mono text-foreground">{cell.prorated_target}</span> by day{" "}
                            {cell.elapsed_days}/{cell.period_days}
                          </p>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          );
        })()}
      </>
    )}

    {tab === "regular" && (
      <>
        {(todosByDate[expandedDate] ?? []).length === 0 && (
          <p className="text-sm text-muted">Nothing due.</p>
        )}
        <ul className="text-sm space-y-1">
          {(todosByDate[expandedDate] ?? []).map((t) => (
            <li key={t.id}>
              {t.title}
              {t.start_time ? ` ${t.start_time}${t.end_time ? `–${t.end_time}` : ""}` : ""} (priority {t.priority})
              {t.done ? " ✓" : ""}
            </li>
          ))}
        </ul>
      </>
    )}

    {tab === "action" && (
      <>
        {!expandedDetail && <p className="text-sm text-muted">Loading...</p>}
        {expandedDetail && (
          <>
            {expandedDetail.journal && (
              <div>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">Journal</h3>
                <p className="text-sm text-foreground/80 whitespace-pre-wrap">{expandedDetail.journal}</p>
              </div>
            )}

            {expandedDetail.todos_completed.length > 0 && (
              <div>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">Completed</h3>
                <ul className="text-sm space-y-0.5 text-foreground/80">
                  {expandedDetail.todos_completed.map((t) => (
                    <li key={t.id} className="flex items-center gap-2">
                      <span className="text-accent">✓</span>
                      <span>{t.title}</span>
                      {t.category && (
                        <span className="rounded border border-line px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted">
                          {t.category}
                        </span>
                      )}
                      {t.completed_at && (
                        <span className="ml-auto font-mono text-[11px] text-muted">
                          {new Date(t.completed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {Object.entries(expandedActivitiesByCategory).map(([category, entries]) => (
              <div key={category}>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">
                  {category} — {entries.reduce((sum, e) => sum + e.hours, 0)}h
                </h3>
                <ul className="text-sm list-disc list-inside text-foreground/80">
                  {entries.map((e) => (
                    <li key={e.id}>
                      {e.description} ({e.hours}h)
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            {expandedDetail.food.entries.length > 0 && (
              <div>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">
                  Food — {expandedDetail.food.totals.total_kcal ?? 0} kcal
                </h3>
                <ul className="text-sm list-disc list-inside text-foreground/80">
                  {(expandedDetail.food.entries as Array<Record<string, unknown>>).map((e, i) => (
                    <li key={i}>
                      {String(e.meal_name ?? e.notes ?? e.meal_type)} — {String(e.kcal)} kcal
                    </li>
                  ))}
                </ul>

                {expandedNutrition && (
                  <div className="mt-3 space-y-2">
                    <div className="grid grid-cols-5 gap-2 text-xs text-center rounded-lg border border-line bg-surface-2/50 p-2">
                      <div>
                        <div className="text-muted">kcal</div>
                        <div className="font-medium">{expandedNutrition.macros.total_kcal}</div>
                      </div>
                      <div>
                        <div className="text-muted">protein</div>
                        <div className="font-medium">{expandedNutrition.macros.total_protein_g}g</div>
                      </div>
                      <div>
                        <div className="text-muted">carbs</div>
                        <div className="font-medium">{expandedNutrition.macros.total_carbs_g}g</div>
                      </div>
                      <div>
                        <div className="text-muted">fat</div>
                        <div className="font-medium">{expandedNutrition.macros.total_fat_g}g</div>
                      </div>
                      <div>
                        <div className="text-muted">fiber</div>
                        <div className="font-medium">{expandedNutrition.macros.total_fiber_g}g</div>
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-xs text-center rounded-lg border border-line bg-surface-2/50 p-2">
                      <div>
                        <div className="text-muted">kcal in</div>
                        <div className="font-medium">{expandedNutrition.energy_balance.kcal_in}</div>
                      </div>
                      <div>
                        <div className="text-muted">kcal burned</div>
                        <div className="font-medium">{expandedNutrition.energy_balance.kcal_burned}</div>
                      </div>
                      <div>
                        <div className="text-muted">net</div>
                        <div className="font-medium">{expandedNutrition.energy_balance.net_kcal}</div>
                      </div>
                    </div>

                    <table className="w-full text-xs">
                      <tbody>
                        {expandedNutrition.micros.map((m) => (
                          <tr key={m.nutrient} className="border-b border-line">
                            <td className="py-1 pr-2">
                              {m.nutrient}
                              {m.is_limit ? " (limit)" : ""}
                            </td>
                            <td className="py-1 pr-2 text-right whitespace-nowrap text-muted">
                              {m.amount.toFixed(1)} {m.unit}
                            </td>
                            <td className="py-1 w-24">
                              <div className="h-1.5 bg-white/10 rounded overflow-hidden">
                                <div
                                  className={`h-full ${
                                    m.is_limit
                                      ? m.pct_of_rda > 100
                                        ? "bg-danger"
                                        : "bg-accent"
                                      : "bg-accent"
                                  }`}
                                  style={{ width: `${Math.min(100, m.pct_of_rda)}%` }}
                                />
                              </div>
                            </td>
                            <td className="py-1 pl-2 text-right text-muted whitespace-nowrap">
                              {m.pct_of_rda.toFixed(0)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {expandedDetail.exercise.length > 0 && (
              <div>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">Exercise</h3>
                <ul className="text-sm list-disc list-inside text-foreground/80">
                  {expandedDetail.exercise.map((e) => (
                    <li key={e.id}>
                      {e.exercise_name}: {formatSets(e.sets) || e.performance_text}
                      {e.notes ? ` — ${e.notes}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {expandedDetail.substances.length > 0 && (
              <div>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">Substances</h3>
                <ul className="text-sm list-disc list-inside text-foreground/80">
                  {(expandedDetail.substances as Array<Record<string, unknown>>).map((s, i) => (
                    <li key={i}>
                      {String(s.substance)}: {String(s.amount)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {expandedDetail.body_stats.length > 0 && (
              <div>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">Body Stats</h3>
                <ul className="text-sm list-disc list-inside text-foreground/80">
                  {(expandedDetail.body_stats as Array<Record<string, unknown>>).map((b, i) => (
                    <li key={i}>
                      {String(b.metric)}: {String(b.value)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {expandedDetail.photos.length > 0 && (
              <div>
                <h3 className="mb-1 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-accent">Photos</h3>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {expandedDetail.photos.map((p) => {
                    const thumb = firstImageAsset(p.assets);
                    return (
                      <Link
                        key={`${p.folder}/${p.slug}`}
                        href={`/kb/browse?path=${encodeURIComponent(p.folder)}&open=${encodeURIComponent(p.slug)}`}
                        className="w-24 shrink-0 space-y-1"
                        title={p.title}
                      >
                        {thumb ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={kbAssetUrl(p.folder, thumb)}
                            alt={p.title}
                            className="h-24 w-24 rounded-lg border border-line object-cover"
                          />
                        ) : (
                          <div className="flex h-24 w-24 items-center justify-center rounded-lg border border-line bg-surface-2/50 p-2 text-center text-[10px] text-muted">
                            {p.title}
                          </div>
                        )}
                        <p className="truncate text-xs text-foreground/80">{p.title}</p>
                      </Link>
                    );
                  })}
                </div>
              </div>
            )}

            {Object.keys(expandedActivitiesByCategory).length === 0 &&
              expandedDetail.food.entries.length === 0 &&
              expandedDetail.exercise.length === 0 &&
              expandedDetail.substances.length === 0 &&
              expandedDetail.body_stats.length === 0 &&
              expandedDetail.todos_completed.length === 0 &&
              expandedDetail.photos.length === 0 &&
              !expandedDetail.journal && <p className="text-sm text-muted">Nothing logged.</p>}
          </>
        )}
      </>
    )}
    </div>
  ) : null;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageHeader
        title="Calendar"
        icon={CalendarDays}
        actions={
          <Segmented
            value={tab}
            onChange={switchTab}
            options={[
              { value: "regular", label: "Regular" },
              { value: "action", label: "Action" },
              { value: "habits", label: "Habits" },
            ]}
          />
        }
      />

      <div className="flex items-center justify-between">
        <Button size="sm" onClick={() => shiftMonth(-1)} aria-label="Previous month">
          <ChevronLeft size={16} />
        </Button>
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm uppercase tracking-[0.14em] text-accent">{monthLabel(monthCursor)}</span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setMonthCursor(currentMonthStart())}
          >
            Today
          </Button>
        </div>
        <Button size="sm" onClick={() => shiftMonth(1)} aria-label="Next month">
          <ChevronRight size={16} />
        </Button>
      </div>

      {/* Habits view: one row per Monday-anchored week overlapping the month —
          goals render like recurring weekly meetings (next-wave-plan §8). */}
      {tab === "habits" && (
        <div className="space-y-1.5">
          {!ledger && <p className="text-sm text-muted">Loading...</p>}
          {ledger && ledger.habits.length === 0 && <p className="text-sm text-muted">No habits yet.</p>}
          {ledger &&
            ledger.habits.length > 0 &&
            weekRows.map(({ start, end, idx }) => {
              const isExpanded = expandedDate === start;
              const isCurrent = start === currentWeekStart;
              return (
                <button
                  key={start}
                  onClick={() => toggleExpanded(start)}
                  aria-label={`Week of ${start}`}
                  className={cn(
                    "flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border p-2 text-left transition-colors",
                    isExpanded ? "border-accent shadow-glow" : isCurrent ? "border-accent/60" : "border-line hover:border-accent/40"
                  )}
                >
                  <span className={cn("shrink-0 font-mono text-xs", isCurrent ? "text-accent" : "text-muted")}>
                    {start.slice(5)} → {end.slice(5)}
                  </span>
                  {idx === null ? (
                    <span className="text-xs text-muted">upcoming</span>
                  ) : (
                    <span className="flex flex-wrap items-center gap-1.5">
                      {ledger.habits
                        .filter((h) => h.cells[idx]?.active)
                        .map((h) => (
                          <span key={h.id} className="inline-flex items-center gap-1 text-xs text-foreground/80">
                            {h.name}
                            <CellStatus cell={h.cells[idx]} direction={h.direction} />
                          </span>
                        ))}
                    </span>
                  )}
                </button>
              );
            })}
        </div>
      )}

      {tab !== "habits" && (
      <div>
        <div className="mb-1 grid grid-cols-7 gap-1 text-center font-mono text-[10px] uppercase tracking-wider text-muted">
          {WEEKDAYS.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>

        <div className="grid grid-cols-7 gap-1">
          {cells.map((dateStr, i) => {
            if (!dateStr) return <div key={i} />;
            const count = countFor(dateStr);
            const dayNum = Number(dateStr.slice(-2));
            const isExpanded = expandedDate === dateStr;
            const isToday = dateStr === today;
            return (
              <button
                key={dateStr}
                onClick={() => toggleExpanded(dateStr)}
                aria-label={`${dateStr}${count > 0 ? `, ${count} ${tab === "regular" ? "due" : "logged"}` : ""}`}
                className={cn(
                  "flex h-14 flex-col justify-between rounded-lg border p-1.5 text-left transition-colors sm:h-16 sm:p-2",
                  heat(count),
                  isExpanded ? "border-accent shadow-glow" : isToday ? "border-accent/60" : "border-line hover:border-accent/40"
                )}
              >
                <span className={cn("font-mono text-sm", isToday ? "text-accent" : "text-foreground/80")}>{dayNum}</span>
                {count > 0 && (
                  <span className="font-mono text-[10px] text-accent">
                    {count}
                    <span className="hidden sm:inline"> {tab === "regular" ? "due" : "logged"}</span>
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
      )}

      {/* Desktop: the day (or habits week) opens inline under the grid */}
      {expandedDate && (
        <div className="hidden md:block">
          <Panel title={tab === "habits" ? `Week of ${expandedDate}` : expandedDate}>{detail}</Panel>
        </div>
      )}

      {/* Phone: the same detail as a bottom sheet */}
      <div className="md:hidden">
        <BottomSheet
          open={!!expandedDate}
          onClose={() => toggleExpanded(expandedDate as string)}
          title={expandedDate ? (tab === "habits" ? `Week of ${expandedDate}` : expandedDate) : ""}
        >
          {detail}
        </BottomSheet>
      </div>
    </div>
  );
}
