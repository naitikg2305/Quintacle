"use client";

import { useState } from "react";
import { Save, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Field";
import {
  CareerHubFields,
  CareerHubType,
  CareerNode,
  createCareerHub,
  updateCareerHubFields,
} from "@/lib/careerPageApi";

const TYPE_LABEL: Record<CareerHubType, string> = {
  employer: "Employer",
  role: "Role (inside an org)",
  contract: "Contract",
  education: "Education",
  other: "Other",
};

function Labeled({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`block min-w-0 ${className ?? ""}`}>
      <span className="mb-1 block font-mono text-[10px] uppercase tracking-[0.14em] text-muted">{label}</span>
      {children}
    </label>
  );
}

// Create (no `hub`) or edit (`hub` given) — one form, nothing is written
// until Save. Dates accept 2026-01, Jan 2026, 2026-01-15 or "present".
export function HubForm({
  hub,
  orgs,
  defaultOrg,
  onSaved,
  onCancel,
}: {
  hub?: CareerNode;
  orgs: CareerNode[];
  defaultOrg?: string;
  onSaved: (n: CareerNode) => void;
  onCancel: () => void;
}) {
  const editing = !!hub;
  const [type, setType] = useState<CareerHubType>(hub?.type ?? (defaultOrg ? "role" : "employer"));
  const [name, setName] = useState("");
  const [org, setOrg] = useState(defaultOrg ?? orgs[0]?.folder ?? "");
  const [role, setRole] = useState(hub?.role ?? "");
  const [start, setStart] = useState(hub?.start_raw ?? "");
  const [end, setEnd] = useState(hub?.end_raw ?? "");
  const [location, setLocation] = useState(hub?.location ?? "");
  const [summary, setSummary] = useState(hub?.summary ?? "");
  const [bullets, setBullets] = useState((hub?.bullets ?? []).join("\n"));
  const [recordEntry, setRecordEntry] = useState(hub?.record_entry_field ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    const fields: CareerHubFields = {
      role,
      start,
      end,
      location,
      summary,
      bullets: bullets.split("\n").map((b) => b.replace(/^[-*•]\s*/, "").trim()).filter(Boolean),
      record_entry: recordEntry,
    };
    try {
      const saved = editing
        ? await updateCareerHubFields(hub!.folder, { ...fields, type })
        : await createCareerHub({ ...fields, type, name: name.trim(), org: type === "role" ? org : undefined });
      onSaved(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const folderPreview = editing
    ? hub!.folder
    : type === "role"
      ? `${org || "career/<org>"}/${name || "<name>"}`
      : type === "contract"
        ? `Career/Contracts/${name || "<client>"}`
        : `Career/${name || "<name>"}`;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="Type">
          <Select value={type} onChange={(e) => setType(e.target.value as CareerHubType)}>
            {(Object.keys(TYPE_LABEL) as CareerHubType[]).map((t) => (
              <option key={t} value={t}>
                {TYPE_LABEL[t]}
              </option>
            ))}
          </Select>
        </Labeled>
        {!editing && (
          <Labeled label={type === "role" ? "Role hub name (e.g. Engineering, Sales)" : type === "contract" ? "Client" : "Name"}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={type === "role" ? "Engineering" : "Minfy"} />
          </Labeled>
        )}
        {!editing && type === "role" && (
          <Labeled label="Org">
            <Select value={org} onChange={(e) => setOrg(e.target.value)}>
              {orgs.length === 0 && <option value="">— add an employer first —</option>}
              {orgs.map((o) => (
                <option key={o.folder} value={o.folder}>
                  {o.title}
                </option>
              ))}
            </Select>
          </Labeled>
        )}
        <Labeled label="Title / position">
          <Input value={role} onChange={(e) => setRole(e.target.value)} placeholder="AI Engineer" />
        </Labeled>
        <Labeled label="Start">
          <Input value={start} onChange={(e) => setStart(e.target.value)} placeholder="2026-01 or Jan 2026" />
        </Labeled>
        <Labeled label="End">
          <Input value={end} onChange={(e) => setEnd(e.target.value)} placeholder="present" />
        </Labeled>
        <Labeled label="Location">
          <Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Tysons, VA" />
        </Labeled>
        <Labeled label="Record entry (optional)">
          <Input value={recordEntry} onChange={(e) => setRecordEntry(e.target.value)} placeholder="7.1" />
        </Labeled>
      </div>
      <Labeled label="Summary">
        <Textarea rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} />
      </Labeled>
      <Labeled label="Bullets (one per line)">
        <Textarea rows={4} value={bullets} onChange={(e) => setBullets(e.target.value)} className="font-mono text-xs" />
      </Labeled>
      <p className="break-all font-mono text-[11px] text-muted">
        → {folderPreview}
      </p>
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="sm" onClick={save} disabled={busy || (!editing && (!name.trim() || (type === "role" && !org)))}>
          <Save size={13} /> {busy ? "Saving…" : "Save"}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
          <X size={13} /> Cancel
        </Button>
      </div>
    </div>
  );
}
