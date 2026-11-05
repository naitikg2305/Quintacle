"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// 2026-11-05: Investments folded into the unified Finances page. Client-side
// redirect so old links work in the Capacitor static export too.
export default function InvestmentsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/finance?tab=investments");
  }, [router]);
  return null;
}
