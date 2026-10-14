"use client";

import { useEffect, useState } from "react";
import { ArrowLeftRight, Download, RefreshCw } from "lucide-react";
import { API_BASE, SyncReport, syncPull } from "@/lib/api";
import { Badge, PageHeader, Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";

const PEER_KEY = "quintacle.sync.peer";

// Manual LAN sync — both devices must be running the backend on the same
// wifi. Pull copies the peer's changes here; two-way also asks the peer to
// pull back from this device. Additive: deletions never propagate.
export default function SyncPage() {
  const [peer, setPeer] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [report, setReport] = useState<SyncReport | null>(null);

  useEffect(() => {
    // Hydrate the last-used peer address — localStorage only exists client-side.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPeer(localStorage.getItem(PEER_KEY) ?? "");
  }, []);

  function normalizedPeer(): string | null {
    const raw = peer.trim();
    if (!raw) return null;
    const url = raw.includes("://") ? raw : `http://${raw}`;
    return url.includes(":", url.indexOf("://") + 3) ? url : `${url}:8000`;
  }

  // This device's own LAN-reachable backend URL, for the peer to pull from:
  // the host the browser is already using, with the backend's port.
  function selfUrl(): string {
    const port = new URL(API_BASE).port || "8000";
    return `http://${window.location.hostname}:${port}`;
  }

  async function run(twoWay: boolean) {
    const peerUrl = normalizedPeer();
    if (!peerUrl) return;
    localStorage.setItem(PEER_KEY, peer.trim());
    setBusy(true);
    setReport(null);
    setStatus(twoWay ? "syncing both ways..." : "pulling from peer...");
    try {
      const result = await syncPull(
        twoWay ? { peer_url: peerUrl, push_back: true, self_url: selfUrl() } : { peer_url: peerUrl }
      );
      setReport(result);
      setStatus(null);
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageHeader
        title="Sync"
        icon={RefreshCw}
        subtitle="Manual LAN sync — the other device must be on this wifi with its backend running. Additive: nothing is deleted, overwritten files are snapshotted first."
      />

      <Panel title="Peer device">
        <div className="space-y-3">
          <label className="block text-sm">
            <span className="text-muted">Peer address (IP or host, port optional — defaults to 8000)</span>
            <Input
              className="mt-1"
              placeholder="e.g. 192.168.1.42 or http://192.168.1.42:8000"
              value={peer}
              onChange={(e) => setPeer(e.target.value)}
              disabled={busy}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => run(false)} disabled={busy || !peer.trim()}>
              <Download size={16} /> Pull from peer
            </Button>
            <Button onClick={() => run(true)} disabled={busy || !peer.trim()}>
              <ArrowLeftRight size={16} /> Two-way sync
            </Button>
          </div>
          {status && <p className="text-sm text-muted">{status}</p>}
        </div>
      </Panel>

      {report && <ReportPanel title="This device pulled" report={report} />}
      {report?.push_back && <ReportPanel title="Peer pulled back" report={report.push_back} />}
    </div>
  );
}

function FileList({ label, tone, files }: { label: string; tone: "ok" | "accent" | "warn"; files: string[] }) {
  if (files.length === 0) return null;
  return (
    <div>
      <Badge tone={tone}>
        {label}: {files.length}
      </Badge>
      <ul className="mt-1.5 space-y-0.5 font-mono text-xs text-muted">
        {files.map((f) => (
          <li key={f} className="truncate">
            {f}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportPanel({ title, report }: { title: string; report: SyncReport }) {
  const nothingChanged =
    report.pulled.length === 0 && report.merged_journals.length === 0 && report.overwritten_with_snapshot.length === 0;
  return (
    <Panel title={title}>
      <div className="space-y-3 text-sm">
        {nothingChanged && <p className="text-muted">No new files — already in sync.</p>}
        <FileList label="Files pulled" tone="ok" files={report.pulled} />
        <FileList label="Journals merged" tone="accent" files={report.merged_journals} />
        <FileList label="Overwritten (old copy snapshotted)" tone="warn" files={report.overwritten_with_snapshot} />
        <p className="text-xs text-muted">
          {report.skipped_identical} identical skipped · {report.kept_local_newer} kept (local newer) · indexes rebuilt
          ({report.rebuilt.graph_edges} graph edges)
        </p>
        {report.warnings.map((w) => (
          <p key={w} className="text-xs text-warn">
            warning: {w}
          </p>
        ))}
        {report.errors.map((e) => (
          <p key={e} className="text-xs text-danger">
            error: {e}
          </p>
        ))}
      </div>
    </Panel>
  );
}
