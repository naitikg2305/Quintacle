"use client";

import { useEffect, useState } from "react";
import { getKBSpreadsheet, saveKBSpreadsheet, SpreadsheetSheet } from "@/lib/api";

export default function SpreadsheetEditor({ folder, path }: { folder: string; path: string }) {
  const [sheets, setSheets] = useState<SpreadsheetSheet[] | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSheets(null);
    setError(null);
    setActiveSheet(0);
    getKBSpreadsheet(folder, path)
      .then((r) => setSheets(r.sheets))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [folder, path]);

  function updateCell(row: number, col: number, value: string) {
    setSheets((prev) => {
      if (!prev) return prev;
      const next = [...prev];
      const sheet = { ...next[activeSheet] };
      const rows = sheet.rows.map((r) => [...r]);
      rows[row][col] = value;
      sheet.rows = rows;
      next[activeSheet] = sheet;
      return next;
    });
  }

  function addRow() {
    setSheets((prev) => {
      if (!prev) return prev;
      const next = [...prev];
      const sheet = { ...next[activeSheet] };
      const width = sheet.rows[0]?.length ?? 1;
      sheet.rows = [...sheet.rows, Array(width).fill("")];
      next[activeSheet] = sheet;
      return next;
    });
  }

  function addColumn() {
    setSheets((prev) => {
      if (!prev) return prev;
      const next = [...prev];
      const sheet = { ...next[activeSheet] };
      sheet.rows = sheet.rows.map((r) => [...r, ""]);
      next[activeSheet] = sheet;
      return next;
    });
  }

  async function save() {
    if (!sheets) return;
    setBusy(true);
    setStatus("saving...");
    try {
      await saveKBSpreadsheet(folder, path, sheets);
      setStatus("saved");
    } catch (e) {
      setStatus(`save failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  }

  if (error) return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;
  if (!sheets) return <p className="text-sm opacity-60">Loading spreadsheet...</p>;

  const sheet = sheets[activeSheet];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        {sheets.map((s, i) => (
          <button
            key={s.name + i}
            onClick={() => setActiveSheet(i)}
            className={`text-xs border rounded px-2 py-1 ${i === activeSheet ? "bg-black text-white dark:bg-white dark:text-black" : ""}`}
          >
            {s.name}
          </button>
        ))}
        <div className="ml-auto flex gap-2">
          <button onClick={addRow} className="text-xs border rounded px-2 py-1">
            + row
          </button>
          <button onClick={addColumn} className="text-xs border rounded px-2 py-1">
            + column
          </button>
          <button
            onClick={save}
            disabled={busy}
            className="text-xs bg-black text-white dark:bg-white dark:text-black rounded px-3 py-1 disabled:opacity-40"
          >
            Save
          </button>
        </div>
      </div>
      <div className="overflow-auto border rounded max-h-[60vh]">
        <table className="text-xs border-collapse w-full">
          <tbody>
            {sheet.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} className="border p-0">
                    <input
                      className="w-24 px-1 py-0.5 bg-transparent outline-none focus:bg-black/5 dark:focus:bg-white/10"
                      value={cell}
                      onChange={(e) => updateCell(ri, ci, e.target.value)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {status && <p className="text-xs opacity-60">{status}</p>}
    </div>
  );
}
