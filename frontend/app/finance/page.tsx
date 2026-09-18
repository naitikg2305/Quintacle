"use client";

import { useEffect, useMemo, useState } from "react";
import { Expense, FINANCE_KINDS, FinanceKind, listExpenses, logExpense } from "@/lib/api";

const TABS: { kind: FinanceKind; label: string }[] = [
  { kind: "subscription", label: "Subscriptions" },
  { kind: "food", label: "Food" },
  { kind: "alcohol", label: "Alcohol" },
  { kind: "experience", label: "Experience" },
  { kind: "shopping", label: "Shopping" },
  { kind: "big_purchase", label: "Big Purchases" },
  { kind: "regular", label: "Regular" },
];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function twoYearsAgo(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 2);
  return d.toISOString().slice(0, 10);
}

function fmt(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

export default function FinancePage() {
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [tab, setTab] = useState<FinanceKind>("subscription");

  const [showForm, setShowForm] = useState(false);
  const [amount, setAmount] = useState("");
  const [merchant, setMerchant] = useState("");
  const [category, setCategory] = useState("");
  const [kind, setKind] = useState<FinanceKind>("regular");
  const [entryDate, setEntryDate] = useState(today());
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setExpenses(await listExpenses(twoYearsAgo(), today()));
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
    setEntryDate(today());
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
      </div>

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
    </div>
  );
}
