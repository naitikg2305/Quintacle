"use client";

import { useEffect, useState } from "react";
import {
  createStockResearch,
  deleteStockTransaction,
  listStockResearch,
  listStockTransactions,
  logStockTransaction,
  refreshStockPrices,
  STOCK_ACTIONS,
  StockAction,
  StockPositions,
  StockResearchNote,
  StockTransaction,
} from "@/lib/api";
import { stockPositions } from "@/lib/api";
import { todayIso } from "@/lib/date";

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function pnlClass(n: number | null | undefined): string {
  if (n == null || n === 0) return "";
  return n > 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400";
}

const STATUS_LABELS: Record<StockResearchNote["status"], string> = {
  owned: "owned",
  watching: "watching",
  passed: "passed — kept for re-evaluation",
};

export default function StocksPage() {
  const [positions, setPositions] = useState<StockPositions | null>(null);
  const [transactions, setTransactions] = useState<StockTransaction[]>([]);
  const [research, setResearch] = useState<StockResearchNote[]>([]);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshErrors, setRefreshErrors] = useState<string[]>([]);

  const [showTxForm, setShowTxForm] = useState(false);
  const [txDate, setTxDate] = useState(todayIso());
  const [action, setAction] = useState<StockAction>("buy");
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("");
  const [account, setAccount] = useState("");
  const [txNotes, setTxNotes] = useState("");
  const [txBusy, setTxBusy] = useState(false);

  const [showResearchForm, setShowResearchForm] = useState(false);
  const [resSymbol, setResSymbol] = useState("");
  const [resStatus, setResStatus] = useState<StockResearchNote["status"]>("watching");
  const [resContent, setResContent] = useState("");
  const [resBusy, setResBusy] = useState(false);

  async function reload() {
    const [pos, txs, notes] = await Promise.all([stockPositions(), listStockTransactions(), listStockResearch()]);
    setPositions(pos);
    setTransactions(txs.slice().sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id));
    setResearch(notes);
  }

  useEffect(() => {
    // setState only ever inside the .then callback — keeps this page from
    // adding another react-hooks/set-state-in-effect to the pre-existing pile.
    let cancelled = false;
    Promise.all([stockPositions(), listStockTransactions(), listStockResearch()]).then(([pos, txs, notes]) => {
      if (cancelled) return;
      setPositions(pos);
      setTransactions(txs.slice().sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id));
      setResearch(notes);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function refreshPrices() {
    setRefreshBusy(true);
    setRefreshErrors([]);
    try {
      const result = await refreshStockPrices();
      setRefreshErrors(result.results.filter((r) => "error" in r).map((r) => `${r.symbol}: ${(r as { error: string }).error}`));
      await reload();
    } finally {
      setRefreshBusy(false);
    }
  }

  const txValid =
    symbol.trim() !== "" &&
    (action === "dividend" ? Number(price) > 0 : Number(qty) > 0 && Number(price) >= 0);

  async function submitTransaction() {
    if (!txValid) return;
    setTxBusy(true);
    try {
      await logStockTransaction({
        date: txDate,
        action,
        symbol: symbol.trim(),
        qty: action === "dividend" ? 0 : Number(qty),
        price: Number(price) || 0,
        fees: Number(fees) || 0,
        account,
        notes: txNotes,
      });
      setSymbol("");
      setQty("");
      setPrice("");
      setFees("");
      setTxNotes("");
      setShowTxForm(false);
      await reload();
    } finally {
      setTxBusy(false);
    }
  }

  async function removeTransaction(id: number) {
    await deleteStockTransaction(id);
    await reload();
  }

  async function submitResearch() {
    if (!resSymbol.trim()) return;
    setResBusy(true);
    try {
      await createStockResearch({ symbol: resSymbol.trim(), status: resStatus, content: resContent });
      setResSymbol("");
      setResContent("");
      setResStatus("watching");
      setShowResearchForm(false);
      await reload();
    } finally {
      setResBusy(false);
    }
  }

  const researchBySymbol = new Map(research.map((r) => [r.symbol, r]));
  const open = positions?.positions.filter((p) => p.qty > 0) ?? [];
  const closed = positions?.positions.filter((p) => p.qty <= 0) ?? [];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Stocks</h1>
          <p className="text-sm opacity-60">
            Positions, cost basis and P&L are computed from the transaction ledger — nothing here is hand-maintained.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs opacity-60">
            {positions?.prices_as_of ? `prices as of ${positions.prices_as_of} (EOD)` : "no price snapshot yet"}
          </span>
          <button onClick={refreshPrices} disabled={refreshBusy} className="border rounded px-3 py-1.5 text-sm disabled:opacity-40">
            {refreshBusy ? "Fetching…" : "↻ Refresh prices"}
          </button>
        </div>
      </div>

      {refreshErrors.length > 0 && (
        <div className="border border-amber-500/50 rounded p-3 text-xs space-y-1">
          <p className="opacity-80">Some prices couldn&apos;t be fetched — showing the last stored snapshot instead:</p>
          {refreshErrors.map((e) => (
            <p key={e} className="opacity-60">
              {e}
            </p>
          ))}
        </div>
      )}

      {positions && (
        <div className="border rounded p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-medium text-sm">Positions</h2>
            <div className="text-xs opacity-70 flex gap-4">
              <span>invested {fmt(positions.totals.cost_basis)}</span>
              <span>value {positions.totals.priced_symbols > 0 ? fmt(positions.totals.market_value) : "—"}</span>
              <span className={pnlClass(positions.totals.unrealized_pnl)}>
                unrealized {positions.totals.priced_symbols > 0 ? fmt(positions.totals.unrealized_pnl) : "—"}
              </span>
              <span className={pnlClass(positions.totals.realized_pnl)}>realized {fmt(positions.totals.realized_pnl)}</span>
              <span>dividends {fmt(positions.totals.dividends)}</span>
            </div>
          </div>

          {open.length === 0 && <p className="text-sm opacity-60">No open positions — log a buy to start the ledger.</p>}
          {open.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs opacity-50 text-left">
                    <th className="py-1 pr-3 font-normal">Symbol</th>
                    <th className="py-1 pr-3 font-normal text-right">Qty</th>
                    <th className="py-1 pr-3 font-normal text-right">Avg cost</th>
                    <th className="py-1 pr-3 font-normal text-right">Cost basis</th>
                    <th className="py-1 pr-3 font-normal text-right">Last price</th>
                    <th className="py-1 pr-3 font-normal text-right">Value</th>
                    <th className="py-1 pr-3 font-normal text-right">Unrealized</th>
                    <th className="py-1 pr-3 font-normal text-right">Realized</th>
                    <th className="py-1 pr-3 font-normal text-right">Dividends</th>
                    <th className="py-1 font-normal">Research</th>
                  </tr>
                </thead>
                <tbody>
                  {open.map((p) => {
                    const note = researchBySymbol.get(p.symbol);
                    return (
                      <tr key={p.symbol} className="border-t border-black/10 dark:border-white/10">
                        <td className="py-1.5 pr-3 font-medium">
                          {p.symbol}
                          {p.oversold && (
                            <span className="ml-1 text-xs text-red-600 dark:text-red-400" title="Sells exceed recorded buys — check the ledger">
                              ⚠ oversold
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 pr-3 text-right">{p.qty}</td>
                        <td className="py-1.5 pr-3 text-right">{fmt(p.avg_cost)}</td>
                        <td className="py-1.5 pr-3 text-right">{fmt(p.cost_basis)}</td>
                        <td className="py-1.5 pr-3 text-right">
                          {fmt(p.last_price)}
                          {p.last_price_date && <span className="block text-[10px] opacity-50">{p.last_price_date}</span>}
                        </td>
                        <td className="py-1.5 pr-3 text-right">{fmt(p.market_value)}</td>
                        <td className={`py-1.5 pr-3 text-right ${pnlClass(p.unrealized_pnl)}`}>{fmt(p.unrealized_pnl)}</td>
                        <td className={`py-1.5 pr-3 text-right ${pnlClass(p.realized_pnl)}`}>{fmt(p.realized_pnl)}</td>
                        <td className="py-1.5 pr-3 text-right">{fmt(p.dividends)}</td>
                        <td className="py-1.5">
                          {note ? (
                            <a href={`/kb/folder?path=${encodeURIComponent(note.folder)}`} className="underline text-xs hover:opacity-80">
                              thesis →
                            </a>
                          ) : (
                            <span className="text-xs opacity-40">none</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {closed.length > 0 && (
            <div className="text-xs opacity-70 space-y-1 pt-1 border-t border-black/10 dark:border-white/10">
              <p className="opacity-70">Closed positions</p>
              {closed.map((p) => (
                <p key={p.symbol}>
                  {p.symbol} — realized <span className={pnlClass(p.realized_pnl)}>{fmt(p.realized_pnl)}</span>
                  {p.dividends > 0 && <> · dividends {fmt(p.dividends)}</>}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="border rounded p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-sm">Transactions</h2>
          <button onClick={() => setShowTxForm((s) => !s)} className="border rounded px-3 py-1.5 text-sm">
            + Transaction
          </button>
        </div>

        {showTxForm && (
          <div className="border rounded p-3 space-y-2">
            <div className="flex gap-2 flex-wrap">
              <input type="date" className="border rounded px-2 py-1 text-sm" value={txDate} onChange={(e) => setTxDate(e.target.value)} />
              <select className="border rounded px-2 py-1 text-sm" value={action} onChange={(e) => setAction(e.target.value as StockAction)}>
                {STOCK_ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
              <input
                className="border rounded px-2 py-1 text-sm w-24 uppercase"
                placeholder="ticker"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
              />
              {action !== "dividend" && (
                <input
                  type="number"
                  min="0"
                  step="any"
                  className="border rounded px-2 py-1 text-sm w-24"
                  placeholder="qty"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                />
              )}
              <input
                type="number"
                min="0"
                step="0.01"
                className="border rounded px-2 py-1 text-sm w-32"
                placeholder={action === "dividend" ? "total received" : "price / share"}
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
              <input
                type="number"
                min="0"
                step="0.01"
                className="border rounded px-2 py-1 text-sm w-24"
                placeholder="fees"
                value={fees}
                onChange={(e) => setFees(e.target.value)}
              />
              <input
                className="border rounded px-2 py-1 text-sm flex-1"
                placeholder="account (e.g. Fidelity Roth IRA)"
                value={account}
                onChange={(e) => setAccount(e.target.value)}
              />
            </div>
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={2}
              placeholder="notes"
              value={txNotes}
              onChange={(e) => setTxNotes(e.target.value)}
            />
            <button
              onClick={submitTransaction}
              disabled={txBusy || !txValid}
              className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Save transaction
            </button>
          </div>
        )}

        <div className="space-y-1">
          {transactions.length === 0 && <p className="text-sm opacity-60">No transactions yet.</p>}
          {transactions.map((t) => (
            <div key={t.id} className="border rounded p-3 flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm">{t.symbol}</span>
                  <span className={`text-xs rounded px-1.5 py-0.5 border ${t.action === "sell" ? "opacity-80" : "opacity-60"}`}>
                    {t.action}
                  </span>
                  {t.action !== "dividend" && <span className="text-xs opacity-60">{t.qty} sh</span>}
                  <span className="text-xs opacity-60">
                    {t.action === "dividend" ? `${fmt(t.price)} received` : `@ ${fmt(t.price)}`}
                  </span>
                  {t.fees > 0 && <span className="text-xs opacity-50">fees {fmt(t.fees)}</span>}
                  {t.account && <span className="text-xs opacity-50">{t.account}</span>}
                </div>
                {t.notes && <p className="text-xs opacity-70 mt-1">{t.notes}</p>}
                <p className="text-xs opacity-50 mt-1">{t.date}</p>
              </div>
              <button onClick={() => removeTransaction(t.id)} className="text-xs underline opacity-50 hover:opacity-100 shrink-0">
                delete
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="border rounded p-4 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="font-medium text-sm">Research</h2>
            <p className="text-xs opacity-60">
              One folder per company — theses stay even for companies you passed on; that reasoning is half the value at
              re-evaluation.
            </p>
          </div>
          <div className="flex gap-2">
            <a
              href={`/kb/folder?path=${encodeURIComponent("Organisation/Finance/Stocks Research")}`}
              className="text-xs border rounded px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5"
            >
              Browse all research →
            </a>
            <button onClick={() => setShowResearchForm((s) => !s)} className="border rounded px-3 py-1.5 text-sm">
              + Thesis
            </button>
          </div>
        </div>

        {showResearchForm && (
          <div className="border rounded p-3 space-y-2">
            <div className="flex gap-2 flex-wrap">
              <input
                className="border rounded px-2 py-1 text-sm w-24 uppercase"
                placeholder="ticker"
                value={resSymbol}
                onChange={(e) => setResSymbol(e.target.value)}
              />
              <select
                className="border rounded px-2 py-1 text-sm"
                value={resStatus}
                onChange={(e) => setResStatus(e.target.value as StockResearchNote["status"])}
              >
                <option value="owned">owned</option>
                <option value="watching">watching</option>
                <option value="passed">passed (researched, not buying)</option>
              </select>
            </div>
            <textarea
              className="w-full border rounded p-2 text-sm"
              rows={4}
              placeholder="the thesis — why buy (or why pass)"
              value={resContent}
              onChange={(e) => setResContent(e.target.value)}
            />
            <button
              onClick={submitResearch}
              disabled={resBusy || !resSymbol.trim()}
              className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Save thesis
            </button>
          </div>
        )}

        <div className="space-y-1">
          {research.length === 0 && <p className="text-sm opacity-60">No research notes yet.</p>}
          {research.map((r) => (
            <div key={`${r.folder}/${r.slug}`} className="border rounded p-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-sm">{r.symbol}</span>
                <span className="text-xs opacity-60">{r.title}</span>
                <span
                  className={`text-xs rounded px-1.5 py-0.5 border ${
                    r.status === "passed" ? "opacity-50" : r.status === "owned" ? "" : "opacity-70"
                  }`}
                >
                  {STATUS_LABELS[r.status] ?? r.status}
                </span>
              </div>
              <a href={`/kb/folder?path=${encodeURIComponent(r.folder)}`} className="text-xs underline opacity-70 hover:opacity-100 shrink-0">
                open folder →
              </a>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
