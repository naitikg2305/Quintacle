"use client";

import { useEffect, useState } from "react";
import { createDocument, Document, documentAssetUrl, listDocuments } from "@/lib/api";

const DOC_TYPES = ["lease", "id", "passport", "immigration", "insurance", "medical", "financial", "warranty"];

function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [name, setName] = useState("");
  const [docType, setDocType] = useState("id");
  const [issuedDate, setIssuedDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function refresh() {
    setDocuments(await listDocuments());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    setStatus("saving...");
    const result = await createDocument(
      { name, doc_type: docType, issued_date: issuedDate || null, expiry_date: expiryDate || null, notes },
      files
    );
    setStatus(result.todo_created ? `saved — "Renew: ${name}" added to your todos` : "saved");
    setName("");
    setIssuedDate("");
    setExpiryDate("");
    setNotes("");
    setFiles([]);
    await refresh();
    setBusy(false);
  }

  const sorted = [...documents].sort((a, b) => {
    if (!a.expiry_date) return 1;
    if (!b.expiry_date) return -1;
    return a.expiry_date.localeCompare(b.expiry_date);
  });

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Document Vault</h1>
      <p className="text-sm opacity-60 -mt-4">
        Leases, IDs, insurance, immigration paperwork. Setting an expiry date automatically creates a renewal todo — one time,
        on first save, so redefining a document later never spawns duplicates.
      </p>

      <div className="border rounded p-4 space-y-3">
        <h2 className="font-medium text-sm">Add a document</h2>
        <div className="flex gap-2">
          <input
            className="flex-1 border rounded px-2 py-1 text-sm"
            placeholder="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <select className="border rounded px-2 py-1 text-sm" value={docType} onChange={(e) => setDocType(e.target.value)}>
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2 text-sm">
          <label className="flex-1">
            issued
            <input
              type="date"
              className="block w-full border rounded px-2 py-1 mt-1"
              value={issuedDate}
              onChange={(e) => setIssuedDate(e.target.value)}
            />
          </label>
          <label className="flex-1">
            expires
            <input
              type="date"
              className="block w-full border rounded px-2 py-1 mt-1"
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
            />
          </label>
        </div>
        <textarea
          className="w-full border rounded p-2 text-sm"
          rows={2}
          placeholder="notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <input
          type="file"
          multiple
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          className="text-sm"
        />
        {files.length > 0 && (
          <p className="text-xs opacity-60">{files.length} page{files.length === 1 ? "" : "s"}/scan{files.length === 1 ? "" : "s"} selected</p>
        )}
        <button
          onClick={submit}
          disabled={busy || !name.trim()}
          className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
        >
          Save document
        </button>
        {status && <p className="text-sm opacity-70">{status}</p>}
      </div>

      <div className="space-y-2">
        {sorted.length === 0 && <p className="text-sm opacity-60">Nothing in the vault yet.</p>}
        {sorted.map((d) => {
          const soon = d.expiry_date ? daysUntil(d.expiry_date) : null;
          return (
            <div key={d.slug} className="border rounded p-3 flex items-start gap-3">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{d.name}</span>
                  <span className="text-xs opacity-50">{d.doc_type}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-black/5 dark:bg-white/10">{d.status}</span>
                </div>
                {d.notes && <p className="text-xs opacity-70 mt-1">{d.notes}</p>}
                <div className="text-xs opacity-50 mt-1 flex gap-3">
                  {d.issued_date && <span>issued {d.issued_date}</span>}
                  {d.expiry_date && (
                    <span className={soon !== null && soon <= 60 ? "text-red-600 dark:text-red-400 font-medium" : ""}>
                      expires {d.expiry_date}
                      {soon !== null && soon <= 60 && soon >= 0 ? ` (${soon}d)` : ""}
                    </span>
                  )}
                  {(d.assets ?? []).map((asset, i) => (
                    <a key={asset} href={documentAssetUrl(asset)} target="_blank" rel="noreferrer" className="underline">
                      view {(d.assets ?? []).length > 1 ? `page ${i + 1}` : "scan"} →
                    </a>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
