"use client";

import { useEffect, useId, useState } from "react";
import { listKBFolders } from "@/lib/api";

// One fetch per page load, shared by every card that renders this input.
let foldersPromise: Promise<string[]> | null = null;

function loadFolders(): Promise<string[]> {
  if (!foldersPromise) foldersPromise = listKBFolders().catch(() => [] as string[]);
  return foldersPromise;
}

// A folder text input with the KB's existing folders as suggestions — the
// "pick it yourself" folder picker the private, skip-AI review card needs
// (2026-11-05). Free text still works: a new folder is created on Save.
export default function KBFolderInput({
  value,
  onChange,
  className,
  placeholder = "folder",
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  placeholder?: string;
}) {
  const listId = useId();
  const [folders, setFolders] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    loadFolders().then((f) => {
      if (live) setFolders(f);
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <input list={listId} className={className} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
      <datalist id={listId}>
        {folders.map((f) => (
          <option key={f} value={f} />
        ))}
      </datalist>
    </>
  );
}
