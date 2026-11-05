"use client";

// Career — every Career/** hub (employers, the roles inside them, contracts,
// education) as the PersonalWebsite's experience timeline. Detail of one hub
// is `?hub=<folder>` (static-export friendly, no dynamic route).
// The record/website updaters moved to /career/updates (2026-11-05).
import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Briefcase, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState, PageHeader, Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { CareerTimeline } from "@/components/careerpage/CareerTimeline";
import { HubDetail } from "@/components/careerpage/HubDetail";
import { HubForm } from "@/components/careerpage/HubForm";
import { CareerNode, CareerTimeline as Timeline, flattenCareer, getCareerTimeline } from "@/lib/careerPageApi";

type Filter = "all" | "employment" | "contracts" | "education";

const MATCH: Record<Filter, (n: CareerNode) => boolean> = {
  all: () => true,
  employment: (n) => n.type === "employer" || n.type === "role" || n.type === "other",
  contracts: (n) => n.type === "contract",
  education: (n) => n.type === "education",
};

export default function CareerPage() {
  return (
    <Suspense>
      <CareerPageInner />
    </Suspense>
  );
}

function CareerPageInner() {
  const hubParam = useSearchParams().get("hub");
  const [data, setData] = useState<Timeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    getCareerTimeline()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(load, [load]);

  const orgs = useMemo(() => (data ? data.items.filter((n) => n.type !== "contract" && n.type !== "role") : []), [data]);
  const shown = useMemo(() => (data ? data.items.filter(MATCH[filter]) : []), [data, filter]);
  const detail = useMemo(
    () => (data && hubParam ? (flattenCareer(data.items).find((n) => n.folder === hubParam) ?? null) : null),
    [data, hubParam]
  );

  const updatesLink = (
    <Link href="/career/updates" className="whitespace-nowrap font-mono text-xs text-accent hover:underline">
      Career updates →
    </Link>
  );

  if (hubParam) {
    return (
      <div className="mx-auto max-w-4xl">
        {error && <p className="mb-3 text-sm text-danger">{error}</p>}
        {!data && !error && <p className="text-sm text-muted">Loading…</p>}
        {data && !detail && (
          <EmptyState icon={Briefcase}>
            No Career hub at <span className="font-mono">{hubParam}</span>. <Link href="/career" className="text-accent underline">Back to Career</Link>
          </EmptyState>
        )}
        {data && detail && <HubDetail node={detail} orgs={orgs} onChanged={load} />}
      </div>
    );
  }

  const total = data?.items.length ?? 0;
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="Career"
        subtitle="Every employer, role and contract — with the work logs, record entries and files behind each."
        icon={Briefcase}
        actions={
          <>
            {updatesLink}
            <Button size="sm" variant="primary" onClick={() => setAdding((v) => !v)}>
              <Plus size={13} /> Add role / contract
            </Button>
          </>
        }
      />

      {adding && (
        <Panel title="Add a hub" icon={Plus} className="mb-4">
          <HubForm
            orgs={orgs}
            onCancel={() => setAdding(false)}
            onSaved={() => {
              setAdding(false);
              load();
            }}
          />
        </Panel>
      )}

      <p className="mb-3 inline-block max-w-full rounded-md border border-accent/40 bg-background px-3 py-1.5 font-mono text-sm text-accent shadow-[0_0_12px_rgb(34_211_238/0.15)]">
        $ git log --oneline career/ <span className="text-muted"># {total} {total === 1 ? "entry" : "entries"}, newest first</span>
      </p>

      <div className="mb-4 overflow-x-auto">
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All" },
            { value: "employment", label: "Employment" },
            { value: "contracts", label: "Contracts" },
            { value: "education", label: "Education" },
          ]}
        />
      </div>

      {error && <p className="mb-3 text-sm text-danger">{error}</p>}
      {!data && !error && <p className="text-sm text-muted">Loading…</p>}
      {data && shown.length === 0 && (
        <EmptyState icon={Briefcase}>
          {total === 0 ? (
            <>
              No Career hubs yet. Add an employer (Career/&lt;Org&gt;), then its roles (Career/&lt;Org&gt;/&lt;Role&gt;) and
              contracts (Career/Contracts/&lt;Client&gt;).
            </>
          ) : (
            "Nothing under this filter."
          )}
        </EmptyState>
      )}
      {shown.length > 0 && <CareerTimeline items={shown} />}
    </div>
  );
}
