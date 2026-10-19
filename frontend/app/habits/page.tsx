"use client";

import { useEffect, useState } from "react";
import ReadOnlyChat from "@/components/ReadOnlyChat";
import Link from "next/link";
import { ChevronDown, ChevronUp, CircleCheck, LayoutDashboard, MessageSquare, Plus, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Field";
import { Badge, PageHeader, Panel, Stat } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { cn } from "@/lib/cn";
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
const EXPENSE_KINDS = ["subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"];

type GoalType = "time" | "amount_cap" | "budget";
type Row = { habit: Habit; progress: HabitProgress; history: HabitHistoryPoint[] };

// One accent for "target met", a quiet neutral for "not yet" — the mark carries
// the state, and every bar has a native hover tooltip with the real numbers.
function Bars({ bars, height = 30 }: { bars: { value: number; met: boolean; label: string }[]; height?: number }) {
  const w = 22;
  const gap = 3;
  const max = Math.max(...bars.map((b) => b.value), 1);
  return (
    <svg width={bars.length * (w + gap)} height={height} className="shrink-0" role="img">
      {bars.map((b, i) => {
        const barH = Math.max(3, (b.value / max) * height);
        return (
          <rect
            key={i}
            x={i * (w + gap)}
            y={height - barH}
            width={w}
            height={barH}
            rx={3}
            className={b.met ? "fill-accent" : "fill-muted/40"}
          >
            <title>{b.label}</title>
          </rect>
        );
      })}
    </svg>
  );
}

function Sparkline({ history }: { history: HabitHistoryPoint[] }) {
  return (
    <Bars
      bars={history.map((p) => ({
        // Height = progress toward that period's own target (capped at full).
        value: p.target > 0 ? Math.min(1, p.current / p.target) : 0,
        met: p.met,
        label: `${p.window.start} → ${p.window.end}: ${p.current} / ${p.target}${p.met ? " ✓" : ""}`,
      }))}
    />
  );
}

function TrendBars({
  values,
  dates,
  target,
  direction,
  unit,
}: {
  values: number[];
  dates: string[];
  target: number;
  direction: "at_least" | "at_most";
  unit: string;
}) {
  return (
    <Bars
      bars={values.map((v, i) => ({
        value: v,
        met: direction === "at_most" ? v <= target : v >= target,
        label: `${dates[i]}: ${Math.round(v)} ${unit} (target ${direction === "at_most" ? "≤" : "≥"} ${Math.round(target)})`,
      }))}
    />
  );
}

// Status is never color alone: an icon and a word ride with it.
function GoalStatus({ p }: { p: HabitProgress }) {
  const over = p.direction === "at_most" && p.current > p.target;
  if (over)
    return (
      <Badge tone="danger">
        <TriangleAlert size={11} className="mr-1" /> over cap
      </Badge>
    );
  if (p.met)
    return (
      <Badge tone="ok">
        <CircleCheck size={11} className="mr-1" /> {p.direction === "at_most" ? "under cap" : "met"}
      </Badge>
    );
  return <Badge tone="muted">in progress</Badge>;
}

function meterColor(p: HabitProgress, pct: number): string {
  if (p.direction === "at_most") return pct > 100 ? "bg-danger" : pct > 85 ? "bg-warn" : "bg-accent";
  return p.met ? "bg-ok" : "bg-accent";
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
  // Budget-line matcher (metric=spend): an expense kind and/or comma-separated
  // whole-word terms over merchant/category/notes — both blank = total spend.
  const [budgetKind, setBudgetKind] = useState("");
  const [budgetTerms, setBudgetTerms] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [askOpen, setAskOpen] = useState(false);

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
        : goalType === "amount_cap"
          ? {
              name,
              target_amount: Number(target),
              target_period: period,
              match_category: null,
              unit: "kcal",
              metric: "food_kcal",
              direction: "at_most",
            }
          : {
              // Named budget line: the quota engine's spend metric with the
              // kind/text matcher; blank matcher = total spend, the original quota.
              name,
              target_amount: Number(target),
              target_period: period,
              match_category: budgetTerms.trim() || null,
              match_kind: budgetKind || null,
              unit: "$",
              metric: "spend",
              direction: "at_most",
            }
    );
    setName("");
    setTarget("");
    setBudgetKind("");
    setBudgetTerms("");
    setStatus("goal added");
    await refresh();
  }

  const onTrack = rows.filter((r) => r.progress.met).length;
  const mono = "font-mono text-[10px] uppercase tracking-[0.14em] text-muted";

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <PageHeader title="Dashboard" icon={LayoutDashboard} subtitle="Goals vs. actuals, with trend." />

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Goals" value={rows.length} />
        <Stat label="On track" value={onTrack} tone="ok" />
        <Stat label="Still going" value={rows.length - onTrack} tone={rows.length - onTrack > 0 ? "warn" : "ok"} />
      </div>

      <div>
        <button
          onClick={() => setAskOpen((v) => !v)}
          className="flex w-full items-center justify-between rounded-xl border border-line bg-surface/80 px-4 py-2.5 text-left transition-colors hover:border-accent/50"
        >
          <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
            <MessageSquare size={14} /> Ask about your data
          </span>
          {askOpen ? <ChevronUp size={16} className="text-muted" /> : <ChevronDown size={16} className="text-muted" />}
        </button>
        {askOpen && (
          <div className="mt-2">
            <ReadOnlyChat />
          </div>
        )}
      </div>

      {targets && "error" in targets && (
        <Panel>
          <p className="text-sm text-muted">
            {targets.error} — set up your{" "}
            <Link href="/profile" className="text-accent underline-offset-2 hover:underline">
              Profile
            </Link>{" "}
            to see personalized kcal/protein targets here.
          </p>
        </Panel>
      )}

      {targets && !("error" in targets) && nutritionHistory.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          <Panel title="Calories">
            <p className="text-sm text-muted">
              target <span className="font-mono text-foreground">~{targets.tdee_kcal}</span> kcal/day (TDEE)
            </p>
            <div className="mt-3 flex items-center gap-3">
              <TrendBars
                values={nutritionHistory.map((h) => h.kcal)}
                dates={nutritionHistory.map((h) => h.date)}
                target={targets.tdee_kcal}
                direction="at_most"
                unit="kcal"
              />
              <span className={mono}>last {nutritionHistory.length} days</span>
            </div>
          </Panel>
          <Panel title="Protein">
            <p className="text-sm text-muted">
              target <span className="font-mono text-foreground">{targets.protein_target_g}</span> g/day
            </p>
            <div className="mt-3 flex items-center gap-3">
              <TrendBars
                values={nutritionHistory.map((h) => h.protein_g)}
                dates={nutritionHistory.map((h) => h.date)}
                target={targets.protein_target_g}
                direction="at_least"
                unit="g"
              />
              <span className={mono}>last {nutritionHistory.length} days</span>
            </div>
          </Panel>
        </div>
      )}

      {rows.length === 0 && <p className="text-sm text-muted">No goals set yet.</p>}
      <div className="grid gap-3 md:grid-cols-2">
        {rows.map(({ habit, progress: p, history }) => {
          const pct = p.target > 0 ? (p.current / p.target) * 100 : 0;
          return (
            <Panel key={habit.id} bodyClassName="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-medium">{p.habit}</p>
                  <p className="text-xs text-muted">
                    <span className="font-mono text-foreground">{p.current}</span> {p.direction === "at_most" ? "of" : "/"}{" "}
                    <span className="font-mono text-foreground">{p.target}</span> {p.unit}
                    {p.direction === "at_most" ? " cap" : ""} per {p.target_period}
                  </p>
                </div>
                <GoalStatus p={p} />
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
                <div className={cn("h-full rounded-full", meterColor(p, pct))} style={{ width: `${Math.min(100, pct)}%` }} />
              </div>
              {p.metric === "spend" && p.direction === "at_most" && p.elapsed_days < p.period_days && (
                <p className="text-xs text-muted">
                  pace: <span className="font-mono text-foreground">{p.current.toFixed(2)}</span> vs{" "}
                  <span className="font-mono text-foreground">{p.prorated_target.toFixed(2)}</span> even-spend by day{" "}
                  {p.elapsed_days}/{p.period_days}
                  {p.current > p.prorated_target ? " — ahead of pace" : " — under pace"}
                </p>
              )}
              {history.length > 0 && (
                <div className="flex items-center gap-3">
                  <Sparkline history={history} />
                  <span className={mono}>
                    last {history.length} {p.target_period}s
                  </span>
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      <Panel title="Add a goal" bodyClassName="space-y-3">
        <Segmented
          value={goalType}
          onChange={setGoalType}
          options={[
            { value: "time", label: "Time-based (hours)" },
            { value: "amount_cap", label: "Amount cap (kcal)" },
            { value: "budget", label: "Budget line ($)" },
          ]}
        />
        <Input
          placeholder={goalType === "time" ? "e.g. Golf" : goalType === "amount_cap" ? "e.g. Daily calorie cap" : "e.g. Food budget, Winery weekend"}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          <Input
            type="number"
            className="w-28"
            placeholder={goalType === "time" ? "hours" : goalType === "amount_cap" ? "kcal" : "$"}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
          <Select className="w-auto" value={period} onChange={(e) => setPeriod(e.target.value)}>
            {PERIODS.map((pp) => (
              <option key={pp} value={pp}>
                per {pp}
              </option>
            ))}
          </Select>
          {goalType === "time" && (
            <Select className="w-auto" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          )}
          {goalType === "budget" && (
            <>
              <Select className="w-auto" value={budgetKind} onChange={(e) => setBudgetKind(e.target.value)}>
                <option value="">any kind</option>
                {EXPENSE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k.replace("_", " ")}
                  </option>
                ))}
              </Select>
              <Input
                className="w-56"
                placeholder="match words (e.g. winery, creatine)"
                title="Comma-separated whole words matched against merchant/category/notes; an expense counts if it matches the kind OR any word. Both blank = total spend."
                value={budgetTerms}
                onChange={(e) => setBudgetTerms(e.target.value)}
              />
            </>
          )}
        </div>
        {goalType === "budget" && (
          <p className="text-xs text-muted">
            Counts expenses matching the kind OR any listed word (whole-word, against merchant/category/notes). Leave both
            blank for a total-spend cap.
          </p>
        )}
        <Button variant="primary" onClick={submit} disabled={!name || !target}>
          <Plus size={16} /> Add goal
        </Button>
        {status && <p className="text-sm text-muted">{status}</p>}
      </Panel>
    </div>
  );
}
