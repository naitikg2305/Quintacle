"use client";

// Accounts tab (2026-11-05): manually-recorded balances — checking, savings,
// cash, brokerage, 401(k), IRA, HSA, crypto, plus liabilities (card balance
// owed, loans). "Update balance" APPENDS a dated snapshot; history is never
// overwritten (nodes/finance/accounts.py), and a mistyped snapshot has an
// explicit delete as the undo. Totals/net worth are computed server-side.

import { useEffect, useState } from "react";
import { History, Plus, Trash2, Wallet, X } from "lucide-react";
import {
  ACCOUNT_TYPE_LABELS,
  AccountBucket,
  AccountsSummary,
  addAccountBalance,
  deleteAccount,
  deleteAccountBalance,
  FinanceAccount,
  getAccounts,
  upsertAccount,
} from "@/lib/api";
import { todayIso } from "@/lib/date";
import { Badge, EmptyState, Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Field";
import { FieldLabel, money, Sparkline } from "./shared";

const BUCKET_LABELS: Record<AccountBucket, string> = {
  liquid: "Cash & bank",
  investments: "Investments",
  retirement: "Retirement",
  other: "Other assets",
  liabilities: "Liabilities (owed)",
};
const BUCKET_ORDER: AccountBucket[] = ["liquid", "investments", "retirement", "other", "liabilities"];

export default function AccountsTab() {
  const [data, setData] = useState<AccountsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const [name, setName] = useState("");
  const [type, setType] = useState("checking");
  const [institution, setInstitution] = useState("");
  const [balance, setBalance] = useState("");
  const [asOf, setAsOf] = useState(todayIso());
  const [busy, setBusy] = useState(false);

  async function reload() {
    setData(await getAccounts());
  }

  useEffect(() => {
    let cancelled = false;
    getAccounts()
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  async function addAccount() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await upsertAccount({
        name: name.trim(),
        account_type: type,
        institution,
        ...(balance !== "" ? { balance: Number(balance), as_of: asOf } : {}),
      });
      setName("");
      setInstitution("");
      setBalance("");
      setShowAdd(false);
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const groups = BUCKET_ORDER.map((b) => ({ bucket: b, items: data?.accounts.filter((a) => a.bucket === b) ?? [] })).filter(
    (g) => g.items.length > 0
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">
          Record what each account holds. Updating a balance adds a dated snapshot — history is kept.
        </p>
        <Button size="sm" variant="primary" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? <X size={13} /> : <Plus size={13} />}
          {showAdd ? "Close" : "Add account"}
        </Button>
      </div>

      {error && <p className="rounded-lg border border-danger/40 p-3 text-sm text-danger">{error}</p>}

      {showAdd && (
        <Panel title="Add account" icon={Plus}>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            <FieldLabel label="Name" className="col-span-2 md:col-span-1">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Fidelity 401k" />
            </FieldLabel>
            <FieldLabel label="Type">
              <Select value={type} onChange={(e) => setType(e.target.value)}>
                {Object.entries(ACCOUNT_TYPE_LABELS).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </Select>
            </FieldLabel>
            <FieldLabel label="Institution">
              <Input value={institution} onChange={(e) => setInstitution(e.target.value)} placeholder="optional" />
            </FieldLabel>
            <FieldLabel label={type === "credit_card" || type === "loan" ? "Amount owed" : "Balance"}>
              <Input type="number" inputMode="decimal" step="any" value={balance} onChange={(e) => setBalance(e.target.value)} placeholder="optional" />
            </FieldLabel>
            <FieldLabel label="As of">
              <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
            </FieldLabel>
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Tip: name a brokerage the same as the &quot;account&quot; on your stock transactions and net worth uses this
            balance instead of the ledger value for those tickers.
          </p>
          <div className="mt-3 flex justify-end">
            <Button size="sm" variant="primary" onClick={addAccount} disabled={busy || !name.trim()}>
              {busy ? "Saving…" : "Save account"}
            </Button>
          </div>
        </Panel>
      )}

      {data && data.accounts.length === 0 && (
        <EmptyState icon={Wallet}>No accounts yet — add your checking, savings, 401(k), brokerage…</EmptyState>
      )}

      {groups.map((g) => (
        <Panel
          key={g.bucket}
          title={BUCKET_LABELS[g.bucket]}
          actions={<span className="font-mono text-xs text-muted">{money(data?.buckets[g.bucket])}</span>}
        >
          <ul className="divide-y divide-line">
            {g.items.map((a) => (
              <AccountRow key={a.slug} a={a} onChange={reload} />
            ))}
          </ul>
        </Panel>
      ))}
    </div>
  );
}

function AccountRow({ a, onChange }: { a: FinanceAccount; onChange: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [value, setValue] = useState("");
  const [asOf, setAsOf] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const owed = a.bucket === "liabilities";

  async function save() {
    if (value === "") return;
    setBusy(true);
    try {
      await addAccountBalance(a.slug, { balance: Number(value), as_of: asOf });
      setValue("");
      setEditing(false);
      await onChange();
    } finally {
      setBusy(false);
    }
  }

  async function removeSnapshot(i: number) {
    const b = a.balances[i];
    if (!confirm(`Delete the ${money(b.balance)} snapshot from ${b.date}?`)) return;
    await deleteAccountBalance(a.slug, i);
    await onChange();
  }

  async function removeAccount() {
    if (!confirm(`Delete account "${a.name}" and its ${a.balances.length} balance snapshot(s)?`)) return;
    await deleteAccount(a.slug);
    await onChange();
  }

  return (
    <li className="space-y-2 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="min-w-0 truncate text-sm font-medium">{a.name}</p>
        <span className={`shrink-0 font-mono text-sm ${owed ? "text-danger" : ""}`}>
          {owed && a.latest_balance != null ? "−" : ""}
          {money(a.latest_balance)}
        </span>
      </div>
      <p className="text-xs text-muted">
        {ACCOUNT_TYPE_LABELS[a.account_type] ?? a.account_type}
        {a.institution ? ` · ${a.institution}` : ""}
        {a.latest_date ? ` · as of ${a.latest_date}` : " · no balance yet"}
      </p>
      {a.balances.length > 1 && <Sparkline values={a.balances.map((b) => b.balance)} className="h-6" />}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => setEditing((v) => !v)}>
          {editing ? "Cancel" : "Update balance"}
        </Button>
        {a.balances.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setShowHistory((v) => !v)}>
            <History size={12} /> {a.balances.length}
          </Button>
        )}
        <button onClick={removeAccount} className="ml-auto text-muted hover:text-danger" aria-label={`Delete account ${a.name}`}>
          <Trash2 size={14} />
        </button>
      </div>
      {editing && (
        <div className="flex flex-wrap items-end gap-2">
          <FieldLabel label={owed ? "Amount owed" : "New balance"} className="w-36">
            <Input type="number" inputMode="decimal" step="any" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
          </FieldLabel>
          <FieldLabel label="As of" className="w-40">
            <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </FieldLabel>
          <Button size="sm" variant="primary" onClick={save} disabled={busy || value === ""}>
            {busy ? "Saving…" : "Save snapshot"}
          </Button>
        </div>
      )}
      {showHistory && (
        <ul className="space-y-1 rounded-lg border border-line p-2 text-xs">
          {a.balances
            .map((b, i) => ({ b, i }))
            .reverse()
            .map(({ b, i }) => (
              <li key={`${b.date}-${i}`} className="flex items-center gap-2">
                <span className="w-24 font-mono text-muted">{b.date}</span>
                <span className="flex-1 font-mono">{money(b.balance)}</span>
                {b.note && <Badge tone="muted">{b.note}</Badge>}
                <button onClick={() => removeSnapshot(i)} className="text-muted hover:text-danger" aria-label={`Delete snapshot ${b.date}`}>
                  <Trash2 size={12} />
                </button>
              </li>
            ))}
        </ul>
      )}
    </li>
  );
}
