"use client";

// Subscriptions tab: the old Finance ledger's "Subscriptions" kind view
// (logged kind=subscription charges grouped by merchant) + the old Insights
// view's detected recurring charges (cadence arithmetic, no model) and
// monthly burn. Moved here 2026-11-05.

import { useEffect, useMemo, useState } from "react";
import { DetectedSubscription, Expense, getDetectedSubscriptions, listExpenses } from "@/lib/api";
import { todayIso, yearsAgoIso } from "@/lib/date";
import { Badge, Panel, Stat } from "@/components/ui/Panel";
import { money } from "./shared";

export default function SubscriptionsTab() {
  const [logged, setLogged] = useState<Expense[]>([]);
  const [subs, setSubs] = useState<{ subscriptions: DetectedSubscription[]; monthly_burn: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listExpenses(yearsAgoIso(2), todayIso()), getDetectedSubscriptions()]).then(([ex, s]) => {
      if (cancelled) return;
      setLogged(ex.filter((e) => e.kind === "subscription").sort((a, b) => b.date.localeCompare(a.date)));
      setSubs(s);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(() => {
    const map = new Map<string, Expense[]>();
    for (const e of logged) {
      const key = e.merchant.trim().toLowerCase() || "(unnamed)";
      map.set(key, [...(map.get(key) ?? []), e]);
    }
    return Array.from(map.values())
      .map((items) => ({
        merchant: items[0].merchant || "(unnamed)",
        count: items.length,
        lastAmount: items[0].amount,
        lastDate: items[0].date,
        avg: items.reduce((s, e) => s + e.amount, 0) / items.length,
      }))
      .sort((a, b) => b.avg - a.avg);
  }, [logged]);

  const active = subs?.subscriptions.filter((s) => s.active) ?? [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Stat label="Monthly burn" value={subs ? money(subs.monthly_burn) : "—"} hint="detected, active" />
        <Stat label="Annualized" value={subs ? money(subs.monthly_burn * 12) : "—"} hint="monthly burn × 12" />
        <Stat label="Active recurring" value={active.length} hint={`${subs?.subscriptions.length ?? 0} detected total`} />
      </div>

      <Panel title="Detected recurring charges">
        <p className="mb-3 text-xs text-muted">
          Same merchant + similar amount at a steady cadence — recurrence arithmetic over the ledger, no AI judgment.
        </p>
        {subs && subs.subscriptions.length === 0 && <p className="text-sm text-muted">No recurring charges detected yet.</p>}
        <ul className="divide-y divide-line">
          {subs?.subscriptions.map((s) => (
            <li key={`${s.merchant}-${s.amount}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{s.merchant}</p>
                <p className="text-xs text-muted">
                  {money(s.amount)} {s.cadence} · {s.charges} charges · next {s.next_expected}
                  {!s.kind_already_subscription && " · not kind=subscription in the ledger"}
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono text-sm">{money(s.monthly_equivalent)}/mo</p>
                <Badge tone={s.active ? "ok" : "muted"}>{s.active ? "active" : "lapsed"}</Badge>
              </div>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Logged subscriptions (kind = subscription)">
        {groups.length === 0 && <p className="text-sm text-muted">No subscriptions logged yet.</p>}
        <ul className="divide-y divide-line">
          {groups.map((g) => (
            <li key={g.merchant} className="flex items-center justify-between gap-2 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{g.merchant}</p>
                <p className="text-xs text-muted">
                  {g.count} charge{g.count === 1 ? "" : "s"} logged · last {money(g.lastAmount)} on {g.lastDate}
                </p>
              </div>
              <span className="shrink-0 font-mono text-sm">~{money(g.avg)}/charge</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
