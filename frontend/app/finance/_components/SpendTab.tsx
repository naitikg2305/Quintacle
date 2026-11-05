"use client";

// Spend & budgets tab: the old Finance page's Ledger view (every expense by
// kind + the add-expense form) and the spend half of its Insights view (this
// month by kind, monthly spend/income/savings, top merchants, movers), plus
// budget lines (spend habits). Moved here 2026-11-05 — nothing dropped.

import { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import {
  Expense,
  FINANCE_KINDS,
  FinanceKind,
  getMerchantMovers,
  getMerchantRollup,
  getMonthlyInsights,
  listExpenses,
  logExpense,
  MerchantMover,
  MerchantRollup,
  MonthlyInsight,
} from "@/lib/api";
import { todayIso, yearsAgoIso } from "@/lib/date";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { cn } from "@/lib/cn";
import BudgetsPanel from "./BudgetsPanel";
import { Bar, fmtDelta, money } from "./shared";

export const KIND_LABELS: { kind: FinanceKind; label: string }[] = [
  { kind: "subscription", label: "Subscriptions" },
  { kind: "food", label: "Food" },
  { kind: "alcohol", label: "Alcohol" },
  { kind: "experience", label: "Experience" },
  { kind: "shopping", label: "Shopping" },
  { kind: "big_purchase", label: "Big Purchases" },
  { kind: "regular", label: "Regular" },
];

// Same 3-month window the old Insights view used for the merchant rollup.
function rollupStart(today: string) {
  const [y, m] = today.split("-").map(Number);
  return `${String(m - 3 <= 0 ? y - 1 : y).padStart(4, "0")}-${String(((m - 4 + 12) % 12) + 1).padStart(2, "0")}-01`;
}

export default function SpendTab() {
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [months, setMonths] = useState<MonthlyInsight[]>([]);
  const [merchants, setMerchants] = useState<MerchantRollup[]>([]);
  const [movers, setMovers] = useState<MerchantMover[]>([]);
  const [kindTab, setKindTab] = useState<FinanceKind>("food");

  const [showForm, setShowForm] = useState(false);
  const [amount, setAmount] = useState("");
  const [merchant, setMerchant] = useState("");
  const [category, setCategory] = useState("");
  const [kind, setKind] = useState<FinanceKind>("regular");
  const [entryDate, setEntryDate] = useState(todayIso());
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const today = todayIso();
    return Promise.all([
      listExpenses(yearsAgoIso(2), today),
      getMonthlyInsights(12),
      getMerchantRollup(rollupStart(today), today),
      getMerchantMovers(10),
    ]);
  }

  function apply([ex, mo, me, mv]: Awaited<ReturnType<typeof load>>) {
    setExpenses(ex);
    setMonths(mo);
    setMerchants(me);
    setMovers(mv);
  }

  useEffect(() => {
    let cancelled = false;
    load().then((d) => {
      if (!cancelled) apply(d);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- apply only calls stable state setters
  }, []);

  async function submit() {
    if (!amount || Number(amount) <= 0) return;
    setBusy(true);
    try {
      await logExpense({ date: entryDate, amount: Number(amount), merchant, category, notes, kind });
      setAmount("");
      setMerchant("");
      setCategory("");
      setNotes("");
      setKind("regular");
      setEntryDate(todayIso());
      setShowForm(false);
      apply(await load());
    } finally {
      setBusy(false);
    }
  }

  const byKind = useMemo(() => {
    const grouped = new Map<FinanceKind, Expense[]>();
    for (const t of KIND_LABELS) grouped.set(t.kind, []);
    for (const e of expenses) (grouped.get(e.kind) ?? grouped.get("regular")!).push(e);
    for (const list of grouped.values()) list.sort((a, b) => b.date.localeCompare(a.date));
    return grouped;
  }, [expenses]);

  const grandTotal = expenses.reduce((sum, e) => sum + e.amount, 0);
  const visible = byKind.get(kindTab) ?? [];
  const tabTotal = visible.reduce((sum, e) => sum + e.amount, 0);

  const current = months[months.length - 1];
  const maxMonthTotal = Math.max(...months.map((m) => m.total), 1);
  const maxKind = current ? Math.max(...FINANCE_KINDS.map((k) => current.by_kind[k]), 1) : 1;
  const maxMerchant = Math.max(...merchants.map((m) => m.total), 1);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        {current && (
          <Panel title="This month by kind" actions={<span className="font-mono text-xs text-muted">{money(current.total)}</span>}>
            <div className="space-y-2">
              {KIND_LABELS.map((t) => (
                <div key={t.kind} className="grid grid-cols-[6.5rem_1fr_5.5rem] items-center gap-2 text-sm">
                  <span className="truncate text-muted">{t.label}</span>
                  <Bar value={current.by_kind[t.kind]} max={maxKind} />
                  <span className="text-right font-mono text-xs">
                    {money(current.by_kind[t.kind])}
                    <span className="block text-[10px] text-muted">{fmtDelta(current.delta_by_kind?.[t.kind] ?? null)}</span>
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        )}
        <BudgetsPanel />
      </div>

      <Panel title={`Monthly spend, income & savings (last ${months.length} months)`}>
        <div className="space-y-1.5">
          {months.map((m) => (
            <div key={m.month} className="grid grid-cols-[4rem_1fr_5.5rem_3.5rem] items-center gap-2 text-sm sm:grid-cols-[4.5rem_1fr_6rem_6rem_4rem]">
              <span className="font-mono text-xs text-muted">{m.month}</span>
              <Bar value={m.total} max={maxMonthTotal} />
              <span className="text-right font-mono text-xs">{money(m.total)}</span>
              <span className="hidden text-right font-mono text-xs text-muted sm:block">{m.income > 0 ? money(m.income) : "—"}</span>
              <span className="text-right text-xs text-muted">{m.savings_rate_pct !== null ? `${m.savings_rate_pct}%` : "—"}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-muted">columns: spend · income · savings rate — all computed server-side, no model involved</p>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Top merchants (last ~3 months)">
          {merchants.length === 0 && <p className="text-sm text-muted">No expenses in range.</p>}
          <div className="space-y-2">
            {merchants.slice(0, 12).map((m) => (
              <div key={m.merchant} className="grid grid-cols-[1fr_5.5rem] items-center gap-2 text-sm">
                <div className="min-w-0">
                  <div className="flex justify-between gap-2">
                    <span className="truncate">{m.merchant}</span>
                    <span className="shrink-0 text-xs text-muted">
                      {m.count}× · avg {money(m.average)}
                    </span>
                  </div>
                  <Bar value={m.total} max={maxMerchant} />
                </div>
                <span className="text-right font-mono text-xs">{money(m.total)}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Biggest movers (this month vs last)">
          {movers.length === 0 && <p className="text-sm text-muted">Nothing to compare yet.</p>}
          <div className="space-y-1.5">
            {movers.map((m) => (
              <div key={m.merchant} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate">{m.merchant}</span>
                <span className="shrink-0 text-xs text-muted">
                  {money(m.last_month)} → {money(m.this_month)}
                </span>
                <span className={cn("w-24 shrink-0 text-right font-mono text-xs", m.delta > 0 ? "text-danger" : "text-ok")}>
                  {fmtDelta(m.delta)}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {/* The ledger: every expense, by kind */}
      <Panel
        title="Expense ledger"
        actions={
          <Button size="sm" variant="primary" onClick={() => setShowForm((s) => !s)}>
            {showForm ? <X size={13} /> : <Plus size={13} />}
            {showForm ? "Close" : "Expense"}
          </Button>
        }
      >
        <p className="mb-3 text-xs text-muted">
          Logged manually or via Drop, bucketed by kind. Total tracked (last 2 years): <strong>{money(grandTotal)}</strong>
        </p>
        {showForm && (
          <div className="mb-4 space-y-2 rounded-lg border border-line p-3">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
              <Input type="number" step="0.01" min="0" inputMode="decimal" placeholder="amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <Input placeholder="merchant" value={merchant} onChange={(e) => setMerchant(e.target.value)} />
              <Input placeholder="category" value={category} onChange={(e) => setCategory(e.target.value)} />
              <Select value={kind} onChange={(e) => setKind(e.target.value as FinanceKind)}>
                {FINANCE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k.replace("_", " ")}
                  </option>
                ))}
              </Select>
              <Input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} />
            </div>
            <Textarea rows={2} placeholder="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <Button size="sm" variant="primary" onClick={submit} disabled={busy || !amount || Number(amount) <= 0}>
              Save expense
            </Button>
          </div>
        )}
        <div className="mb-3 flex flex-wrap gap-1.5">
          {KIND_LABELS.map((t) => {
            const count = byKind.get(t.kind)?.length ?? 0;
            return (
              <button
                key={t.kind}
                onClick={() => setKindTab(t.kind)}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs",
                  kindTab === t.kind ? "border-accent/60 bg-accent/15 text-accent" : "border-line text-muted hover:text-foreground"
                )}
              >
                {t.label}
                {count > 0 && <span className="ml-1 opacity-60">({count})</span>}
              </button>
            );
          })}
        </div>
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="text-muted">{KIND_LABELS.find((t) => t.kind === kindTab)?.label}</span>
          <span className="font-mono">{money(tabTotal)}</span>
        </div>
        <ul className="divide-y divide-line">
          {visible.length === 0 && <li className="py-2 text-sm text-muted">Nothing here yet.</li>}
          {visible.map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm">
                  {e.merchant || "(unspecified)"}
                  {e.category && <span className="ml-2 text-xs text-muted">{e.category}</span>}
                </p>
                {e.notes && <p className="truncate text-xs text-muted">{e.notes}</p>}
                <p className="font-mono text-[11px] text-muted">{e.date}</p>
              </div>
              <span className="shrink-0 font-mono text-sm">{money(e.amount)}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
