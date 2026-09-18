"use client";

import { useState } from "react";
import { BatchFile, Bucket, proposeBatchDrop, pushKBEntryWithAsset } from "@/lib/api";

// Batch import: drop a pile of files at once, one AI call buckets them by
// shared destination folder, review/edit each bucket, reassign a file to a
// different bucket (or a brand new one — pulling it "out of the bucket" is
// just moving it to a folder of its own), then save. Each file still commits
// through the exact same single-file endpoint the regular Drop page uses.
export default function BatchDropPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [buckets, setBuckets] = useState<Bucket[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [manualDate, setManualDate] = useState("");
  const [manualTripName, setManualTripName] = useState("");

  function onFilesChosen(chosen: FileList | File[]) {
    setFiles((prev) => [...prev, ...Array.from(chosen)]);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (e.dataTransfer.files?.length) onFilesChosen(e.dataTransfer.files);
  }

  function removeFile(name: string) {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  }

  async function sortIntoBuckets() {
    if (files.length === 0) return;
    setBusy(true);
    setStatus(`sorting ${files.length} files...`);
    try {
      const { buckets: proposed } = await proposeBatchDrop(files, manualDate, manualTripName);
      setBuckets(proposed);
      setStatus(`grouped into ${proposed.length} bucket${proposed.length === 1 ? "" : "s"} — review below`);
    } catch (e) {
      setStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  function updateFile(folder: string, filename: string, patch: Partial<BatchFile>) {
    setBuckets((prev) =>
      prev
        ? prev.map((b) =>
            b.folder !== folder ? b : { ...b, files: b.files.map((f) => (f.filename === filename ? { ...f, ...patch } : f)) }
          )
        : prev
    );
  }

  function moveFile(filename: string, fromFolder: string, toFolder: string) {
    if (!toFolder.trim() || toFolder === fromFolder) return;
    setBuckets((prev) => {
      if (!prev) return prev;
      let moved: BatchFile | undefined;
      const withoutFile = prev
        .map((b) => {
          if (b.folder !== fromFolder) return b;
          const remaining = b.files.filter((f) => {
            if (f.filename === filename) {
              moved = f;
              return false;
            }
            return true;
          });
          return { ...b, files: remaining };
        })
        .filter((b) => b.files.length > 0);
      if (!moved) return prev;
      const targetIdx = withoutFile.findIndex((b) => b.folder === toFolder);
      if (targetIdx >= 0) {
        const updated = [...withoutFile];
        updated[targetIdx] = { ...updated[targetIdx], files: [...updated[targetIdx].files, moved] };
        return updated;
      }
      return [...withoutFile, { folder: toFolder, files: [moved] }];
    });
  }

  async function saveAll() {
    if (!buckets) return;
    setBusy(true);
    const total = buckets.reduce((n, b) => n + b.files.length, 0);
    let done = 0;
    for (const bucket of buckets) {
      for (const file of bucket.files) {
        setStatus(`saving ${done + 1}/${total}: ${file.filename}...`);
        const original = files.find((f) => f.name === file.filename);
        if (!original) continue;
        await pushKBEntryWithAsset(
          { folder: bucket.folder, title: file.title, content: file.content, links: file.links },
          [original]
        );
        done++;
      }
    }
    setStatus(`saved ${done} file${done === 1 ? "" : "s"}`);
    setFiles([]);
    setBuckets(null);
    setBusy(false);
  }

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold">Batch Import</h1>
      <p className="text-sm opacity-60 -mt-2">
        Drop a pile of files at once — AI groups them into buckets by where they belong. Review each bucket, move a file to a
        different one (or type a new folder to place it on its own), then save.
      </p>

      {!buckets && (
        <>
          <div onDragOver={(e) => e.preventDefault()} onDrop={onDrop} className="border-2 border-dashed rounded p-6 text-center space-y-2">
            <p className="text-sm opacity-60">Drag files here, or choose below</p>
            <input
              type="file"
              multiple
              onChange={(e) => e.target.files && onFilesChosen(e.target.files)}
              className="text-sm mx-auto"
            />
          </div>

          {files.length > 0 && (
            <ul className="text-sm space-y-1">
              {files.map((f) => (
                <li key={f.name} className="flex items-center gap-2">
                  <span className="flex-1 truncate">📄 {f.name}</span>
                  <button onClick={() => removeFile(f.name)} className="opacity-50 hover:opacity-100 px-1">
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex gap-2 text-sm">
            <label className="flex-1">
              Photo date fallback (for photos with no EXIF — screenshots, re-shared images)
              <input
                type="date"
                value={manualDate}
                onChange={(e) => setManualDate(e.target.value)}
                className="block w-full border rounded px-2 py-1 mt-1"
              />
            </label>
            <label className="flex-1">
              Trip name (overrides AI's guess, applies to every photo here)
              <input
                type="text"
                placeholder="e.g. Japan Trip 2026"
                value={manualTripName}
                onChange={(e) => setManualTripName(e.target.value)}
                className="block w-full border rounded px-2 py-1 mt-1"
              />
            </label>
          </div>

          <button
            onClick={sortIntoBuckets}
            disabled={busy || files.length === 0}
            className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
          >
            Sort into buckets
          </button>
        </>
      )}

      {buckets && (
        <div className="space-y-4">
          {buckets.map((bucket) => (
            <div key={bucket.folder} className="border rounded p-4 space-y-3">
              <h2 className="font-medium text-sm">
                {bucket.folder} <span className="opacity-50 font-normal">({bucket.files.length})</span>
              </h2>
              {bucket.files.map((file) => (
                <div key={file.filename} className="border-t pt-2 space-y-1">
                  <div className="flex gap-2 items-center">
                    <span className="text-xs opacity-50 shrink-0">{file.filename}</span>
                    <input
                      className="border rounded px-2 py-1 text-sm flex-1"
                      value={file.title}
                      onChange={(e) => updateFile(bucket.folder, file.filename, { title: e.target.value })}
                    />
                    <input
                      className="border rounded px-2 py-1 text-xs w-48"
                      placeholder="move to folder..."
                      defaultValue=""
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          moveFile(file.filename, bucket.folder, e.currentTarget.value);
                          e.currentTarget.value = "";
                        }
                      }}
                    />
                  </div>
                  <textarea
                    className="w-full border rounded p-2 text-xs"
                    rows={3}
                    value={file.content}
                    onChange={(e) => updateFile(bucket.folder, file.filename, { content: e.target.value })}
                  />
                </div>
              ))}
            </div>
          ))}

          <div className="flex gap-2">
            <button onClick={() => setBuckets(null)} className="border rounded px-4 py-2 text-sm">
              Back
            </button>
            <button
              onClick={saveAll}
              disabled={busy}
              className="flex-1 bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm disabled:opacity-40"
            >
              Save all ({buckets.reduce((n, b) => n + b.files.length, 0)} files)
            </button>
          </div>
        </div>
      )}

      {status && <p className="text-sm opacity-70">{status}</p>}
    </div>
  );
}
