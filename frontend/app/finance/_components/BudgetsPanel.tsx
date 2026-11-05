"use client";

// Budget lines = habits with metric="spend" (set up via a "budget:" drop or
// the Habits page). Progress numbers (current, target, proration) are all
// computed by /logs/habits/{id}/progress — rendering only here.

import { useEffect, useState } from "react";
import { Target } from "lucide-react";
import { Habit, habitProgress, HabitProgress, listHabits } from "@/lib/api";
import { Panel } from "@/components/ui/Panel";
import { Bar, money } from "./shared";

type Line = { habit: Habit; progress: HabitProgress | null };

export function useBudgetLines() {
  const [lines, setLines] = useState<Line[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    listHabits()
      .then(async (habits) => {
        const spend = habits.filter((h) => h.metric === "spend" && !h.ended_on);
        const progress = await Promise.all(spend.map((h) => habitProgress(h.id).catch(() => null)));
        if (!cancelled) setLines(spend.map((habit, i) => ({ habit, progress: progress[i] })));
      })
      .catch(() => !cancelled && setLines([]));
    return () => {
      cancelled = true;
    };
  }, []);
  return lines;
}

export default function BudgetsPanel({ compact = false }: { compact?: boolean }) {
  const lines = useBudgetLines();
  return (
    <Panel
      title="Budgets"
      icon={Target}
      actions={
        <a href="/habits" className="text-xs text-muted hover:text-foreground">
          manage →
        </a>
      }
    >
      {lines === null && <p className="text-sm text-muted">Loading…</p>}
      {lines?.length === 0 && (
        <p className="text-sm text-muted">
          No budget lines yet — drop &quot;budget: $400/month food&quot; in chat, or add a spend habit on the Habits page.
        </p>
      )}
      <ul className="space-y-3">
        {(compact ? lines?.slice(0, 4) : lines)?.map(({ habit, progress }) => {
          const over = progress ? progress.current > progress.target : false;
          const aheadOfPace = progress ? progress.current > progress.prorated_target : false;
          return (
            <li key={habit.id} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="truncate">{habit.name}</span>
                <span className="shrink-0 font-mono text-xs text-muted">
                  {progress ? `${money(progress.current)} / ${money(progress.target)}` : "—"} · {habit.target_period}
                </span>
              </div>
              <Bar
                value={progress?.current ?? 0}
                max={progress?.target ?? 0}
                barClassName={over ? "bg-danger" : aheadOfPace ? "bg-warn" : "bg-ok"}
              />
              {progress && !compact && (
                <p className="text-[11px] text-muted">
                  {over
                    ? "over budget"
                    : aheadOfPace
                      ? `ahead of pace — ${money(progress.prorated_target)} expected by day ${progress.elapsed_days}/${progress.period_days}`
                      : `on pace — ${money(progress.prorated_target)} expected by day ${progress.elapsed_days}/${progress.period_days}`}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
