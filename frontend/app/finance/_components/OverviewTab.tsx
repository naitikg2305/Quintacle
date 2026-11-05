"use client";

// Overview tab: net worth (recorded account balances + uncovered stock-ledger
// holdings − liabilities, computed by GET /finance/accounts), this month's
// spend / income / savings rate / subscription burn, budgets, and a 12-month
// spend-vs-income chart. Rendering only — every figure is server-computed.

import { useEffect, useState } from "react";
import {
  AccountsSummary,
  DetectedSubscription,
  getAccounts,
  getDetectedSubscriptions,
  getMonthlyInsights,
  MonthlyInsight,
} from "@/lib/api";
import { Panel, Stat } from "@/components/ui/Panel";
import BudgetsPanel from "./BudgetsPanel";
import { Donut, fmtDelta, money, SLICE_COLORS, Sparkline, toneOf } from "./shared";

export default function OverviewTab({ goTab }: { goTab: (t: string) => void }) {
  const [accounts, setAccounts] = useState<AccountsSummary | null>(null);
  const [months, setMonths] = useState<MonthlyInsight[]>([]);
  const [subs, setSubs] = useState<{ subscriptions: DetectedSubscription[]; monthly_burn: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getAccounts(), getMonthlyInsights(12), getDetectedSubscriptions()]).then(([a, m, s]) => {
      if (cancelled) return;
      setAccounts(a);
      setMonths(m);
      setSubs(s);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const current = months[months.length - 1];
  const mix = accounts
    ? [
        { key: "Cash & bank", value: accounts.buckets.liquid },
        { key: "Investments", value: accounts.investments_total },
        { key: "Retirement", value: accounts.buckets.retirement },
        { key: "Other", value: accounts.buckets.other },
      ].filter((s) => s.value > 0)
    : [];
  const mixTotal = accounts?.assets ?? 0;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
        <Panel title="Net worth">
          {accounts && accounts.accounts.length === 0 && accounts.stock_holdings_counted === 0 ? (
            <p className="text-sm text-muted">
              Record your accounts (checking, 401(k), brokerage…) to see net worth.{" "}
              <button onClick={() => goTab("accounts")} className="text-accent underline">
                Add accounts →
              </button>
            </p>
          ) : (
            <>
              <p className="font-mono text-3xl font-semibold text-accent">{money(accounts?.net_worth)}</p>
              <p className="mt-1 text-xs text-muted">
                {accounts?.as_of ? `latest balance ${accounts.as_of}` : "no balances recorded yet"}
                {accounts && accounts.stock_holdings_counted > 0 &&
                  ` · incl. ${money(accounts.stock_holdings_counted)} stock holdings${accounts.stock_holdings_at_cost ? " (some at cost)" : ""}`}
              </p>
              {accounts && accounts.history.length > 1 && (
                <div className="mt-3">
                  <Sparkline values={accounts.history.map((h) => h.net_worth)} className="h-12" />
                  <p className="mt-1 text-[10px] text-muted">
                    recorded balances over time ({accounts.history[0].date} → {accounts.history[accounts.history.length - 1].date})
                  </p>
                </div>
              )}
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                <Row label="Cash & bank" value={accounts?.buckets.liquid} />
                <Row label="Investments" value={accounts?.investments_total} />
                <Row label="Retirement" value={accounts?.buckets.retirement} />
                <Row label="Liabilities" value={accounts ? -accounts.liabilities : null} />
              </div>
            </>
          )}
        </Panel>

        <Panel title="Asset mix">
          {mix.length === 0 || mixTotal <= 0 ? (
            <p className="text-sm text-muted">No assets recorded yet.</p>
          ) : (
            <div className="flex items-center gap-4">
              <Donut label="Asset mix" slices={mix.map((s) => ({ key: s.key, pct: (s.value / mixTotal) * 100 }))} />
              <ul className="flex-1 space-y-1 text-xs">
                {mix.map((s, i) => (
                  <li key={s.key} className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SLICE_COLORS[i % SLICE_COLORS.length] }} />
                    <span>{s.key}</span>
                    <span className="ml-auto font-mono text-muted">{money(s.value)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      </div>

      {current && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Spent this month" value={money(current.total)} hint={`${fmtDelta(current.delta_total)} vs last month`} />
          <Stat label="Income this month" value={money(current.income)} tone="ok" />
          <Stat
            label="Savings rate"
            value={current.savings_rate_pct !== null ? `${current.savings_rate_pct}%` : "—"}
            hint={`${money(current.savings)} kept`}
            tone={toneOf(current.savings)}
          />
          <Stat
            label="Subscriptions"
            value={subs ? `${money(subs.monthly_burn)}/mo` : "—"}
            hint={subs ? `${subs.subscriptions.filter((s) => s.active).length} active detected` : undefined}
            tone="warn"
          />
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
        <BudgetsPanel compact />
        <Panel title="Spend vs income (12 months)">
          <SpendIncomeChart months={months} />
        </Panel>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-line px-2 py-1.5">
      <span className="text-xs text-muted">{label}</span>
      <span className={`font-mono text-xs ${value != null && value < 0 ? "text-danger" : ""}`}>{money(value)}</span>
    </div>
  );
}

// Plain-SVG grouped bars: spend (accent) vs income (ok) per month.
function SpendIncomeChart({ months }: { months: MonthlyInsight[] }) {
  if (months.length === 0) return <p className="text-sm text-muted">No data yet.</p>;
  const w = 300;
  const h = 110;
  const max = Math.max(...months.map((m) => Math.max(m.total, m.income)), 1);
  const slot = w / months.length;
  const bw = Math.max(2, slot / 2 - 2);
  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h + 14}`} className="h-36 w-full" role="img" aria-label="Monthly spend versus income">
        {months.map((m, i) => {
          const x = i * slot + 1;
          const sh = (m.total / max) * h;
          const ih = (m.income / max) * h;
          return (
            <g key={m.month}>
              <rect x={x} y={h - sh} width={bw} height={sh} rx="1" fill="var(--color-accent)">
                <title>{`${m.month} spend ${money(m.total)}`}</title>
              </rect>
              <rect x={x + bw + 1} y={h - ih} width={bw} height={ih} rx="1" fill="var(--color-ok)">
                <title>{`${m.month} income ${money(m.income)}`}</title>
              </rect>
              {(i % 3 === 0 || i === months.length - 1) && (
                <text x={x} y={h + 11} fontSize="8" fill="var(--color-muted)">
                  {m.month.slice(2)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <p className="mt-1 flex gap-3 text-[11px] text-muted">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-accent" /> spend
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-ok" /> income
        </span>
      </p>
    </div>
  );
}
