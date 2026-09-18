"use client";

import { useEffect, useState } from "react";
import ReadOnlyChat from "@/components/ReadOnlyChat";
import {
  createHabit,
  getNutritionHistory,
  getTargets,
  habitHistory,
  habitProgress,
  Habit,
  HabitHistoryPoint,
  HabitProgress,
  listHabits,
  NutritionHistoryPoint,
  Targets,
} from "@/lib/api";

const CATEGORIES = ["productivity", "social", "leisure", "yourself", "emotional"];
const PERIODS = ["day", "week", "2weeks", "month"];

type GoalType = "time" | "amount_cap";
type Row = { habit: Habit; progress: HabitProgress; history: HabitHistoryPoint[] };

function Sparkline({ history, direction }: { history: HabitHistoryPoint[]; direction: string }) {
  const w = 24;
  const gap = 3;
  const h = 28;
  return (
    <svg width={history.length * (w + gap)} height={h} className="shrink-0">
      {history.map((p, i) => {
        const pct = p.target > 0 ? Math.min(1, p.current / p.target) : 0;
        const barH = Math.max(2, pct * h);
        const good = direction === "at_most" ? p.met : p.met;
        return (
          <rect
            key={i}
            x={i * (w + gap)}
            y={h - barH}
            width={w}
            height={barH}
            rx={2}
            className={good ? "fill-black dark:fill-white" : "fill-black/25 dark:fill-white/25"}
          />
        );
      })}
    </svg>
  );
}

function TrendBars({
  values,
  target,
  direction,
}: {
  values: number[];
  target: number;
  direction: "at_least" | "at_most";
}) {
  const w = 24;
  const gap = 3;
  const h = 28;
  const max = Math.max(target, ...values, 1);
  return (
    <svg width={values.length * (w + gap)} height={h} className="shrink-0">
      {values.map((v, i) => {
        const barH = Math.max(2, (v / max) * h);
        const met = direction === "at_most" ? v <= target : v >= target;
        return (
          <rect
            key={i}
            x={i * (w + gap)}
            y={h - barH}
            width={w}
            height={barH}
            rx={2}
            className={met ? "fill-black dark:fill-white" : "fill-black/25 dark:fill-white/25"}
          />
        );
      })}
    </svg>
  );
}

export default function HabitsPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [nutritionHistory, setNutritionHistory] = useState<NutritionHistoryPoint[]>([]);
  const [targets, setTargets] = useState<Targets | null>(null);
  const [goalType, setGoalType] = useState<GoalType>("time");
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [period, setPeriod] = useState("week");
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [status, setStatus] = useState<string | null>(null);

  async function refresh() {
    const habits = await listHabits();
    const withData = await Promise.all(
      habits.map(async (habit) => ({
        habit,
        progress: await habitProgress(habit.id),
        history: await habitHistory(habit.id, 8),
      }))
    );
    setRows(withData);
    setNutritionHistory(await getNutritionHistory(8));
    setTargets(await getTargets());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function submit() {
    if (!name || !target) return;
    setStatus("saving...");
    await createHabit(
      goalType === "time"
        ? {
            name,
            target_amount: Number(target),
            target_period: period,
            match_category: category,
            unit: "hrs",
            metric: "activity_hours",
            direction: "at_least",
          }
        : {
            name,
            target_amount: Number(target),
            target_period: period,
            match_category: null,
            unit: "kcal",
            metric: "food_kcal",
            direction: "at_most",
          }
    );
    setName("");
    setTarget("");
    setStatus("goal added");
    await refresh();
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="text-sm opacity-60 -mt-4">Goals vs. actuals, with trend — finance rows slot in here once phase 3 lands.</p>

      <ReadOnlyChat />

      {targets && "error" in targets && (
        <p className="text-sm opacity-60 border rounded p-3">
          {targets.error} — set up your <a href="/profile" className="underline">Profile</a> to see personalized kcal/protein targets here.
        </p>
      )}

      {targets && !("error" in targets) && nutritionHistory.length > 0 && (
        <div className="space-y-3">
          <div className="border rounded p-4 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="font-medium">Calories</span>
              <span>target ~{targets.tdee_kcal} kcal/day (TDEE)</span>
            </div>
            <div className="flex items-center gap-2">
              <TrendBars values={nutritionHistory.map((h) => h.kcal)} target={targets.tdee_kcal} direction="at_most" />
              <span className="text-xs opacity-50">last {nutritionHistory.length} days</span>
            </div>
          </div>
          <div className="border rounded p-4 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="font-medium">Protein</span>
              <span>target {targets.protein_target_g}g/day</span>
            </div>
            <div className="flex items-center gap-2">
              <TrendBars
                values={nutritionHistory.map((h) => h.protein_g)}
                target={targets.protein_target_g}
                direction="at_least"
              />
              <span className="text-xs opacity-50">last {nutritionHistory.length} days</span>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {rows.length === 0 && <p className="opacity-60 text-sm">No goals set yet.</p>}
        {rows.map(({ habit, progress: p, history }) => {
          const pct = Math.min(100, (p.current / p.target) * 100);
          return (
            <div key={habit.id} className="border rounded p-4 space-y-3">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="font-medium">{p.habit}</span>
                  <span>
                    {p.current} {p.direction === "at_most" ? "of" : "/"} {p.target} {p.unit}{" "}
                    {p.direction === "at_most" ? "cap" : ""} per {p.target_period}
                    {p.met ? " ✓" : ""}
                  </span>
                </div>
                <div className="h-2 bg-black/10 dark:bg-white/10 rounded overflow-hidden">
                  <div className="h-full bg-black dark:bg-white" style={{ width: `${pct}%` }} />
                </div>
              </div>
              {history.length > 0 && (
                <div className="flex items-center gap-2">
                  <Sparkline history={history} direction={p.direction} />
                  <span className="text-xs opacity-50">last {history.length} {p.target_period}s</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="border rounded p-4 space-y-3">
        <h2 className="font-medium">Add a goal</h2>
        <div className="flex gap-3 text-sm">
          <label className="flex items-center gap-1">
            <input
              type="radio"
              checked={goalType === "time"}
              onChange={() => setGoalType("time")}
            />
            Time-based (hours)
          </label>
          <label className="flex items-center gap-1">
            <input
              type="radio"
              checked={goalType === "amount_cap"}
              onChange={() => setGoalType("amount_cap")}
            />
            Amount cap (kcal)
          </label>
        </div>
        <input
          className="border rounded px-2 py-1 w-full text-sm"
          placeholder={goalType === "time" ? "e.g. Golf" : "e.g. Daily calorie cap"}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="flex gap-3">
          <input
            type="number"
            className="border rounded px-2 py-1 w-28 text-sm"
            placeholder={goalType === "time" ? "hours" : "kcal"}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
          <select className="border rounded px-2 py-1 text-sm" value={period} onChange={(e) => setPeriod(e.target.value)}>
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                per {p}
              </option>
            ))}
          </select>
          {goalType === "time" && (
            <select
              className="border rounded px-2 py-1 text-sm"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          )}
        </div>
        <button
          onClick={submit}
          className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm"
        >
          Add goal
        </button>
        {status && <p className="text-sm opacity-70">{status}</p>}
      </div>
    </div>
  );
}
