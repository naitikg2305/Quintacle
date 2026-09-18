"use client";

import { useEffect, useState } from "react";
import { createCreditCard, CreditCard, listCreditCards } from "@/lib/api";

function fmtMoney(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

export default function CreditCardsPage() {
  const [cards, setCards] = useState<CreditCard[]>([]);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [issuer, setIssuer] = useState("");
  const [annualFee, setAnnualFee] = useState("");
  const [rewardsSummary, setRewardsSummary] = useState("");
  const [pointsBalance, setPointsBalance] = useState("");
  const [signupBonus, setSignupBonus] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);

  async function refresh() {
    setCards(await listCreditCards());
  }

  useEffect(() => {
    refresh();
  }, []);

  function resetForm() {
    setName("");
    setIssuer("");
    setAnnualFee("");
    setRewardsSummary("");
    setPointsBalance("");
    setSignupBonus("");
    setNotes("");
    setEditingName(null);
    setShowForm(false);
  }

  function startEdit(c: CreditCard) {
    setName(c.name);
    setIssuer(c.issuer);
    setAnnualFee(c.annual_fee != null ? String(c.annual_fee) : "");
    setRewardsSummary(c.rewards_summary);
    setPointsBalance(c.points_balance != null ? String(c.points_balance) : "");
    setSignupBonus(c.signup_bonus);
    setNotes(c.notes);
    setEditingName(c.name);
    setShowForm(true);
  }

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    await createCreditCard({
      name,
      issuer,
      annual_fee: annualFee ? Number(annualFee) : null,
      rewards_summary: rewardsSummary,
      points_balance: pointsBalance ? Number(pointsBalance) : null,
      signup_bonus: signupBonus,
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
          <h1 className="text-2xl font-semibold">Credit Cards</h1>
          <p className="text-sm opacity-60">Your real cards, benefits, and points — update them yourself anytime.</p>
        </div>
        <div className="flex gap-2">
          <a
            href={`/kb/folder?path=${encodeURIComponent("Organisation/Finance/Credit Cards")}`}
            className="text-xs border rounded px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5"
          >
            💬 Chat about redemption strategy →
          </a>
          <button
            onClick={() => (showForm ? resetForm() : setShowForm(true))}
            className="border rounded px-3 py-1.5 text-sm"
          >
            + Card
          </button>
        </div>
      </div>

      {showForm && (
        <div className="border rounded p-4 space-y-2">
          <div className="flex gap-2">
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="card name (e.g. Chase Sapphire Preferred)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={editingName != null}
            />
            <input
              className="w-32 border rounded px-2 py-1 text-sm"
              placeholder="issuer"
              value={issuer}
              onChange={(e) => setIssuer(e.target.value)}
            />
            <input
              type="number"
              step="0.01"
              className="w-24 border rounded px-2 py-1 text-sm"
              placeholder="annual fee"
              value={annualFee}
              onChange={(e) => setAnnualFee(e.target.value)}
            />
          </div>
          <input
            className="w-full border rounded px-2 py-1 text-sm"
            placeholder="rewards summary (e.g. 3x dining, 2x travel, 1x everything else)"
            value={rewardsSummary}
            onChange={(e) => setRewardsSummary(e.target.value)}
          />
          <div className="flex gap-2">
            <input
              type="number"
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="current points balance"
              value={pointsBalance}
              onChange={(e) => setPointsBalance(e.target.value)}
            />
            <input
              className="flex-1 border rounded px-2 py-1 text-sm"
              placeholder="signup bonus"
              value={signupBonus}
              onChange={(e) => setSignupBonus(e.target.value)}
            />
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={3}
            placeholder="notes — redemption tips, why you got it, perks"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              onClick={submit}
              disabled={busy || !name.trim()}
              className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              {editingName ? "Save changes" : "Save card"}
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
        {cards.length === 0 && <p className="text-sm opacity-60">No cards tracked yet.</p>}
        {cards.map((c) => (
          <div key={c.slug} className="border rounded p-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-sm">{c.name}</span>
                {c.issuer && <span className="text-xs opacity-50">{c.issuer}</span>}
                {c.annual_fee != null && (
                  <span className="text-xs opacity-50">{c.annual_fee === 0 ? "no annual fee" : `${fmtMoney(c.annual_fee)}/yr`}</span>
                )}
                {c.points_balance != null && <span className="text-xs opacity-50">{c.points_balance.toLocaleString()} pts</span>}
              </div>
              <button onClick={() => startEdit(c)} className="text-xs underline opacity-70 hover:opacity-100">
                edit
              </button>
            </div>
            {c.rewards_summary && <p className="text-xs opacity-70 mt-1">{c.rewards_summary}</p>}
            {c.signup_bonus && <p className="text-xs opacity-60 mt-1">signup bonus: {c.signup_bonus}</p>}
            {c.notes && <p className="text-sm mt-1 whitespace-pre-wrap">{c.notes}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
