"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// 2026-11-05: the Stocks page became the Investments tab of the unified
// Finances page (owner: "finances + stocks … becomes Finances"). This stub
// keeps old links/bookmarks working; it's a client-side redirect so the same
// code works in the Capacitor static export (no server to serve a 307).
// The /stocks ENDPOINTS and ledger data are untouched — only the surface
// moved. Research-note creation (POST /stocks/research) is still served by
// the backend; it'll resurface with the planned stocks discusser.
export default function StocksRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/finance?tab=investments");
  }, [router]);
  return null;
}
