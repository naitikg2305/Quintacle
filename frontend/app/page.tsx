"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  BookUser,
  CalendarCheck,
  Clock,
  History,
  ListChecks,
  Network,
  Target,
  User,
  type LucideIcon,
} from "lucide-react";
import {
  activitiesInRange,
  ActivityEntry,
  Expense,
  getJournal,
  getNutritionForDate,
  getRecent,
  getRecentGraph,
  getTargets,
  Habit,
  habitProgress,
  HabitProgress,
  listExpenses,
  listHabits,
  listTodos,
  NutritionForDate,
  RecentGraph,
  RecentNode,
  Targets,
  Todo,
} from "@/lib/api";
import { EmptyState, Panel, Stat } from "@/components/ui/Panel";
import AssistPanel from "@/components/overview/AssistPanel";
import WeekGraph from "@/components/overview/WeekGraph";
import { nodeHref } from "@/components/overview/links";
import { addDaysIso, mondayOfWeek, TIME_ZONE, todayIso } from "@/lib/date";

// The overview (owner-approved 2026-11-03, replacing the old link-grid Home):
// the morning glance. Today's row, a deterministic Brief, Recent, This week
// with a mini graph, and the Assist + Capture column. Everything here is
// computed in code from existing endpoints — no model writes the Brief.

type HabitRow = { habit: Habit; progress: HabitProgress };

type Data = {
  todos: Todo[] | null;
  habits: HabitRow[] | null;
  nutrition: NutritionForDate | null;
  targets: Targets | null;
  expenses: Expense[] | null;
  activities: ActivityEntry[] | null;
  journal: string | null | undefined;
  recent: RecentNode[] | null;
  graph: RecentGraph | null;
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
};

// One failing endpoint blanks its own tile, never the page.
const soft = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

function greeting(hour: number): string {
  if (hour < 5) return "Late night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 100 ? 2 : 0 })}`;

function onPace(p: HabitProgress): boolean {
  return p.direction === "at_most" ? p.current <= p.prorated_target : p.current >= p.prorated_target;
}

function fmtAmount(n: number, unit: string): string {
  if (unit === "$" || unit === "usd" || unit === "dollars") return money(n);
  return `${Math.round(n * 10) / 10}${unit ? ` ${unit}` : ""}`;
}

function relTime(iso: string, today: string): string {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  if (day === today) return new Date(iso).toLocaleTimeString(undefined, { timeZone: TIME_ZONE, hour: "numeric", minute: "2-digit" });
  if (day === addDaysIso(today, -1)) return "Yesterday";
  return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
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

type BriefItem = { icon: LucideIcon; text: string; tone: "warn" | "danger" | "muted" | "ok"; href?: string };

function buildBrief(d: Data, today: string): BriefItem[] {
  const items: BriefItem[] = [];
  const open = (d.todos ?? []).filter((t) => !t.done);
  for (const t of open.filter((t) => t.due_date === today).sort((a, b) => b.priority - a.priority)) {
    items.push({ icon: ListChecks, text: `Due today: ${t.title}${t.start_time ? ` · ${t.start_time.slice(0, 5)}` : ""}`, tone: "warn", href: "/todos" });
  }
  const overdue = open.filter((t) => t.due_date && t.due_date < today);
  if (overdue.length) {
    items.push({
      icon: AlertTriangle,
      text: `${overdue.length} overdue — oldest: ${overdue.sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))[0].title}`,
      tone: "danger",
      href: "/todos",
    });
  }
  for (const { habit, progress: p } of d.habits ?? []) {
    if (onPace(p)) continue;
    const verb = p.direction === "at_most" ? "over pace" : "behind pace";
    items.push({
      icon: Target,
      text: `${habit.name}: ${fmtAmount(p.current, p.unit)} of ${fmtAmount(p.target, p.unit)} this ${p.target_period.replace(/ly$/, "")} — ${verb}`,
      tone: p.direction === "at_most" ? "danger" : "warn",
      href: "/habits",
    });
  }
  if (d.journal === null) items.push({ icon: BookOpen, text: "Nothing written for today yet", tone: "muted", href: "/journal" });
  return items;
}

export default function Overview() {
  const [now, setNow] = useState<Date | null>(null);
  const [d, setD] = useState<Data>(EMPTY);

  useEffect(() => {
    setNow(new Date());
    const today = todayIso();
    const weekStart = mondayOfWeek(today);
    Promise.all([
      soft(listTodos()),
      soft(
        listHabits().then((hs) =>
          Promise.all(
            hs.filter((h) => !h.ended_on).map((h) => habitProgress(h.id).then((progress) => ({ habit: h, progress })))
          )
        )
      ),
      soft(getNutritionForDate(today)),
      soft(getTargets()),
      soft(listExpenses(weekStart, today)),
      soft(activitiesInRange(weekStart, today)),
      soft(getJournal(today).then((j) => (j.content && j.content.trim() ? j.content : null))),
      soft(getRecent(8)),
      soft(getRecentGraph(addDaysIso(today, -6))),
    ]).then(([todos, habits, nutrition, targets, expenses, activities, journal, recent, graph]) =>
      setD({ todos, habits, nutrition, targets, expenses, activities, journal, recent, graph })
    );
  }, []);

  const today = now ? todayIso() : "";
  const open = (d.todos ?? []).filter((t) => !t.done);
  const dueToday = open.filter((t) => t.due_date === today).length;
  const overdue = open.filter((t) => t.due_date && t.due_date < today).length;

  const habitsOnPace = (d.habits ?? []).filter((h) => onPace(h.progress)).length;
  const kcal = d.nutrition?.macros.total_kcal ?? 0;
  const protein = d.nutrition?.macros.total_protein_g ?? 0;
  const targets = d.targets && !("error" in d.targets) ? d.targets : null;

  const spendToday = (d.expenses ?? []).filter((e) => e.date === today).reduce((s, e) => s + e.amount, 0);
  const spendWeek = (d.expenses ?? []).reduce((s, e) => s + e.amount, 0);
  const hoursWeek = (d.activities ?? []).reduce((s, a) => s + a.hours, 0);
  const hoursByCat = Object.entries(
    (d.activities ?? []).reduce<Record<string, number>>((acc, a) => ({ ...acc, [a.category]: (acc[a.category] ?? 0) + a.hours }), {})
  ).sort((a, b) => b[1] - a[1]);
  const budgets = (d.habits ?? []).filter((h) => h.progress.metric === "spend" && h.progress.direction === "at_most");
  const budgetLeft = budgets.reduce((s, h) => s + (h.progress.target - h.progress.current), 0);
  const habitsMet = (d.habits ?? []).filter((h) => h.progress.met).length;

  const brief = now ? buildBrief(d, today) : [];
  const loading = d.todos === null && d.recent === null && d.habits === null;

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

        {/* Today */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Link href="/todos">
            <Stat
              label="Todos today"
              value={d.todos ? dueToday : "–"}
              tone={overdue > 0 ? "danger" : dueToday > 0 ? "warn" : "ok"}
              hint={d.todos ? (overdue ? `${overdue} overdue · ${open.length} open` : `${open.length} open`) : " "}
            />
          </Link>
          <Link href="/habits">
            <Stat
              label="Habits on pace"
              value={d.habits ? (d.habits.length ? `${habitsOnPace}/${d.habits.length}` : "–") : "–"}
              tone={d.habits && d.habits.length && habitsOnPace < d.habits.length ? "warn" : "ok"}
              hint={d.habits && !d.habits.length ? "No habits set" : "this period"}
            />
          </Link>
          <Link href="/day">
            <Stat
              label="Food today"
              value={d.nutrition ? `${Math.round(kcal).toLocaleString()}` : "–"}
              hint={
                targets
                  ? `of ${Math.round(targets.tdee_kcal).toLocaleString()} kcal · ${Math.round(protein)}/${Math.round(targets.protein_target_g)}g protein`
                  : `kcal · ${Math.round(protein)}g protein`
              }
            />
          </Link>
          <Link href="/finance">
            <Stat
              label="Spend today"
              value={d.expenses ? money(spendToday) : "–"}
              hint={d.expenses ? `${money(spendWeek)} this week` : " "}
            />
          </Link>
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <Panel title="Brief" icon={CalendarCheck} className="min-w-0" bodyClassName="p-3">
            {loading ? (
              <p className="p-2 text-sm text-muted">Loading…</p>
            ) : brief.length === 0 ? (
              <EmptyState icon={CalendarCheck}>Nothing pressing today — all clear.</EmptyState>
            ) : (
              <ul className="space-y-1">
                {brief.map((b, i) => {
                  const color = { warn: "text-warn", danger: "text-danger", muted: "text-muted", ok: "text-ok" }[b.tone];
                  const row = (
                    <span className="flex items-start gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-white/5">
                      <b.icon size={15} className={`mt-0.5 shrink-0 ${color}`} />
                      <span>{b.text}</span>
                    </span>
                  );
                  return <li key={i}>{b.href ? <Link href={b.href}>{row}</Link> : row}</li>;
                })}
              </ul>
            )}
          </Panel>

          <Panel title="Recent" icon={History} className="min-w-0" bodyClassName="p-3">
            {!d.recent || d.recent.length === 0 ? (
              <EmptyState icon={History}>{d.recent ? "Nothing saved yet." : "Loading…"}</EmptyState>
            ) : (
              <ul className="space-y-0.5">
                {d.recent.map((r) => {
                  const href = nodeHref(r.id);
                  const row = (
                    <span className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-white/5">
                      <span className="w-14 shrink-0 font-mono text-[10px] uppercase tracking-wider text-accent/80">
                        {TYPE_LABEL[r.type] ?? r.type}
                      </span>
                      <span className="min-w-0 flex-1 truncate">{r.title}</span>
                      <span className="shrink-0 text-xs text-muted">{today ? relTime(r.updated_at, today) : ""}</span>
                    </span>
                  );
                  return <li key={r.id}>{href ? <Link href={href}>{row}</Link> : row}</li>;
                })}
              </ul>
            )}
          </Panel>
        </div>

        {/* This week */}
        <Panel title="This week" icon={Clock} bodyClassName="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat
              label="Hours logged"
              value={d.activities ? Math.round(hoursWeek * 10) / 10 : "–"}
              hint={hoursByCat.length ? hoursByCat.slice(0, 2).map(([c, h]) => `${c} ${Math.round(h * 10) / 10}h`).join(" · ") : "No hours yet"}
            />
            <Stat label="Spent" value={d.expenses ? money(spendWeek) : "–"} hint={`${(d.expenses ?? []).length} purchases`} />
            <Stat
              label="Budget left"
              value={budgets.length ? money(budgetLeft) : "–"}
              tone={budgets.length && budgetLeft < 0 ? "danger" : "accent"}
              hint={budgets.length ? `${budgets.length} budget line${budgets.length > 1 ? "s" : ""}` : "No budget set"}
            />
            <Stat
              label="Goals met"
              value={d.habits && d.habits.length ? `${habitsMet}/${d.habits.length}` : "–"}
              tone="ok"
              hint={d.habits && d.habits.length ? "full target reached" : "No goals set"}
            />
          </div>
          <div className="rounded-lg border border-line bg-surface-2/40 p-2">
            <div className="flex items-center justify-between px-1 pb-1">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Connections · last 7 days</p>
              <Link href="/kb/graph" className="flex items-center gap-1 text-xs text-muted hover:text-accent">
                <Network size={12} /> Full graph
              </Link>
            </div>
            {d.graph && d.graph.nodes.some((n) => n.recent) ? (
              <WeekGraph graph={d.graph} />
            ) : (
              <p className="p-6 text-center text-sm text-muted">{d.graph ? "Nothing saved in the last 7 days." : "Loading…"}</p>
            )}
          </div>
        </Panel>
      </div>

      <AssistPanel />
    </div>
  );
}
