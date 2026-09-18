"use client";

import { useEffect, useMemo, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { PageHeader, Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { cn } from "@/lib/cn";
import { DayDetail, formatSets, getDayCounts, getDayDetail, getNutritionForDate, listTodos, NutritionForDate, Todo } from "@/lib/api";

type Tab = "regular" | "action";

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function monthLabel(d: Date): string {
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function DayViewPage() {
  const [monthCursor, setMonthCursor] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [tab, setTab] = useState<Tab>("regular");
  const [todos, setTodos] = useState<Todo[]>([]);
  const [actionCounts, setActionCounts] = useState<Record<string, number>>({});
  const [expandedDate, setExpandedDate] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<DayDetail | null>(null);
  const [expandedNutrition, setExpandedNutrition] = useState<NutritionForDate | null>(null);

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
    getDayCounts(toISODate(monthStart), toISODate(monthEnd)).then(setActionCounts);
    setExpandedDate(null);
    setExpandedDetail(null);
  }, [monthStart, monthEnd]);

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
    cells.push(toISODate(new Date(monthCursor.getFullYear(), monthCursor.getMonth(), day)));
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
    getDayDetail(dateStr).then(setExpandedDetail);
    getNutritionForDate(dateStr).then(setExpandedNutrition);
  }

  const expandedActivitiesByCategory = useMemo(() => {
    if (!expandedDetail) return {};
    const grouped: Record<string, DayDetail["activities"]> = {};
    for (const a of expandedDetail.activities) {
      (grouped[a.category] ??= []).push(a);
    }
    return grouped;
  }, [expandedDetail]);

  const todayIso = toISODate(new Date());
  const heat = (n: number) => (n <= 0 ? "" : n === 1 ? "bg-accent/[0.07]" : n <= 3 ? "bg-accent/15" : "bg-accent/25");

  const detail = expandedDate ? (
    <div className="space-y-3">

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

            {Object.keys(expandedActivitiesByCategory).length === 0 &&
              expandedDetail.food.entries.length === 0 &&
              expandedDetail.exercise.length === 0 &&
              expandedDetail.substances.length === 0 &&
              expandedDetail.body_stats.length === 0 &&
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
            onChange={setTab}
            options={[
              { value: "regular", label: "Regular" },
              { value: "action", label: "Action" },
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
            onClick={() => {
              const now = new Date();
              setMonthCursor(new Date(now.getFullYear(), now.getMonth(), 1));
            }}
          >
            Today
          </Button>
        </div>
        <Button size="sm" onClick={() => shiftMonth(1)} aria-label="Next month">
          <ChevronRight size={16} />
        </Button>
      </div>

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
            const isToday = dateStr === todayIso;
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

      {/* Desktop: the day opens inline under the grid */}
      {expandedDate && (
        <div className="hidden md:block">
          <Panel title={expandedDate}>{detail}</Panel>
        </div>
      )}

      {/* Phone: the same detail as a bottom sheet */}
      <div className="md:hidden">
        <BottomSheet open={!!expandedDate} onClose={() => toggleExpanded(expandedDate as string)} title={expandedDate ?? ""}>
          {detail}
        </BottomSheet>
      </div>
    </div>
  );
}
