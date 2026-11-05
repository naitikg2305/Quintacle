"use client";

// One form for both "New project" (POST /projects) and "Edit fields"
// (PUT /projects/<slug>/fields). A direct owner edit with an explicit Save,
// like the career alias table — no model in the loop.

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { PROJECT_STATUSES, type ProjectDetail, type ProjectFieldsUpdate, type ProjectStatus } from "@/lib/projectsApi";
import { STATUS_LABEL } from "./ProjectCard";

type Draft = {
  name: string;
  description: string;
  status: ProjectStatus;
  repo: string;
  summary: string;
  stack: string;
  start: string;
  end: string;
  cover: string;
  public_name: string;
  public_repo: string;
};

function draftFrom(p?: ProjectDetail): Draft {
  return {
    name: "",
    description: "",
    status: p?.status ?? "doing",
    repo: p?.repo ?? "",
    summary: p?.hub ? p.summary : "",
    stack: (p?.stack ?? []).join(", "),
    start: p?.start ?? "",
    end: p?.end ?? "",
    cover: p?.cover ?? "",
    public_name: p?.public_name ?? "",
    public_repo: p?.public_repo ?? "",
  };
}

function Label({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">{text}</span>
      {children}
    </label>
  );
}

export default function ProjectForm({
  project,
  onSubmit,
  onCancel,
}: {
  project?: ProjectDetail;
  onSubmit: (body: ProjectFieldsUpdate & { name?: string; description?: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const creating = !project;
  const [initial] = useState<Draft>(() => draftFrom(project));
  const [d, setD] = useState<Draft>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => setD((prev) => ({ ...prev, [k]: e.target.value }));

  const imageAndModelFiles = (project?.files ?? []).filter((f) => f.kind === "image" || f.name.toLowerCase().endsWith(".stl"));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (creating && !d.name.trim()) {
      setError("Name is required");
      return;
    }
    setBusy(true);
    setError(null);
    // Edit sends only what changed (a summary shown from the hub body's first
    // line is not persisted as a field just by opening the form); create
    // sends everything that's filled in.
    const keys: (keyof Draft)[] = ["status", "repo", "summary", "stack", "start", "end", "public_name", "public_repo"];
    if (!creating) keys.push("cover");
    const body: Record<string, string> = {};
    for (const k of keys) {
      const v = d[k].trim();
      if (creating ? v !== "" : v !== initial[k].trim()) body[k] = v;
    }
    if (creating) {
      body.name = d.name.trim();
      body.description = d.description;
    }
    try {
      await onSubmit(body as ProjectFieldsUpdate & { name?: string; description?: string });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {creating && (
        <Label text="Name">
          <Input value={d.name} onChange={set("name")} placeholder="Autonomous Rover" autoFocus />
        </Label>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Label text="Status">
          <Select value={d.status} onChange={set("status")}>
            {PROJECT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </Select>
        </Label>
        <Label text="GitHub repo">
          <Input value={d.repo} onChange={set("repo")} placeholder="https://github.com/…" inputMode="url" />
        </Label>
      </div>
      <Label text="Summary (card one-liner)">
        <Input value={d.summary} onChange={set("summary")} placeholder="What it is, in a line" />
      </Label>
      <Label text="Stack (comma separated)">
        <Input value={d.stack} onChange={set("stack")} placeholder="Python, FastAPI, ROS" />
      </Label>
      <div className="grid grid-cols-2 gap-3">
        <Label text="Start">
          <Input value={d.start} onChange={set("start")} placeholder="2025-01" />
        </Label>
        <Label text="End">
          <Input value={d.end} onChange={set("end")} placeholder="2025-05" />
        </Label>
      </div>
      {!creating && imageAndModelFiles.length > 0 && (
        <Label text="Card visual">
          <Select value={d.cover} onChange={set("cover")}>
            <option value="">Automatic (card.stl, cover image, first image…)</option>
            {imageAndModelFiles.map((f) => (
              <option key={f.path} value={f.path}>
                {f.path}
              </option>
            ))}
          </Select>
        </Label>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Label text="Public name (website)">
          <Input value={d.public_name} onChange={set("public_name")} placeholder="Name the site uses" />
        </Label>
        <Label text="Public repo (website)">
          <Input value={d.public_repo} onChange={set("public_repo")} placeholder="https://github.com/…" inputMode="url" />
        </Label>
      </div>
      {creating && (
        <Label text="Description (hub note body, markdown)">
          <Textarea value={d.description} onChange={set("description")} rows={5} placeholder="What it is, why, how…" />
        </Label>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Saving…" : creating ? "Create project" : "Save"}
        </Button>
      </div>
    </form>
  );
}
