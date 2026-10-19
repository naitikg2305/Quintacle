"use client";

import { useEffect, useMemo, useState } from "react";
import {
  DetectedSubscription,
  Expense,
  FINANCE_KINDS,
  FinanceKind,
  getDetectedSubscriptions,
  getMerchantMovers,
  getMerchantRollup,
  getMonthlyInsights,
  Income,
  listExpenses,
  listIncome,
  logExpense,
  logIncome,
  MerchantMover,
  MerchantRollup,
  MonthlyInsight,
} from "@/lib/api";
import { todayIso, yearsAgoIso } from "@/lib/date";

const TABS: { kind: FinanceKind; label: string }[] = [
  { kind: "subscription", label: "Subscriptions" },
  { kind: "food", label: "Food" },
  { kind: "alcohol", label: "Alcohol" },
  { kind: "experience", label: "Experience" },
  { kind: "shopping", label: "Shopping" },
  { kind: "big_purchase", label: "Big Purchases" },
  { kind: "regular", label: "Regular" },
];

function fmt(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function fmtDelta(n: number | null): string {
  if (n === null) return "—";
  return `${n > 0 ? "▲" : n < 0 ? "▼" : "·"} ${fmt(Math.abs(n))}`;
}

// A quiet proportional bar in the page's own style — value / max of its group.
// Every number shown next to it comes computed from the backend.
function Bar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full rounded-full bg-black/10 dark:bg-white/10">
      <div className="h-full rounded-full bg-black/70 dark:bg-white/70" style={{ width: `${pct}%` }} />
    </div>
  );
}

type InsightsData = {
  months: MonthlyInsight[];
  merchants: MerchantRollup[];
  movers: MerchantMover[];
  subs: { subscriptions: DetectedSubscription[]; monthly_burn: number };
  incomeRows: Income[];
};

// One fetch for everything the tab shows — every figure is computed in
// SQL/code on the backend; this only gathers and renders.
async function fetchInsightsData(): Promise<InsightsData> {
  const today = todayIso();
  const [y, m] = today.split("-").map(Number);
  const rollupStart = `${String(m - 3 <= 0 ? y - 1 : y).padStart(4, "0")}-${String(((m - 4 + 12) % 12) + 1).padStart(2, "0")}-01`;
  const [months, merchants, movers, subs, income] = await Promise.all([
    getMonthlyInsights(12),
    getMerchantRollup(rollupStart, today),
    getMerchantMovers(10),
    getDetectedSubscriptions(),
    listIncome(yearsAgoIso(1), today),
  ]);
  return { months, merchants, movers, subs, incomeRows: income.slice().sort((a, b) => b.date.localeCompare(a.date)) };
}

// Deterministic insights (next-wave-plan §1): rendering only, zero local math
// beyond display scaling.
function InsightsView() {
  const [data, setData] = useState<InsightsData | null>(null);

  const [incomeAmount, setIncomeAmount] = useState("");
  const [incomeSource, setIncomeSource] = useState("");
  const [incomeKind, setIncomeKind] = useState("salary");
  const [incomeDate, setIncomeDate] = useState(todayIso());
  const [incomeBusy, setIncomeBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchInsightsData().then((d) => {
      if (!cancelled) setData(d);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submitIncome() {
    if (!incomeAmount || Number(incomeAmount) <= 0) return;
    setIncomeBusy(true);
    await logIncome({ date: incomeDate, amount: Number(incomeAmount), source: incomeSource, kind: incomeKind });
    setIncomeAmount("");
    setIncomeSource("");
    setIncomeDate(todayIso());
    setData(await fetchInsightsData());
    setIncomeBusy(false);
  }

  const months = data?.months ?? [];
  const merchants = data?.merchants ?? [];
  const movers = data?.movers ?? [];
  const subs = data?.subs ?? null;
  const incomeRows = data?.incomeRows ?? [];

  const current = months[months.length - 1];
  const maxMonthTotal = Math.max(...months.map((m) => m.total), 1);
  const maxKind = current ? Math.max(...FINANCE_KINDS.map((k) => current.by_kind[k]), 1) : 1;
  const maxMerchant = Math.max(...merchants.map((m) => m.total), 1);

  return (
    <div className="space-y-6">
      {current && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="border rounded p-3">
            <p className="text-xs opacity-60">Spent this month</p>
            <p className="text-lg font-semibold">{fmt(current.total)}</p>
            <p className="text-xs opacity-60">{fmtDelta(current.delta_total)} vs last month</p>
          </div>
          <div className="border rounded p-3">
            <p className="text-xs opacity-60">Income this month</p>
            <p className="text-lg font-semibold">{fmt(current.income)}</p>
          </div>
          <div className="border rounded p-3">
            <p className="text-xs opacity-60">Savings rate</p>
            <p className="text-lg font-semibold">
              {current.savings_rate_pct !== null ? `${current.savings_rate_pct}%` : "—"}
            </p>
            <p className="text-xs opacity-60">{fmt(current.savings)} kept</p>
          </div>
          <div className="border rounded p-3">
            <p className="text-xs opacity-60">Subscription burn</p>
            <p className="text-lg font-semibold">{subs ? `${fmt(subs.monthly_burn)}/mo` : "—"}</p>
            <p className="text-xs opacity-60">{subs ? `${subs.subscriptions.filter((s) => s.active).length} active detected` : ""}</p>
          </div>
        </div>
      )}

      {current && (
        <div className="border rounded p-4 space-y-2">
          <h2 className="font-medium text-sm">This month by kind</h2>
          {TABS.map((t) => {
            const value = current.by_kind[t.kind];
            const delta = current.delta_by_kind?.[t.kind] ?? null;
            return (
              <div key={t.kind} className="grid grid-cols-[7rem_1fr_6rem_6rem] items-center gap-2 text-sm">
                <span className="opacity-70">{t.label}</span>
                <Bar value={value} max={maxKind} />
                <span className="text-right font-medium">{fmt(value)}</span>
                <span className="text-right text-xs opacity-60">{fmtDelta(delta)}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="border rounded p-4 space-y-2">
        <h2 className="font-medium text-sm">Monthly spend, income &amp; savings (last {months.length} months)</h2>
        <div className="space-y-1.5">
          {months.map((m) => (
            <div key={m.month} className="grid grid-cols-[4.5rem_1fr_6rem_6rem_4rem] items-center gap-2 text-sm">
              <span className="font-mono text-xs opacity-70">{m.month}</span>
              <Bar value={m.total} max={maxMonthTotal} />
              <span className="text-right">{fmt(m.total)}</span>
              <span className="text-right opacity-70">{m.income > 0 ? fmt(m.income) : "—"}</span>
              <span className="text-right text-xs opacity-60">{m.savings_rate_pct !== null ? `${m.savings_rate_pct}%` : "—"}</span>
            </div>
          ))}
        </div>
        <p className="text-xs opacity-50">columns: spend · income · savings rate — all computed server-side, no model involved</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="border rounded p-4 space-y-2">
          <h2 className="font-medium text-sm">Top merchants (last ~3 months)</h2>
          {merchants.length === 0 && <p className="text-sm opacity-60">No expenses in range.</p>}
          {merchants.slice(0, 12).map((m) => (
            <div key={m.merchant} className="grid grid-cols-[1fr_5.5rem] items-center gap-2 text-sm">
              <div className="min-w-0">
                <div className="flex justify-between gap-2">
                  <span className="truncate">{m.merchant}</span>
                  <span className="text-xs opacity-60 shrink-0">
                    {m.count}× · avg {fmt(m.average)}
                  </span>
                </div>
                <Bar value={m.total} max={maxMerchant} />
              </div>
              <span className="text-right font-medium">{fmt(m.total)}</span>
            </div>
          ))}
        </div>

        <div className="border rounded p-4 space-y-2">
          <h2 className="font-medium text-sm">Biggest movers (this month vs last)</h2>
          {movers.length === 0 && <p className="text-sm opacity-60">Nothing to compare yet.</p>}
          {movers.map((m) => (
            <div key={m.merchant} className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">{m.merchant}</span>
              <span className="text-xs opacity-60 shrink-0">
                {fmt(m.last_month)} → {fmt(m.this_month)}
              </span>
              <span className={`text-right font-medium shrink-0 w-24 ${m.delta > 0 ? "" : "opacity-70"}`}>{fmtDelta(m.delta)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="border rounded p-4 space-y-2">
        <h2 className="font-medium text-sm">Detected recurring charges</h2>
        <p className="text-xs opacity-60">
          Same merchant + similar amount at a steady cadence — recurrence arithmetic over the ledger, no AI judgment.
        </p>
        {subs && subs.subscriptions.length === 0 && <p className="text-sm opacity-60">No recurring charges detected yet.</p>}
        {subs?.subscriptions.map((s) => (
          <div key={`${s.merchant}-${s.amount}`} className="border rounded p-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <span className="font-medium text-sm">{s.merchant}</span>
              <p className="text-xs opacity-60 mt-0.5">
                {fmt(s.amount)} {s.cadence} · {s.charges} charges · next expected {s.next_expected}
                {!s.kind_already_subscription && " · not kind=subscription in the ledger"}
              </p>
            </div>
            <div className="text-right">
              <span className="text-sm font-medium">{fmt(s.monthly_equivalent)}/mo</span>
              <p className={`text-xs ${s.active ? "opacity-60" : "opacity-40"}`}>{s.active ? "active" : "lapsed"}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="border rounded p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-sm">Income</h2>
          <span className="text-xs opacity-60">
            also via Drop: &quot;income: 3200 Acme paycheck&quot; — parsed deterministically
          </span>
        </div>
        <div className="flex gap-2 flex-wrap">
          <input
            type="number"
            step="0.01"
            min="0"
            className="border rounded px-2 py-1 text-sm w-28"
            placeholder="amount"
            value={incomeAmount}
            onChange={(e) => setIncomeAmount(e.target.value)}
          />
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="source (employer, sale...)"
            value={incomeSource}
            onChange={(e) => setIncomeSource(e.target.value)}
          />
          <select className="border rounded px-2 py-1 text-sm" value={incomeKind} onChange={(e) => setIncomeKind(e.target.value)}>
            <option value="salary">salary</option>
            <option value="other">other</option>
          </select>
          <input type="date" className="border rounded px-2 py-1 text-sm" value={incomeDate} onChange={(e) => setIncomeDate(e.target.value)} />
          <button
            onClick={submitIncome}
            disabled={incomeBusy || !incomeAmount || Number(incomeAmount) <= 0}
            className="bg-black text-white dark:bg-white dark:text-black rounded px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Save income
          </button>
        </div>
        <div className="space-y-1">
          {incomeRows.length === 0 && <p className="text-sm opacity-60">No income logged yet — savings rate needs it.</p>}
          {incomeRows.slice(0, 8).map((r) => (
            <div key={r.id} className="border rounded p-2.5 flex items-center justify-between gap-3 text-sm">
              <div>
                <span className="font-medium">{r.source || "(unspecified)"}</span>
                <span className="text-xs opacity-50 ml-2">{r.kind}</span>
                <p className="text-xs opacity-50 mt-0.5">{r.date}</p>
              </div>
              <span className="font-medium shrink-0">{fmt(r.amount)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function FinancePage() {
  const [view, setView] = useState<"ledger" | "insights">("ledger");
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [tab, setTab] = useState<FinanceKind>("subscription");

  const [showForm, setShowForm] = useState(false);
  const [amount, setAmount] = useState("");
  const [merchant, setMerchant] = useState("");
  const [category, setCategory] = useState("");
  const [kind, setKind] = useState<FinanceKind>("regular");
  const [entryDate, setEntryDate] = useState(todayIso());
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setExpenses(await listExpenses(yearsAgoIso(2), todayIso()));
  }

  useEffect(() => {
    refresh();
  }, []);

  async function submit() {
    if (!amount || Number(amount) <= 0) return;
    setBusy(true);
    await logExpense({ date: entryDate, amount: Number(amount), merchant, category, notes, kind });
    setAmount("");
    setMerchant("");
    setCategory("");
    setNotes("");
    setKind("regular");
    setEntryDate(todayIso());
    setShowForm(false);
    await refresh();
    setBusy(false);
  }

  const byKind = useMemo(() => {
    const grouped = new Map<FinanceKind, Expense[]>();
    for (const t of TABS) grouped.set(t.kind, []);
    for (const e of expenses) {
      const list = grouped.get(e.kind) ?? grouped.get("regular")!;
      list.push(e);
    }
    for (const list of grouped.values()) list.sort((a, b) => b.date.localeCompare(a.date));
    return grouped;
  }, [expenses]);

  const grandTotal = expenses.reduce((sum, e) => sum + e.amount, 0);
  const visible = byKind.get(tab) ?? [];
  const tabTotal = visible.reduce((sum, e) => sum + e.amount, 0);

  const subscriptionGroups = useMemo(() => {
    if (tab !== "subscription") return [];
    const groups = new Map<string, Expense[]>();
    for (const e of visible) {
      const key = e.merchant.trim().toLowerCase() || "(unnamed)";
      const list = groups.get(key) ?? [];
      list.push(e);
      groups.set(key, list);
    }
    return Array.from(groups.entries())
      .map(([key, items]) => ({
        merchant: items[0].merchant || "(unnamed)",
        count: items.length,
        lastAmount: items[0].amount,
        lastDate: items[0].date,
        avgMonthly: items.reduce((s, e) => s + e.amount, 0) / items.length,
        items,
      }))
      .sort((a, b) => b.avgMonthly - a.avgMonthly);
  }, [tab, visible]);

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold">Finance</h1>
      <p className="text-sm opacity-60 -mt-4">
        Expenses logged manually or via Drop, bucketed by kind. Total tracked (last 2 years): <strong>{fmt(grandTotal)}</strong>
      </p>

      <div className="border rounded p-3 flex flex-wrap gap-3 items-center text-sm">
        <span className="opacity-70">Investments &amp; planning notes live in the Knowledge Base —</span>
        <a
          href={`/kb/folder?path=${encodeURIComponent("Organisation/Finance/Stocks & Investments")}`}
          className="underline hover:opacity-80"
        >
          Stocks &amp; Investments →
        </a>
        <a
          href={`/kb/folder?path=${encodeURIComponent("Organisation/Finance/Life Planning")}`}
          className="underline hover:opacity-80"
        >
          Life Planning (savings/down payment goals) →
        </a>
        <a href="/finance/cards" className="underline hover:opacity-80">
          Credit Cards (benefits &amp; points) →
        </a>
        <a href="/finance/investments" className="underline hover:opacity-80">
          Investments (what you actually hold) →
        </a>
        <a href="/kb/drop" className="underline hover:opacity-80" title="Drop a CSV/OFX/QFX export (or a PDF with a 'statement:' note) — parsed, deduped, and reviewed before anything is written">
          Import a statement (via Drop) →
        </a>
      </div>

      <div className="flex items-center gap-2">
        {(["ledger", "insights"] as const).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`border rounded px-3 py-1.5 text-sm capitalize ${
              view === v ? "bg-black text-white dark:bg-white dark:text-black" : "hover:bg-black/5 dark:hover:bg-white/5"
            }`}
          >
            {v}
          </button>
        ))}
        <span className="text-xs opacity-50 ml-2">
          {view === "insights" ? "how the money actually moves — all computed, zero AI" : "every expense, by kind"}
        </span>
      </div>

      {view === "insights" ? (
        <InsightsView />
      ) : (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            {TABS.map((t) => {
              const count = byKind.get(t.kind)?.length ?? 0;
              return (
                <button
                  key={t.kind}
                  onClick={() => setTab(t.kind)}
                  className={`border rounded px-3 py-1.5 text-sm ${
                    tab === t.kind ? "bg-black text-white dark:bg-white dark:text-black" : "hover:bg-black/5 dark:hover:bg-white/5"
                  }`}
                >
                  {t.label}
                  {count > 0 && <span className="opacity-60 ml-1">({count})</span>}
                </button>
              );
            })}
            <button onClick={() => setShowForm((s) => !s)} className="border rounded px-3 py-1.5 text-sm ml-auto">
              + Expense
            </button>
          </div>

          {showForm && (
            <div className="border rounded p-4 space-y-2">
              <div className="flex gap-2 flex-wrap">
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="border rounded px-2 py-1 text-sm w-28"
                  placeholder="amount"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
                <input
                  className="border rounded px-2 py-1 text-sm flex-1"
                  placeholder="merchant"
                  value={merchant}
                  onChange={(e) => setMerchant(e.target.value)}
                />
                <input
                  className="border rounded px-2 py-1 text-sm w-32"
                  placeholder="category"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                />
                <select className="border rounded px-2 py-1 text-sm" value={kind} onChange={(e) => setKind(e.target.value as FinanceKind)}>
                  {FINANCE_KINDS.map((k) => (
                    <option key={k} value={k}>
                      {k.replace("_", " ")}
                    </option>
                  ))}
                </select>
                <input
                  type="date"
                  className="border rounded px-2 py-1 text-sm"
                  value={entryDate}
                  onChange={(e) => setEntryDate(e.target.value)}
                />
              </div>
              <textarea
                className="w-full border rounded p-2 text-sm"
                rows={2}
                placeholder="notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
              <button
                onClick={submit}
                disabled={busy || !amount || Number(amount) <= 0}
                className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
              >
                Save expense
              </button>
            </div>
          )}

          <div className="border rounded p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-sm">{TABS.find((t) => t.kind === tab)?.label}</h2>
              <span className="text-sm opacity-70">{fmt(tabTotal)}</span>
            </div>

            {tab === "subscription" ? (
              <div className="space-y-2">
                {subscriptionGroups.length === 0 && <p className="text-sm opacity-60">No subscriptions logged yet.</p>}
                {subscriptionGroups.map((g) => (
                  <div key={g.merchant} className="border rounded p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-sm">{g.merchant}</span>
                      <span className="text-sm">~{fmt(g.avgMonthly)}/charge</span>
                    </div>
                    <p className="text-xs opacity-60 mt-1">
                      {g.count} charge{g.count === 1 ? "" : "s"} logged · last {fmt(g.lastAmount)} on {g.lastDate}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-1">
                {visible.length === 0 && <p className="text-sm opacity-60">Nothing here yet.</p>}
                {visible.map((e) => (
                  <div key={e.id} className="border rounded p-3 flex items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{e.merchant || "(unspecified)"}</span>
                        {e.category && <span className="text-xs opacity-50">{e.category}</span>}
                      </div>
                      {e.notes && <p className="text-xs opacity-70 mt-1">{e.notes}</p>}
                      <p className="text-xs opacity-50 mt-1">{e.date}</p>
                    </div>
                    <span className="text-sm font-medium shrink-0">{fmt(e.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
