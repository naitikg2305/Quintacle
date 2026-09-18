"use client";

import { useEffect, useMemo, useState } from "react";
import { createInvestment, Investment, listInvestments } from "@/lib/api";

function fmtMoney(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

export default function InvestmentsPage() {
  const [holdings, setHoldings] = useState<Investment[]>([]);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("");
  const [shares, setShares] = useState("");
  const [costBasis, setCostBasis] = useState("");
  const [account, setAccount] = useState("");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);

  async function refresh() {
    setHoldings(await listInvestments());
  }

  useEffect(() => {
    refresh();
  }, []);

  const totalInvested = useMemo(
    () => holdings.reduce((sum, h) => sum + (h.shares != null && h.cost_basis != null ? h.shares * h.cost_basis : 0), 0),
    [holdings]
  );

  function resetForm() {
    setName("");
    setSymbol("");
    setShares("");
    setCostBasis("");
    setAccount("");
    setPurchaseDate("");
    setNotes("");
    setEditingName(null);
    setShowForm(false);
  }

  function startEdit(h: Investment) {
    setName(h.name);
    setSymbol(h.symbol);
    setShares(h.shares != null ? String(h.shares) : "");
    setCostBasis(h.cost_basis != null ? String(h.cost_basis) : "");
    setAccount(h.account);
    setPurchaseDate(h.purchase_date ?? "");
    setNotes(h.notes);
    setEditingName(h.name);
    setShowForm(true);
  }

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    await createInvestment({
      name,
      symbol,
      shares: shares ? Number(shares) : null,
      cost_basis: costBasis ? Number(costBasis) : null,
      account,
      purchase_date: purchaseDate || null,
      notes,
    });
    resetForm();
    await refresh();
    setBusy(false);
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Investments</h1>
          <p className="text-sm opacity-60">
            What you actually hold — total invested (cost basis): <strong>{fmtMoney(totalInvested)}</strong>. Not a live price
            tracker; update it yourself as positions change.
          </p>
        </div>
        <div className="flex gap-2">
          <a
            href={`/kb/folder?path=${encodeURIComponent("Organisation/Finance/Stocks & Investments")}`}
            className="text-xs border rounded px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5"
          >
            💬 Discuss stock strategy →
          </a>
          <button onClick={() => (showForm ? resetForm() : setShowForm(true))} className="border rounded px-3 py-1.5 text-sm">
            + Holding
          </button>
        </div>
      </div>

      {showForm && (
        <div className="border rounded p-4 space-y-2">
          <div className="flex gap-2">
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="name (e.g. Apple)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={editingName != null}
            />
            <input
              className="w-24 border rounded px-2 py-1 text-sm"
              placeholder="ticker"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            />
            <input
              type="date"
              className="border rounded px-2 py-1 text-sm"
              value={purchaseDate}
              onChange={(e) => setPurchaseDate(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <input
              type="number"
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="shares"
              value={shares}
              onChange={(e) => setShares(e.target.value)}
            />
            <input
              type="number"
              step="0.01"
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="cost basis / share"
              value={costBasis}
              onChange={(e) => setCostBasis(e.target.value)}
            />
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="account (e.g. Fidelity Roth IRA)"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
            />
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={3}
            placeholder="notes — why you bought it, strategy"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              onClick={submit}
              disabled={busy || !name.trim()}
              className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              {editingName ? "Save changes" : "Save holding"}
            </button>
            {editingName && (
              <button onClick={resetForm} className="border rounded px-4 py-2 text-sm">
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      <div className="space-y-2">
        {holdings.length === 0 && <p className="text-sm opacity-60">No holdings tracked yet.</p>}
        {holdings.map((h) => (
          <div key={h.slug} className="border rounded p-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-sm">{h.name}</span>
                {h.symbol && <span className="text-xs opacity-50">{h.symbol}</span>}
                {h.shares != null && <span className="text-xs opacity-50">{h.shares} shares</span>}
                {h.cost_basis != null && <span className="text-xs opacity-50">{fmtMoney(h.cost_basis)}/share</span>}
                {h.account && <span className="text-xs opacity-50">{h.account}</span>}
              </div>
              <button onClick={() => startEdit(h)} className="text-xs underline opacity-70 hover:opacity-100">
                edit
              </button>
            </div>
            {h.shares != null && h.cost_basis != null && (
              <p className="text-xs opacity-70 mt-1">invested: {fmtMoney(h.shares * h.cost_basis)}</p>
            )}
            {h.notes && <p className="text-sm mt-1 whitespace-pre-wrap">{h.notes}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
