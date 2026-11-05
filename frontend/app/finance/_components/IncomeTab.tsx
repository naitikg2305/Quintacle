"use client";

// Income tab: the old Insights view's income form + list, plus monthly
// income/savings from /finance/insights/monthly. Moved here 2026-11-05.

import { useEffect, useState } from "react";
import { getMonthlyInsights, Income, listIncome, logIncome, MonthlyInsight } from "@/lib/api";
import { todayIso, yearsAgoIso } from "@/lib/date";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Field";
import { Bar, money } from "./shared";

export default function IncomeTab() {
  const [rows, setRows] = useState<Income[]>([]);
  const [months, setMonths] = useState<MonthlyInsight[]>([]);
  const [showAll, setShowAll] = useState(false);

  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("");
  const [kind, setKind] = useState("salary");
  const [date, setDate] = useState(todayIso());
  const [busy, setBusy] = useState(false);

  async function load() {
    return Promise.all([listIncome(yearsAgoIso(1), todayIso()), getMonthlyInsights(12)]);
  }

  function apply([inc, mo]: Awaited<ReturnType<typeof load>>) {
    setRows(inc.slice().sort((a, b) => b.date.localeCompare(a.date)));
    setMonths(mo);
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
      await logIncome({ date, amount: Number(amount), source, kind });
      setAmount("");
      setSource("");
      setDate(todayIso());
      apply(await load());
    } finally {
      setBusy(false);
    }
  }

  const maxIncome = Math.max(...months.map((m) => m.income), 1);

  return (
    <div className="space-y-4">
      <Panel title="Log income">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-[8rem_1fr_8rem_10rem_auto]">
          <Input type="number" step="0.01" min="0" inputMode="decimal" placeholder="amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Input placeholder="source (employer, sale…)" value={source} onChange={(e) => setSource(e.target.value)} />
          <Select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="salary">salary</option>
            <option value="other">other</option>
          </Select>
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <Button size="sm" variant="primary" onClick={submit} disabled={busy || !amount || Number(amount) <= 0} className="col-span-2 md:col-span-1">
            Save income
          </Button>
        </div>
        <p className="mt-2 text-[11px] text-muted">also via Drop: &quot;income: 3200 Acme paycheck&quot; — parsed deterministically</p>
      </Panel>

      <Panel title="Monthly income & savings rate">
        <div className="space-y-1.5">
          {months.map((m) => (
            <div key={m.month} className="grid grid-cols-[4rem_1fr_5.5rem_3.5rem] items-center gap-2 text-sm">
              <span className="font-mono text-xs text-muted">{m.month}</span>
              <Bar value={m.income} max={maxIncome} barClassName="bg-ok" />
              <span className="text-right font-mono text-xs">{m.income > 0 ? money(m.income) : "—"}</span>
              <span className="text-right text-xs text-muted">{m.savings_rate_pct !== null ? `${m.savings_rate_pct}%` : "—"}</span>
            </div>
          ))}
        </div>
      </Panel>

      <Panel
        title="Income (last year)"
        actions={
          rows.length > 8 && (
            <Button size="sm" variant="ghost" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show recent" : `Show all ${rows.length}`}
            </Button>
          )
        }
      >
        {rows.length === 0 && <p className="text-sm text-muted">No income logged yet — savings rate needs it.</p>}
        <ul className="divide-y divide-line">
          {(showAll ? rows : rows.slice(0, 8)).map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <div className="min-w-0">
                <p className="truncate">
                  {r.source || "(unspecified)"}
                  <span className="ml-2 text-xs text-muted">{r.kind}</span>
                </p>
                <p className="font-mono text-[11px] text-muted">{r.date}</p>
              </div>
              <span className="shrink-0 font-mono">{money(r.amount)}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
