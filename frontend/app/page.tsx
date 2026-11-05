"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BookOpen,
  BookUser,
  CalendarDays,
  ChevronRight,
  Clock,
  Dumbbell,
  History,
  ImageIcon,
  ListChecks,
  Network,
  Scale,
  Target,
  User,
  Utensils,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import {
  activitiesInRange,
  ActivityEntry,
  BodyStat,
  DayDetail,
  Expense,
  getDayDetail,
  getJournal,
  getNutritionForDate,
  getRecent,
  getRecentGraph,
  getTargets,
  Habit,
  habitProgress,
  HabitProgress,
  listBodyStats,
  listExpenses,
  listHabits,
  listTodos,
  NutritionForDate,
  RecentGraph,
  RecentNode,
  Targets,
  Todo,
} from "@/lib/api";
import { EmptyState, Panel } from "@/components/ui/Panel";
import AssistPanel from "@/components/overview/AssistPanel";
import WeekGraph from "@/components/overview/WeekGraph";
import { Meter, OTHER, Ring, SERIES, Sparkline, StackedColumns } from "@/components/overview/charts";
import { nodeHref } from "@/components/overview/links";
import { addDaysIso, formatIsoDate, mondayOfWeek, TIME_ZONE, todayIso } from "@/lib/date";
import { cn } from "@/lib/cn";

// The dashboard (2026-11-05 redo of the 2026-11-03 overview): "/" is home —
// there's no Home tab any more. Widgets: Today, Goals this week,
// Productivity, Weight, Food + Spend, Connections, Recent, then the Assist +
// Capture column. Everything is computed in code from existing endpoints;
// one failing endpoint (soft()) blanks only its own widget.

type HabitRow = { habit: Habit; progress: HabitProgress };

type Data = {
  todos: Todo[] | null;
  habits: HabitRow[] | null;
  nutrition: NutritionForDate | null;
  targets: Targets | null;
  expenses: Expense[] | null;
  activities: ActivityEntry[] | null; // last Monday .. today (two weeks)
  journal: string | null | undefined;
  recent: RecentNode[] | null;
  graph: RecentGraph | null;
  weight: BodyStat[] | null;
  day: DayDetail | null;
  loaded: boolean; // after load, a null field means its endpoint failed
};

const EMPTY: Data = {
  todos: null,
  habits: null,
  nutrition: null,
  targets: null,
  expenses: null,
  activities: null,
  journal: undefined,
  recent: null,
  graph: null,
  weight: null,
  day: null,
  loaded: false,
};

const WEIGHT_DAYS = 60;

// One failing endpoint blanks its own tile, never the page.
const soft = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

function greeting(hour: number): string {
  if (hour < 5) return "Late night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 100 ? 2 : 0 })}`;
const r1 = (n: number) => Math.round(n * 10) / 10;

function onPace(p: HabitProgress): boolean {
  return p.direction === "at_most" ? p.current <= p.prorated_target : p.current >= p.prorated_target;
}

function fmtAmount(n: number, unit: string): string {
  if (unit === "$" || unit === "usd" || unit === "dollars") return money(n);
  return `${r1(n)}${unit ? ` ${unit}` : ""}`;
}

function relTime(iso: string, today: string): string {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  if (day === today) return new Date(iso).toLocaleTimeString(undefined, { timeZone: TIME_ZONE, hour: "numeric", minute: "2-digit" });
  if (day === addDaysIso(today, -1)) return "Yesterday";
  return formatIsoDate(day).replace(/, \d{4}$/, "");
}

function fmtTime(t: string): string {
  const [h, m] = t.split(":").map(Number);
  const suffix = h >= 12 ? "p" : "a";
  return `${((h + 11) % 12) + 1}${m ? `:${String(m).padStart(2, "0")}` : ""}${suffix}`;
}

const TYPE_LABEL: Record<string, string> = {
  note: "Note",
  journal_day: "Journal",
  todo: "Todo",
  expense: "Spend",
  activity: "Hours",
  person: "Person",
  experience: "Place",
  routine: "Routine",
  meal: "Meal",
};

const LB_PER_KG = 2.20462;
function toUnit(value: number, from: string, to: string): number {
  const f = from.toLowerCase();
  const t = to.toLowerCase();
  if (f === t) return value;
  if (f.startsWith("kg") && t.startsWith("lb")) return value * LB_PER_KG;
  if (f.startsWith("lb") && t.startsWith("kg")) return value / LB_PER_KG;
  return value;
}

const WEEKDAY = ["M", "T", "W", "T", "F", "S", "S"];

function WidgetLink({ href, children = "Open" }: { href: string; children?: string }) {
  return (
    <Link href={href} className="flex items-center gap-0.5 text-xs text-muted transition-colors hover:text-accent">
      {children}
      <ChevronRight size={13} />
    </Link>
  );
}

function Loading({ failed }: { failed?: boolean }) {
  return <p className="p-2 text-sm text-muted">{failed ? "Couldn't load this — is the backend up?" : "Loading…"}</p>;
}

type Row = { key: string; icon: LucideIcon; chip: string; chipTone: "danger" | "warn" | "accent" | "muted"; text: string; sub?: string; href: string };

// ---------------- widgets ----------------

function TodayWidget({ d, today }: { d: Data; today: string }) {
  const open = (d.todos ?? []).filter((t) => !t.done && t.due_date && t.due_date <= today);
  const sorted = [...open].sort((a, b) => {
    const ao = a.due_date! < today ? 0 : 1;
    const bo = b.due_date! < today ? 0 : 1;
    if (ao !== bo) return ao - bo;
    if ((a.start_time ?? "99") !== (b.start_time ?? "99")) return (a.start_time ?? "99") < (b.start_time ?? "99") ? -1 : 1;
    return b.priority - a.priority;
  });
  const shown = sorted.slice(0, 4);
  const rows: Row[] = shown.map((t) => {
    const overdue = t.due_date! < today;
    return {
      key: `t${t.id}`,
      icon: overdue ? AlertTriangle : ListChecks,
      chip: overdue ? "overdue" : t.start_time ? fmtTime(t.start_time) : "today",
      chipTone: overdue ? "danger" : t.start_time ? "accent" : "warn",
      text: t.title,
      sub: overdue ? `was due ${formatIsoDate(t.due_date!).replace(/, \d{4}$/, "")}` : t.category || undefined,
      href: "/todos",
    };
  });
  const day = d.day;
  if (day) {
    for (const a of day.activities) {
      rows.push({ key: `a${a.id}`, icon: Clock, chip: `${r1(a.hours)}h`, chipTone: "muted", text: a.description || a.category, sub: a.category, href: "/day" });
    }
    for (const e of day.exercise) {
      rows.push({ key: `e${e.id}`, icon: Dumbbell, chip: "gym", chipTone: "muted", text: e.exercise_name, sub: e.performance_text || undefined, href: "/day" });
    }
    if (day.photos.length) {
      rows.push({ key: "photos", icon: ImageIcon, chip: `${day.photos.length}`, chipTone: "muted", text: `${day.photos.length} photo${day.photos.length > 1 ? "s" : ""} from today`, href: "/day" });
    }
  }
  if (d.journal === null) rows.push({ key: "journal", icon: BookOpen, chip: "write", chipTone: "muted", text: "Nothing written for today yet", href: "/journal" });

  const chipCls = {
    danger: "border-danger/40 bg-danger/10 text-danger",
    warn: "border-warn/40 bg-warn/10 text-warn",
    accent: "border-accent/40 bg-accent/10 text-accent",
    muted: "border-line bg-white/5 text-muted",
  };
  const more = sorted.length - shown.length;

  return (
    <Panel title="Today" icon={CalendarDays} className="min-w-0" bodyClassName="p-2" actions={<WidgetLink href="/day">Calendar</WidgetLink>}>
      {d.todos === null && d.day === null ? (
        <Loading failed={d.loaded} />
      ) : rows.length === 0 ? (
        <EmptyState icon={CalendarDays}>Nothing due and nothing logged yet today — all clear.</EmptyState>
      ) : (
        <ul className="space-y-0.5">
          {rows.slice(0, 8).map((r) => (
            <li key={r.key}>
              <Link href={r.href} className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-white/5">
                <span className={cn("w-[3.6rem] shrink-0 rounded-md border px-1 py-0.5 text-center font-mono text-[10px] uppercase", chipCls[r.chipTone])}>{r.chip}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{r.text}</span>
                  {r.sub && <span className="block truncate text-[11px] text-muted">{r.sub}</span>}
                </span>
                <r.icon size={14} className="shrink-0 text-muted/70" />
              </Link>
            </li>
          ))}
          {more > 0 && (
            <li>
              <Link href="/todos" className="block px-2 pt-1 text-xs text-muted hover:text-accent">
                +{more} more due or overdue
              </Link>
            </li>
          )}
        </ul>
      )}
    </Panel>
  );
}

function GoalsWidget({ d }: { d: Data }) {
  const rows = d.habits ?? [];
  const onPaceCount = rows.filter((h) => onPace(h.progress)).length;
  return (
    <Panel
      title="Goals this period"
      icon={Target}
      className="min-w-0"
      actions={<WidgetLink href="/habits">Habits</WidgetLink>}
    >
      {d.habits === null ? (
        <Loading failed={d.loaded} />
      ) : rows.length === 0 ? (
        <EmptyState icon={Target}>
          No goals yet. <Link href="/habits" className="text-accent hover:underline">Set a habit</Link> like &ldquo;gym 4×/week&rdquo;.
        </EmptyState>
      ) : (
        <>
          <p className="mb-3 font-mono text-[11px] text-muted">
            <span className={onPaceCount === rows.length ? "text-ok" : "text-warn"}>{onPaceCount}</span>/{rows.length} on pace · tick = where you should be by now
          </p>
          <ul className="space-y-1">
            {rows.slice(0, 6).map(({ habit, progress: p }) => {
              const good = onPace(p);
              const color = good ? "#34d399" : p.direction === "at_most" ? "#f87171" : "#fbbf24";
              const frac = p.target > 0 ? p.current / p.target : 0;
              const status = good ? "on pace" : p.direction === "at_most" ? "over pace" : "behind pace";
              return (
                <li key={habit.id}>
                  <Link href="/habits" className="flex items-center gap-3 rounded-lg px-1 py-1 transition-colors hover:bg-white/5">
                    <Ring
                      value={frac}
                      marker={p.target > 0 ? p.prorated_target / p.target : undefined}
                      color={color}
                      size={46}
                      stroke={5}
                      label={`${habit.name}: ${fmtAmount(p.current, p.unit)} of ${fmtAmount(p.target, p.unit)}, ${status}`}
                    >
                      <span className="font-mono text-[10px] font-semibold">{Math.round(frac * 100)}%</span>
                    </Ring>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-sm">{habit.name}</span>
                        <span className="shrink-0 font-mono text-[11px] text-muted">
                          {fmtAmount(p.current, p.unit)} / {fmtAmount(p.target, p.unit)}
                        </span>
                      </span>
                      <span className="mt-0.5 flex items-center justify-between gap-2 text-[10px]">
                        <span className="uppercase tracking-wider" style={{ color }}>
                          {good ? "✓ " : "! "}
                          {status}
                        </span>
                        <span className="font-mono text-muted">
                          pace {fmtAmount(p.prorated_target, p.unit)} · per {p.target_period.replace(/ly$/, "")}
                        </span>
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Panel>
  );
}

function ProductivityWidget({ d, today }: { d: Data; today: string }) {
  const weekStart = mondayOfWeek(today);
  const lastStart = addDaysIso(weekStart, -7);
  const acts = d.activities ?? [];
  const thisWeek = acts.filter((a) => a.date >= weekStart && a.date <= today);
  const elapsed = [0, 1, 2, 3, 4, 5, 6].filter((i) => addDaysIso(weekStart, i) <= today).length;
  // Same days-elapsed slice of last week, so the comparison is fair mid-week.
  const lastWeekSoFar = acts.filter((a) => a.date >= lastStart && a.date <= addDaysIso(lastStart, elapsed - 1));
  const total = thisWeek.reduce((s, a) => s + a.hours, 0);
  const lastTotal = lastWeekSoFar.reduce((s, a) => s + a.hours, 0);

  const byCat = new Map<string, number>();
  thisWeek.forEach((a) => byCat.set(a.category || "other", (byCat.get(a.category || "other") ?? 0) + a.hours));
  const cats = [...byCat.entries()].sort((a, b) => b[1] - a[1]);
  // Colour follows the category (alphabetical among this week's top 7), not its rank.
  const top = new Set(cats.slice(0, SERIES.length).map(([c]) => c));
  const palette = new Map([...top].sort().map((c, i) => [c, SERIES[i]]));
  const colorOf = (c: string) => palette.get(c) ?? OTHER;
  const fold = (c: string) => (top.has(c) ? c : "Other");

  const days = [0, 1, 2, 3, 4, 5, 6].map((i) => {
    const date = addDaysIso(weekStart, i);
    const seg = new Map<string, number>();
    thisWeek.filter((a) => a.date === date).forEach((a) => seg.set(fold(a.category || "other"), (seg.get(fold(a.category || "other")) ?? 0) + a.hours));
    return { label: WEEKDAY[i], title: formatIsoDate(date).replace(/, \d{4}$/, ""), segments: [...seg.entries()].map(([key, value]) => ({ key, value })) };
  });
  const delta = total - lastTotal;
  const legend = [...cats.slice(0, SERIES.length), ...(cats.length > SERIES.length ? [["Other", cats.slice(SERIES.length).reduce((s, [, h]) => s + h, 0)] as [string, number]] : [])];

  return (
    <Panel title="Productivity · this week" icon={Clock} className="min-w-0" actions={<WidgetLink href="/day">Log</WidgetLink>}>
      {d.activities === null ? (
        <Loading failed={d.loaded} />
      ) : thisWeek.length === 0 ? (
        <EmptyState icon={Clock}>No hours logged this week — tell Chat &ldquo;2h deep work on Quintacle&rdquo;.</EmptyState>
      ) : (
        <div className="space-y-3">
          <div className="flex items-end justify-between gap-3">
            <p className="font-mono text-3xl font-semibold leading-none text-accent">
              {r1(total)}
              <span className="ml-1 text-sm font-normal text-muted">h</span>
            </p>
            {lastTotal > 0 || total > 0 ? (
              <p className={cn("flex items-center gap-0.5 font-mono text-xs", delta >= 0 ? "text-ok" : "text-warn")}>
                {delta >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                {delta >= 0 ? "+" : ""}
                {r1(delta)}h vs last week so far
              </p>
            ) : null}
          </div>
          <StackedColumns days={days} colorOf={(k) => (k === "Other" ? OTHER : colorOf(k))} highlight={elapsed - 1} />
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1">
            {legend.map(([c, h]) => (
              <li key={c} className="flex min-w-0 items-center gap-2 text-xs">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: c === "Other" ? OTHER : colorOf(c) }} />
                <span className="min-w-0 flex-1 truncate text-foreground/90">{c}</span>
                <span className="font-mono text-muted">{r1(h)}h</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function WeightWidget({ d, today }: { d: Data; today: string }) {
  const rows = d.weight ?? [];
  const start = addDaysIso(today, -WEIGHT_DAYS);
  const unit = rows.length ? rows[rows.length - 1].unit || "lb" : "lb";
  // One point per day (the last reading that day), in the latest reading's unit.
  const perDay = new Map<string, number>();
  rows.forEach((r) => perDay.set(r.date, toUnit(r.value, r.unit || "lb", unit)));
  const points = [...perDay.entries()].map(([x, y]) => ({ x, y, label: formatIsoDate(x).replace(/, \d{4}$/, "") }));
  const latest = points[points.length - 1];
  const first = points[0];
  const weekAgo = [...points].reverse().find((p) => p.x <= addDaysIso(today, -7));
  const change = latest && first ? latest.y - first.y : 0;
  const fmt = (y: number) => `${r1(y)} ${unit}`;

  return (
    <Panel title={`Weight · ${WEIGHT_DAYS} days`} icon={Scale} className="min-w-0" actions={<WidgetLink href="/kb">Log</WidgetLink>}>
      {d.weight === null ? (
        <Loading failed={d.loaded} />
      ) : !latest ? (
        <EmptyState icon={Scale}>No weight logged yet — log it from Chat or the scratchpad (&ldquo;weight 182 lb&rdquo;).</EmptyState>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="font-mono text-3xl font-semibold leading-none text-accent">
                {r1(latest.y)}
                <span className="ml-1 text-sm font-normal text-muted">{unit}</span>
              </p>
              <p className="mt-1 text-[11px] text-muted">latest · {latest.label}</p>
            </div>
            <div className="text-right font-mono text-xs">
              {points.length > 1 && (
                <p className={change <= 0 ? "text-ok" : "text-warn"}>
                  {change > 0 ? "+" : ""}
                  {r1(change)} {unit} <span className="text-muted">since {first.label}</span>
                </p>
              )}
              {weekAgo && weekAgo !== latest && (
                <p className="text-muted">
                  {latest.y - weekAgo.y > 0 ? "+" : ""}
                  {r1(latest.y - weekAgo.y)} {unit} vs a week ago
                </p>
              )}
            </div>
          </div>
          {points.length > 1 ? (
            <Sparkline points={points} start={start} end={today} format={fmt} />
          ) : (
            <p className="rounded-lg border border-dashed border-line p-4 text-center text-xs text-muted">One reading so far — the trend line appears after the next.</p>
          )}
          {points.length > 1 && (
            <div className="flex justify-between font-mono text-[10px] text-muted">
              <span>{formatIsoDate(start).replace(/, \d{4}$/, "")}</span>
              <span>
                range {r1(Math.min(...points.map((p) => p.y)))}–{r1(Math.max(...points.map((p) => p.y)))}
              </span>
              <span>today</span>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function FoodWidget({ d }: { d: Data }) {
  const kcal = d.nutrition?.macros.total_kcal ?? 0;
  const protein = d.nutrition?.macros.total_protein_g ?? 0;
  const targets = d.targets && !("error" in d.targets) ? d.targets : null;
  return (
    <Panel title="Food today" icon={Utensils} className="min-w-0" bodyClassName="p-3">
      {d.nutrition === null && d.targets === null ? (
        <Loading failed={d.loaded} />
      ) : (
        <Link href="/day" className="block space-y-2.5">
          <div>
            <div className="mb-1 flex items-baseline justify-between gap-1">
              <span className="font-mono text-xl font-semibold text-accent">{Math.round(kcal).toLocaleString()}</span>
              <span className="truncate text-[10px] text-muted">{targets ? `/ ${Math.round(targets.tdee_kcal).toLocaleString()} kcal` : "kcal"}</span>
            </div>
            <Meter value={kcal} max={targets?.tdee_kcal ?? Math.max(kcal, 1)} color={targets && kcal > targets.tdee_kcal ? "#fbbf24" : "#22d3ee"} />
          </div>
          <div>
            <div className="mb-1 flex items-baseline justify-between gap-1">
              <span className="font-mono text-base font-semibold">{Math.round(protein)}g</span>
              <span className="truncate text-[10px] text-muted">{targets ? `/ ${Math.round(targets.protein_target_g)}g protein` : "protein"}</span>
            </div>
            <Meter value={protein} max={targets?.protein_target_g ?? Math.max(protein, 1)} color={targets && protein >= targets.protein_target_g ? "#34d399" : "#3987e5"} />
          </div>
          {!targets && <p className="text-[10px] text-muted">Set height/sex in Profile + log weight for targets.</p>}
          {d.nutrition && kcal === 0 && <p className="text-[10px] text-muted">Nothing logged yet today.</p>}
        </Link>
      )}
    </Panel>
  );
}

function SpendWidget({ d, today }: { d: Data; today: string }) {
  const weekStart = mondayOfWeek(today);
  const ex = d.expenses ?? [];
  const week = ex.reduce((s, e) => s + e.amount, 0);
  const todaySpend = ex.filter((e) => e.date === today).reduce((s, e) => s + e.amount, 0);
  const byDay = [0, 1, 2, 3, 4, 5, 6].map((i) => ex.filter((e) => e.date === addDaysIso(weekStart, i)).reduce((s, e) => s + e.amount, 0));
  const max = Math.max(1, ...byDay);
  const budgets = (d.habits ?? []).filter((h) => h.progress.metric === "spend" && h.progress.direction === "at_most");
  const left = budgets.reduce((s, h) => s + (h.progress.target - h.progress.current), 0);
  return (
    <Panel title="Spend · week" icon={Wallet} className="min-w-0" bodyClassName="p-3">
      {d.expenses === null ? (
        <Loading failed={d.loaded} />
      ) : (
        <Link href="/finance" className="block space-y-2">
          <div className="flex items-baseline justify-between gap-1">
            <span className="font-mono text-xl font-semibold text-accent">{money(week)}</span>
            <span className="truncate text-[10px] text-muted">{money(todaySpend)} today</span>
          </div>
          <div className="flex h-9 items-end gap-1" aria-label="Spend per day this week">
            {byDay.map((v, i) => (
              <div key={i} className="flex h-full flex-1 items-end justify-center">
                <div
                  className="w-full max-w-4 rounded-t-[3px]"
                  title={`${WEEKDAY[i]}: ${money(v)}`}
                  style={{ height: `${Math.max(v > 0 ? 8 : 4, (v / max) * 100)}%`, background: v > 0 ? "#22d3ee" : "rgb(255 255 255 / 0.08)", opacity: v > 0 ? 0.85 : 1 }}
                />
              </div>
            ))}
          </div>
          <p className={cn("text-[10px]", budgets.length && left < 0 ? "text-danger" : "text-muted")}>
            {budgets.length ? `${money(Math.abs(left))} ${left < 0 ? "over" : "left"} in budget${budgets.length > 1 ? "s" : ""}` : `${ex.length} purchase${ex.length === 1 ? "" : "s"} · no budget set`}
          </p>
        </Link>
      )}
    </Panel>
  );
}

function ConnectionsWidget({ d }: { d: Data }) {
  return (
    <Panel title="Connections · last 7 days" icon={Network} className="min-w-0" bodyClassName="p-2" actions={<WidgetLink href="/kb/graph">Full graph</WidgetLink>}>
      {d.graph && d.graph.nodes.some((n) => n.recent) ? (
        <WeekGraph graph={d.graph} />
      ) : (
        <p className="p-6 text-center text-sm text-muted">{d.graph ? "Nothing saved in the last 7 days." : d.loaded ? "Couldn't load the graph." : "Loading…"}</p>
      )}
    </Panel>
  );
}

function RecentWidget({ d, today }: { d: Data; today: string }) {
  return (
    <Panel title="Recent" icon={History} className="min-w-0" bodyClassName="p-2" actions={<WidgetLink href="/kb/browse">Browse</WidgetLink>}>
      {!d.recent || d.recent.length === 0 ? (
        <EmptyState icon={History}>{d.recent ? "Nothing saved yet." : d.loaded ? "Couldn't load recent items." : "Loading…"}</EmptyState>
      ) : (
        <ul className="grid gap-x-4 gap-y-0.5 md:grid-cols-2">
          {d.recent.map((r) => {
            const href = nodeHref(r.id);
            const row = (
              <span className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-white/5">
                <span className="w-14 shrink-0 font-mono text-[10px] uppercase tracking-wider text-accent/80">{TYPE_LABEL[r.type] ?? r.type}</span>
                <span className="min-w-0 flex-1 truncate">{r.title}</span>
                <span className="shrink-0 text-xs text-muted">{today ? relTime(r.updated_at, today) : ""}</span>
              </span>
            );
            return <li key={r.id}>{href ? <Link href={href}>{row}</Link> : row}</li>;
          })}
        </ul>
      )}
    </Panel>
  );
}

// ---------------- page ----------------

export default function Dashboard() {
  const [now, setNow] = useState<Date | null>(null);
  const [d, setD] = useState<Data>(EMPTY);

  useEffect(() => {
    setNow(new Date());
    const today = todayIso();
    const weekStart = mondayOfWeek(today);
    Promise.all([
      soft(listTodos()),
      // Progress fetched one habit at a time: the backend shares one SQLite
      // connection, and a burst of parallel progress reads can trip it.
      soft(
        listHabits().then(async (hs) => {
          const out: HabitRow[] = [];
          for (const h of hs.filter((h) => !h.ended_on)) out.push({ habit: h, progress: await habitProgress(h.id) });
          return out;
        })
      ),
      soft(getNutritionForDate(today)),
      soft(getTargets()),
      soft(listExpenses(weekStart, today)),
      soft(activitiesInRange(addDaysIso(weekStart, -7), today)),
      soft(getJournal(today).then((j) => (j.content && j.content.trim() ? j.content : null))),
      soft(getRecent(8)),
      soft(getRecentGraph(addDaysIso(today, -6))),
      soft(listBodyStats(addDaysIso(today, -WEIGHT_DAYS), today, "weight")),
      soft(getDayDetail(today)),
    ]).then(([todos, habits, nutrition, targets, expenses, activities, journal, recent, graph, weight, day]) =>
      setD({ todos, habits, nutrition, targets, expenses, activities, journal, recent, graph, weight, day, loaded: true })
    );
  }, []);

  const today = now ? todayIso() : "";

  return (
    <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-accent">
              {now ? now.toLocaleDateString(undefined, { timeZone: TIME_ZONE, weekday: "long", month: "long", day: "numeric" }) : " "}
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
              {now ? greeting(Number(new Intl.DateTimeFormat("en-US", { timeZone: TIME_ZONE, hour: "numeric", hourCycle: "h23" }).format(now))) : "Welcome"}.
            </h1>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { href: "/kb/browse?path=Me", label: "Me", icon: BookUser },
              { href: "/profile", label: "Profile", icon: User },
            ].map((t) => (
              <Link
                key={t.label}
                href={t.href}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-surface-2/50 px-3 py-1.5 text-sm text-muted transition-colors hover:border-accent/50 hover:text-foreground"
              >
                <t.icon size={14} className="text-accent" />
                {t.label}
              </Link>
            ))}
          </div>
        </div>

        {today && (
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <TodayWidget d={d} today={today} />
            <GoalsWidget d={d} />
            <ProductivityWidget d={d} today={today} />
            <WeightWidget d={d} today={today} />
            <div className="grid grid-cols-2 gap-3 md:col-span-2 md:gap-5">
              <FoodWidget d={d} />
              <SpendWidget d={d} today={today} />
            </div>
            <div className="md:col-span-2">
              <ConnectionsWidget d={d} />
            </div>
            <div className="md:col-span-2">
              <RecentWidget d={d} today={today} />
            </div>
          </div>
        )}
      </div>

      <AssistPanel />
    </div>
  );
}
