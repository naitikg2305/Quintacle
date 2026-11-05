"use client";

// Investments tab of the unified Finances page (2026-11-05; briefly its own
// /investments page earlier the same day, before the owner folded it into
// Finances). The stock ledger (nodes/stocks) — totals, holdings, recent
// transactions, add-transaction, an allocation donut — plus the recorded
// brokerage/retirement account balances from the Accounts tab. Every number
// (basis, value, P/L, P/L %, allocation %) is COMPUTED server-side; this only
// formats. The future "stocks discusser" (news + hunches per ticker) gets the
// placeholder card at the bottom. Research-note creation still lives on the
// backend (/stocks/research) — untouched, just not surfaced here for now.

import { useEffect, useState } from "react";
import { Lightbulb, Plus, RefreshCw, Trash2, TrendingUp, X } from "lucide-react";
import {
  ACCOUNT_TYPE_LABELS,
  AccountsSummary,
  deleteStockTransaction,
  getAccounts,
  listStockTransactions,
  logStockTransaction,
  refreshStockPrices,
  STOCK_ACTIONS,
  StockAction,
  StockPosition,
  stockPositions,
  StockPositions,
  StockTransaction,
} from "@/lib/api";
import { todayIso } from "@/lib/date";
import { Badge, EmptyState, Panel, Stat } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Field";
import { cn } from "@/lib/cn";
import { Donut, FieldLabel, money, pct, SLICE_COLORS, toneOf as tone, toneText } from "./shared";

const shares = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 6 });

function sortTxs(txs: StockTransaction[]) {
  return txs.slice().sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
}

export default function InvestmentsTab() {
  const [positions, setPositions] = useState<StockPositions | null>(null);
  const [accounts, setAccounts] = useState<AccountsSummary | null>(null);
  const [transactions, setTransactions] = useState<StockTransaction[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshErrors, setRefreshErrors] = useState<string[]>([]);
  const [showAll, setShowAll] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [txDate, setTxDate] = useState(todayIso());
  const [action, setAction] = useState<StockAction>("buy");
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("");
  const [account, setAccount] = useState("");
  const [notes, setNotes] = useState("");
  const [txBusy, setTxBusy] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);

  async function reload() {
    const [pos, txs, accts] = await Promise.all([stockPositions(), listStockTransactions(), getAccounts()]);
    setPositions(pos);
    setTransactions(sortTxs(txs));
    setAccounts(accts);
  }

  useEffect(() => {
    // setState only inside the .then — no new react-hooks/set-state-in-effect.
    let cancelled = false;
    Promise.all([stockPositions(), listStockTransactions(), getAccounts()])
      .then(([pos, txs, accts]) => {
        if (cancelled) return;
        setPositions(pos);
        setTransactions(sortTxs(txs));
        setAccounts(accts);
      })
      .catch((e) => !cancelled && setLoadError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  async function refreshPrices() {
    setRefreshBusy(true);
    setRefreshErrors([]);
    try {
      const result = await refreshStockPrices();
      setRefreshErrors(
        result.results.filter((r) => "error" in r).map((r) => `${r.symbol}: ${(r as { error: string }).error}`)
      );
      await reload();
    } catch (e) {
      setRefreshErrors([String(e)]);
    } finally {
      setRefreshBusy(false);
    }
  }

  const isDividend = action === "dividend";
  const txValid = symbol.trim() !== "" && (isDividend ? Number(price) > 0 : Number(qty) > 0 && Number(price) >= 0);

  async function submit() {
    if (!txValid) return;
    setTxBusy(true);
    setTxError(null);
    try {
      await logStockTransaction({
        date: txDate,
        action,
        symbol: symbol.trim(),
        qty: isDividend ? 0 : Number(qty),
        price: Number(price) || 0,
        fees: Number(fees) || 0,
        account,
        notes,
      });
      setSymbol("");
      setQty("");
      setPrice("");
      setFees("");
      setNotes("");
      setShowForm(false);
      await reload();
    } catch (e) {
      setTxError(String(e));
    } finally {
      setTxBusy(false);
    }
  }

  async function remove(tx: StockTransaction) {
    if (!confirm(`Delete ${tx.action} ${tx.symbol} on ${tx.date}?`)) return;
    await deleteStockTransaction(tx.id);
    await reload();
  }

  const totals = positions?.totals;
  const open = positions?.positions.filter((p) => p.qty > 0) ?? [];
  const anyPriced = (totals?.priced_symbols ?? 0) > 0;
  const allPriced = anyPriced && (totals?.unpriced_symbols ?? 0) === 0;
  const invAccounts = accounts?.accounts.filter((a) => a.bucket === "investments" || a.bucket === "retirement") ?? [];
  const visibleTxs = showAll ? transactions : transactions.slice(0, 10);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">Stock ledger — computed from your transactions, nothing hand-maintained.</p>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={refreshPrices} disabled={refreshBusy}>
            <RefreshCw size={13} className={cn(refreshBusy && "animate-spin")} />
            {refreshBusy ? "Fetching…" : "Prices"}
          </Button>
          <Button size="sm" variant="primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? <X size={13} /> : <Plus size={13} />}
            {showForm ? "Close" : "Add transaction"}
          </Button>
        </div>
      </div>

      {loadError && (
        <p className="rounded-lg border border-danger/40 p-3 text-sm text-danger">Couldn&apos;t load: {loadError}</p>
      )}

      {refreshErrors.length > 0 && (
        <div className="space-y-1 rounded-lg border border-warn/40 p-3 text-xs">
          <p className="text-warn">Some prices couldn&apos;t be fetched — showing the last stored snapshot instead:</p>
          {refreshErrors.map((e) => (
            <p key={e} className="text-muted">
              {e}
            </p>
          ))}
        </div>
      )}

      {/* Totals */}
      {totals && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Invested" value={money(totals.cost_basis)} hint="cost basis of open lots" />
          <Stat
            label={allPriced ? "Current value" : "Last known value"}
            value={anyPriced ? money(totals.market_value) : "—"}
            hint={
              anyPriced
                ? `EOD ${positions?.prices_as_of ?? ""}${totals.unpriced_symbols ? ` · ${totals.unpriced_symbols} unpriced` : ""}`
                : "no price snapshot yet"
            }
          />
          <Stat
            label="Unrealized P/L"
            value={anyPriced ? money(totals.unrealized_pnl) : "—"}
            hint={anyPriced ? pct(totals.unrealized_pnl_pct) : undefined}
            tone={anyPriced ? tone(totals.unrealized_pnl) : "accent"}
          />
          <Stat
            label="Realized + dividends"
            value={money(totals.realized_pnl + totals.dividends)}
            hint={`${money(totals.realized_pnl)} realized · ${money(totals.dividends)} div`}
            tone={tone(totals.realized_pnl + totals.dividends)}
          />
        </div>
      )}

      {/* Add transaction */}
      {showForm && (
        <Panel title="Add transaction" icon={Plus}>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <FieldLabel label="Date">
              <Input type="date" value={txDate} onChange={(e) => setTxDate(e.target.value)} />
            </FieldLabel>
            <FieldLabel label="Action">
              <Select value={action} onChange={(e) => setAction(e.target.value as StockAction)}>
                {STOCK_ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </Select>
            </FieldLabel>
            <FieldLabel label="Ticker">
              <Input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="RIVN"
                autoCapitalize="characters"
              />
            </FieldLabel>
            {!isDividend && (
              <FieldLabel label="Shares">
                <Input type="number" inputMode="decimal" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} />
              </FieldLabel>
            )}
            <FieldLabel label={isDividend ? "Total cash received" : "Price / share"}>
              <Input type="number" inputMode="decimal" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)} />
            </FieldLabel>
            <FieldLabel label="Fees">
              <Input type="number" inputMode="decimal" min="0" step="any" value={fees} onChange={(e) => setFees(e.target.value)} />
            </FieldLabel>
            <FieldLabel label="Account">
              <Input value={account} onChange={(e) => setAccount(e.target.value)} placeholder="e.g. Robinhood" />
            </FieldLabel>
            <FieldLabel label="Notes" className="col-span-2 md:col-span-1">
              <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="optional" />
            </FieldLabel>
          </div>
          {txError && <p className="mt-2 text-xs text-danger">{txError}</p>}
          <div className="mt-3 flex justify-end">
            <Button variant="primary" size="sm" onClick={submit} disabled={!txValid || txBusy}>
              {txBusy ? "Saving…" : `Save ${action}`}
            </Button>
          </div>
        </Panel>
      )}

      {/* Holdings + allocation */}
      <div className="grid gap-4 md:grid-cols-[1fr_260px]">
        <Panel title="Holdings">
          {positions && open.length === 0 ? (
            <EmptyState icon={TrendingUp}>No open positions — add a buy to start the ledger.</EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {open.map((p) => (
                <HoldingRow key={p.symbol} p={p} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Allocation">
          {open.length === 0 ? (
            <p className="text-sm text-muted">Nothing allocated yet.</p>
          ) : (
            <>
              <Donut label="Allocation chart" slices={open.map((p) => ({ key: p.symbol, pct: p.allocation_pct ?? 0 }))} />
              <p className="mt-2 text-center text-[11px] text-muted">
                by {totals?.allocation_basis === "market_value" ? "market value" : "cost basis (some unpriced)"}
              </p>
              <ul className="mt-3 space-y-1 text-xs">
                {open.map((p, i) => (
                  <li key={p.symbol} className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SLICE_COLORS[i % SLICE_COLORS.length] }} />
                    <span className="font-mono">{p.symbol}</span>
                    <span className="ml-auto font-mono text-muted">{p.allocation_pct?.toFixed(1) ?? "—"}%</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>
      </div>

      {/* Recent transactions */}
      <Panel
        title="Recent transactions"
        actions={
          transactions.length > 10 && (
            <Button size="sm" variant="ghost" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show recent" : `Show all ${transactions.length}`}
            </Button>
          )
        }
      >
        {transactions.length === 0 ? (
          <p className="p-4 text-sm text-muted">No transactions yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {visibleTxs.map((t) => (
              <li key={t.id} className="flex items-start gap-3 py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Badge tone={t.action === "buy" ? "accent" : t.action === "sell" ? "warn" : "ok"}>{t.action}</Badge>
                    <span className="font-mono font-medium">{t.symbol}</span>
                    <span className="ml-auto font-mono text-[11px] text-muted">{t.date}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted">
                    {t.action === "dividend"
                      ? money(t.price)
                      : `${shares(t.qty)} @ ${money(t.price)}${t.fees ? ` + ${money(t.fees)} fees` : ""}`}
                    {t.account ? ` · ${t.account}` : ""}
                    {t.notes ? ` · ${t.notes}` : ""}
                  </p>
                </div>
                <button
                  onClick={() => remove(t)}
                  className="mt-0.5 shrink-0 text-muted hover:text-danger"
                  aria-label={`Delete ${t.action} ${t.symbol} on ${t.date}`}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {/* Recorded brokerage / retirement balances (Accounts tab) */}
      {accounts && (
        <Panel title="Investment & retirement accounts">
          {invAccounts.length === 0 ? (
            <p className="p-4 text-sm text-muted">
              No brokerage, 401(k), IRA or HSA balances recorded — add them on the Accounts tab.
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {invAccounts.map((a) => (
                <li key={a.slug} className="flex items-center gap-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">
                    {a.name}
                    <span className="ml-2 text-xs text-muted">{ACCOUNT_TYPE_LABELS[a.account_type] ?? a.account_type}</span>
                  </span>
                  <span className="text-xs text-muted">{a.latest_date ?? "no balance"}</span>
                  <span className="w-28 text-right font-mono">{money(a.latest_balance)}</span>
                </li>
              ))}
            </ul>
          )}
          {accounts.stock_symbols_covered.length > 0 && (
            <p className="mt-2 border-t border-line pt-2 text-[11px] text-muted">
              Net worth counts {accounts.stock_symbols_covered.join(", ")} via the recorded account balance (their
              ledger account matches), not the ledger value — no double counting.
            </p>
          )}
        </Panel>
      )}

      {/* Home for the future stocks discusser — intentionally no functionality yet. */}
      <Panel title="Watchlist & hunches" icon={Lightbulb} actions={<Badge tone="muted">coming soon</Badge>}>
        <p className="text-sm text-muted">
          Coming soon: a stocks discusser — what&apos;s going on with the tickers you follow (owned or just watching,
          like RIVN), with recorded news and your hunches over time.
        </p>
      </Panel>
    </div>
  );
}

function HoldingRow({ p }: { p: StockPosition }) {
  return (
    <li className="space-y-1.5 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="font-mono text-base font-semibold">{p.symbol}</span>
        <span className="text-xs text-muted">
          {shares(p.qty)} sh · avg {money(p.avg_cost)}
        </span>
        {p.oversold && <Badge tone="danger">oversold</Badge>}
        <span className="ml-auto font-mono text-sm">{money(p.market_value ?? p.cost_basis)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
        <span>
          last {money(p.last_price)}
          {p.last_price_date ? ` (${p.last_price_date})` : " (no snapshot)"}
        </span>
        <span className={cn("ml-auto font-mono", toneText(p.unrealized_pnl))}>
          {p.unrealized_pnl == null ? "P/L —" : `${money(p.unrealized_pnl)} · ${pct(p.unrealized_pnl_pct)}`}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
          <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, p.allocation_pct ?? 0)}%` }} />
        </div>
        <span className="w-12 text-right font-mono text-[11px] text-muted">{p.allocation_pct?.toFixed(1) ?? "—"}%</span>
      </div>
    </li>
  );
}
