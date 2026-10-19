"use client";

import { useState } from "react";
import {
  FINANCE_KINDS,
  FinanceKind,
  ParsedStatementImport,
  parseStatement,
  StatementMapping,
  StatementTransaction,
} from "@/lib/api";

type Props = {
  entry: ParsedStatementImport;
  onUpdate: (patch: Partial<ParsedStatementImport>) => void;
};

const MAPPING_FIELDS: { key: keyof Omit<StatementMapping, "negate">; label: string }[] = [
  { key: "date", label: "date" },
  { key: "merchant", label: "merchant" },
  { key: "amount", label: "amount" },
  { key: "debit", label: "debit" },
  { key: "credit", label: "credit" },
  { key: "notes", label: "notes" },
];

function fmt(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

// Review gate for a dropped bank/card statement (propose -> review -> Save):
// every proposed transaction is a row you can edit, keep, or drop before
// anything is written. CSV drops also expose the column mapping the
// deterministic parser guessed — correct it and re-parse without re-dropping.
export default function StatementImportCard({ entry, onUpdate }: Props) {
  const [reparseBusy, setReparseBusy] = useState(false);
  const [reparseError, setReparseError] = useState<string | null>(null);
  const included = entry.transactions.filter((t) => t.include).length;
  const duplicates = entry.transactions.filter((t) => t.duplicate).length;
  const total = entry.transactions.filter((t) => t.include).reduce((s, t) => s + t.amount, 0);

  function updateTxn(i: number, patch: Partial<StatementTransaction>) {
    onUpdate({ transactions: entry.transactions.map((t, idx) => (idx === i ? { ...t, ...patch } : t)) });
  }

  function setAll(include: boolean) {
    onUpdate({ transactions: entry.transactions.map((t) => ({ ...t, include })) });
  }

  function updateMapping(patch: Partial<StatementMapping>) {
    onUpdate({ mapping: { ...entry.mapping, ...patch } });
  }

  async function reparse() {
    if (!entry.raw_text) return;
    setReparseBusy(true);
    setReparseError(null);
    try {
      const result = await parseStatement(entry.filename, entry.raw_text, entry.mapping);
      onUpdate({
        mapping: result.mapping,
        transactions: result.transactions,
        skipped_credits: result.skipped_credits,
        skipped_unparsed: result.skipped_unparsed,
      });
    } catch (e) {
      setReparseError(e instanceof Error ? e.message : String(e));
    }
    setReparseBusy(false);
  }

  return (
    <div className="flex-1 space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs opacity-70">
        <span className="font-medium">{entry.filename || "statement"}</span>
        <span className="uppercase">{entry.format}</span>
        <span>
          {included}/{entry.transactions.length} kept · {fmt(total)}
        </span>
        {duplicates > 0 && <span className="text-amber-600 dark:text-amber-400">{duplicates} already logged (unchecked)</span>}
        {entry.skipped_credits > 0 && <span>{entry.skipped_credits} credits/payments skipped</span>}
        {entry.skipped_unparsed > 0 && <span>{entry.skipped_unparsed} unparseable rows skipped</span>}
      </div>

      {entry.format === "csv" && entry.headers.length > 0 && (
        <div className="border rounded p-2 space-y-2">
          <p className="text-xs opacity-60">
            Column mapping (guessed from the headers — fix anything wrong, then re-parse):
          </p>
          <div className="flex flex-wrap gap-2 items-center">
            {MAPPING_FIELDS.map(({ key, label }) => (
              <label key={key} className="flex items-center gap-1 text-xs">
                <span className="opacity-60">{label}</span>
                <select
                  className="border rounded px-1 py-0.5 text-xs"
                  value={entry.mapping[key] ?? ""}
                  onChange={(e) => updateMapping({ [key]: e.target.value || null })}
                >
                  <option value="">—</option>
                  {entry.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <label className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={entry.mapping.negate ?? false}
                onChange={(e) => updateMapping({ negate: e.target.checked })}
              />
              <span className="opacity-60" title="Tick when the file records spending as negative amounts">
                flip signs
              </span>
            </label>
            <button
              onClick={reparse}
              disabled={reparseBusy || !entry.raw_text}
              className="border rounded px-2 py-0.5 text-xs hover:bg-black/5 dark:hover:bg-white/5 disabled:opacity-40"
            >
              {reparseBusy ? "re-parsing..." : "Re-parse with this mapping"}
            </button>
          </div>
          {reparseError && <p className="text-xs text-red-600 dark:text-red-400">{reparseError}</p>}
        </div>
      )}

      <div className="flex gap-2 text-xs">
        <button onClick={() => setAll(true)} className="underline opacity-70 hover:opacity-100">
          keep all
        </button>
        <button onClick={() => setAll(false)} className="underline opacity-70 hover:opacity-100">
          keep none
        </button>
      </div>

      <div className="max-h-80 overflow-y-auto space-y-1 pr-1">
        {entry.transactions.length === 0 && (
          <p className="text-xs opacity-60">No spend transactions found — check the column mapping above.</p>
        )}
        {entry.transactions.map((t, i) => (
          <div key={i} className={`flex flex-wrap items-center gap-1.5 text-xs ${t.include ? "" : "opacity-50"}`}>
            <input
              type="checkbox"
              checked={t.include}
              title={t.duplicate ? "Flagged as already logged — re-check to write it anyway" : "Include this transaction"}
              onChange={(e) => updateTxn(i, { include: e.target.checked })}
            />
            <input
              type="date"
              className="border rounded px-1 py-0.5 w-32"
              value={t.date}
              onChange={(e) => updateTxn(i, { date: e.target.value })}
            />
            <input
              className="border rounded px-1 py-0.5 flex-1 min-w-32"
              placeholder="merchant"
              value={t.merchant}
              onChange={(e) => updateTxn(i, { merchant: e.target.value })}
            />
            <input
              type="number"
              step="0.01"
              min="0"
              className="border rounded px-1 py-0.5 w-20"
              value={t.amount}
              onChange={(e) => updateTxn(i, { amount: Number(e.target.value) })}
            />
            <select
              className="border rounded px-1 py-0.5"
              value={t.kind}
              onChange={(e) => updateTxn(i, { kind: e.target.value as FinanceKind })}
            >
              {FINANCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k.replace("_", " ")}
                </option>
              ))}
            </select>
            <input
              className="border rounded px-1 py-0.5 w-28"
              placeholder="notes"
              value={t.notes}
              onChange={(e) => updateTxn(i, { notes: e.target.value })}
            />
            {t.duplicate && (
              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700 dark:text-amber-400" title="Same date + amount + merchant already in the ledger">
                dup
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
