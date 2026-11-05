"use client";

// Finances (2026-11-05): ONE page for money — owner: "finances + stocks
// whatever becomes Finances — with my budgets, my spend, my subscriptions".
// Tabs are URL-addressed (`/finance?tab=investments`) so links and the
// /stocks + /investments redirect stubs land on the right section; it's a
// client-side search param, so the Capacitor static export works unchanged.
// Every feature of the old Finance page (ledger by kind, insights, income,
// subscriptions, KB/credit-card/statement links) and the old Stocks page
// (ledger, positions, prices) moved into a tab — nothing dropped.

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Landmark } from "lucide-react";
import { PageHeader } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";
import AccountsTab from "./_components/AccountsTab";
import IncomeTab from "./_components/IncomeTab";
import InvestmentsTab from "./_components/InvestmentsTab";
import OverviewTab from "./_components/OverviewTab";
import SpendTab from "./_components/SpendTab";
import SubscriptionsTab from "./_components/SubscriptionsTab";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "accounts", label: "Accounts" },
  { id: "investments", label: "Investments" },
  { id: "spend", label: "Spend & budgets" },
  { id: "subscriptions", label: "Subscriptions" },
  { id: "income", label: "Income" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const isTab = (t: string | null): t is TabId => TABS.some((x) => x.id === t);

export default function FinancePage() {
  return (
    <Suspense>
      <FinancePageInner />
    </Suspense>
  );
}

function FinancePageInner() {
  const router = useRouter();
  const raw = useSearchParams().get("tab");
  const tab: TabId = isTab(raw) ? raw : "overview";
  const go = (t: string) => router.replace(t === "overview" ? "/finance" : `/finance?tab=${t}`, { scroll: false });

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Finances" icon={Landmark} subtitle="Accounts, investments, spend, budgets, subscriptions, income — all computed, zero AI." />

      <nav className="-mx-4 mb-4 overflow-x-auto px-4 md:mx-0 md:px-0" aria-label="Finance sections">
        <div className="inline-flex gap-1 rounded-lg border border-line bg-surface p-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => go(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
              className={cn(
                "whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                tab === t.id ? "bg-accent/15 text-accent shadow-glow" : "text-muted hover:text-foreground"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      {tab === "overview" && <OverviewTab goTab={go} />}
      {tab === "accounts" && <AccountsTab />}
      {tab === "investments" && <InvestmentsTab />}
      {tab === "spend" && <SpendTab />}
      {tab === "subscriptions" && <SubscriptionsTab />}
      {tab === "income" && <IncomeTab />}

      {/* Everything the old page linked to, kept reachable. */}
      <div className="mt-6 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-muted">
        <a href="/finance/cards" className="hover:text-foreground">
          Credit cards (benefits &amp; points) →
        </a>
        <a href="/finance/investments" className="hover:text-foreground">
          Static holdings records →
        </a>
        <a href={`/kb/folder?path=${encodeURIComponent("Organisation/Finance/Stocks & Investments")}`} className="hover:text-foreground">
          Stocks &amp; Investments notes →
        </a>
        <a href={`/kb/folder?path=${encodeURIComponent("Organisation/Finance/Life Planning")}`} className="hover:text-foreground">
          Life Planning (savings goals) →
        </a>
        <a
          href="/kb"
          className="hover:text-foreground"
          title="Attach a CSV/OFX/QFX export (or a PDF with a 'statement:' note) on the chat scratchpad — parsed, deduped, and reviewed before anything is written"
        >
          Import a statement (via Chat) →
        </a>
      </div>
    </div>
  );
}
