"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// The Drop page retired (next-wave §9 — chat absorbs drop, 2026-10-20): the
// chat page's scratchpad IS the drop lane now — text, files, statements,
// faces, "Still going" sessions, the manual grid, all of it. This stub keeps
// old links and bookmarks working; it's a client-side redirect so the same
// code works in the Capacitor static export (no server to serve a 307).
// The /drop ENDPOINT is untouched — it's the engine; only this surface moved.
export default function DropRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/kb");
  }, [router]);
  return null;
}
