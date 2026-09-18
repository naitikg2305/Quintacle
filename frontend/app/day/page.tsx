"use client";

import { useEffect, useMemo, useState } from "react";
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

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Calendar</h1>

      <div className="flex gap-2 text-sm">
        <button
          onClick={() => setTab("regular")}
          className={`px-3 py-1 rounded border ${tab === "regular" ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
        >
          Regular
        </button>
        <button
          onClick={() => setTab("action")}
          className={`px-3 py-1 rounded border ${tab === "action" ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
        >
          Action
        </button>
      </div>

      <div className="flex items-center justify-between">
        <button onClick={() => shiftMonth(-1)} className="text-sm underline">
          ← prev
        </button>
        <span className="font-medium">{monthLabel(monthCursor)}</span>
        <button onClick={() => shiftMonth(1)} className="text-sm underline">
          next →
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-xs opacity-60">
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
          return (
            <button
              key={dateStr}
              onClick={() => toggleExpanded(dateStr)}
              className={`border rounded p-2 text-sm text-left h-16 flex flex-col justify-between ${
                isExpanded ? "border-black dark:border-white" : "border-black/10 dark:border-white/10"
              }`}
            >
              <span>{dayNum}</span>
              {count > 0 && (
                <span className="text-xs opacity-70">
                  {count} {tab === "regular" ? "due" : "logged"}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {expandedDate && (
        <section className="border rounded p-4 space-y-3">
          <h2 className="font-medium">{expandedDate}</h2>

          {tab === "regular" && (
            <>
              {(todosByDate[expandedDate] ?? []).length === 0 && (
                <p className="text-sm opacity-60">Nothing due.</p>
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
              {!expandedDetail && <p className="text-sm opacity-60">Loading...</p>}
              {expandedDetail && (
                <>
                  {expandedDetail.journal && (
                    <div>
                      <h3 className="text-sm font-medium">Journal</h3>
                      <p className="text-sm opacity-80 whitespace-pre-wrap">{expandedDetail.journal}</p>
                    </div>
                  )}

                  {Object.entries(expandedActivitiesByCategory).map(([category, entries]) => (
                    <div key={category}>
                      <h3 className="text-sm font-medium capitalize">
                        {category} — {entries.reduce((sum, e) => sum + e.hours, 0)}h
                      </h3>
                      <ul className="text-sm list-disc list-inside opacity-80">
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
                      <h3 className="text-sm font-medium">
                        Food — {expandedDetail.food.totals.total_kcal ?? 0} kcal
                      </h3>
                      <ul className="text-sm list-disc list-inside opacity-80">
                        {(expandedDetail.food.entries as Array<Record<string, unknown>>).map((e, i) => (
                          <li key={i}>
                            {String(e.meal_name ?? e.notes ?? e.meal_type)} — {String(e.kcal)} kcal
                          </li>
                        ))}
                      </ul>

                      {expandedNutrition && (
                        <div className="mt-3 space-y-2">
                          <div className="grid grid-cols-5 gap-2 text-xs text-center border rounded p-2">
                            <div>
                              <div className="opacity-60">kcal</div>
                              <div className="font-medium">{expandedNutrition.macros.total_kcal}</div>
                            </div>
                            <div>
                              <div className="opacity-60">protein</div>
                              <div className="font-medium">{expandedNutrition.macros.total_protein_g}g</div>
                            </div>
                            <div>
                              <div className="opacity-60">carbs</div>
                              <div className="font-medium">{expandedNutrition.macros.total_carbs_g}g</div>
                            </div>
                            <div>
                              <div className="opacity-60">fat</div>
                              <div className="font-medium">{expandedNutrition.macros.total_fat_g}g</div>
                            </div>
                            <div>
                              <div className="opacity-60">fiber</div>
                              <div className="font-medium">{expandedNutrition.macros.total_fiber_g}g</div>
                            </div>
                          </div>

                          <div className="grid grid-cols-3 gap-2 text-xs text-center border rounded p-2">
                            <div>
                              <div className="opacity-60">kcal in</div>
                              <div className="font-medium">{expandedNutrition.energy_balance.kcal_in}</div>
                            </div>
                            <div>
                              <div className="opacity-60">kcal burned</div>
                              <div className="font-medium">{expandedNutrition.energy_balance.kcal_burned}</div>
                            </div>
                            <div>
                              <div className="opacity-60">net</div>
                              <div className="font-medium">{expandedNutrition.energy_balance.net_kcal}</div>
                            </div>
                          </div>

                          <table className="w-full text-xs">
                            <tbody>
                              {expandedNutrition.micros.map((m) => (
                                <tr key={m.nutrient} className="border-b border-black/5 dark:border-white/5">
                                  <td className="py-1 pr-2">
                                    {m.nutrient}
                                    {m.is_limit ? " (limit)" : ""}
                                  </td>
                                  <td className="py-1 pr-2 text-right whitespace-nowrap opacity-70">
                                    {m.amount.toFixed(1)} {m.unit}
                                  </td>
                                  <td className="py-1 w-24">
                                    <div className="h-1.5 bg-black/10 dark:bg-white/10 rounded overflow-hidden">
                                      <div
                                        className={`h-full ${
                                          m.is_limit
                                            ? m.pct_of_rda > 100
                                              ? "bg-red-500"
                                              : "bg-black dark:bg-white"
                                            : "bg-black dark:bg-white"
                                        }`}
                                        style={{ width: `${Math.min(100, m.pct_of_rda)}%` }}
                                      />
                                    </div>
                                  </td>
                                  <td className="py-1 pl-2 text-right opacity-70 whitespace-nowrap">
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
                      <h3 className="text-sm font-medium">Exercise</h3>
                      <ul className="text-sm list-disc list-inside opacity-80">
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
                      <h3 className="text-sm font-medium">Substances</h3>
                      <ul className="text-sm list-disc list-inside opacity-80">
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
                      <h3 className="text-sm font-medium">Body Stats</h3>
                      <ul className="text-sm list-disc list-inside opacity-80">
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
                    !expandedDetail.journal && <p className="text-sm opacity-60">Nothing logged.</p>}
                </>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
