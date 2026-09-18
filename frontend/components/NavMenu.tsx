"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/kb", label: "Knowledge Base" },
  { href: "/kb/browse", label: "Browse Files" },
  { href: "/kb/drop", label: "Drop" },
  { href: "/journal", label: "Journal" },
  { href: "/kb/batch", label: "Batch Import" },
  { href: "/kb/graph", label: "Graph" },
  { href: "/documents", label: "Documents" },
  { href: "/home", label: "Home Inventory" },
  { href: "/travel", label: "Travel" },
  { href: "/finance", label: "Finance" },
  { href: "/people", label: "People" },
  { href: "/wardrobe", label: "Wardrobe" },
  { href: "/gallery", label: "Gallery" },
  { href: "/habits", label: "Dashboard" },
  { href: "/day", label: "Day View" },
  { href: "/todos", label: "Todos" },
  { href: "/profile", label: "Profile" },
];

export default function NavMenu() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  return (
    <>
      <nav className="flex items-center justify-between border-b border-black/10 dark:border-white/10 px-6 py-3">
        <Link href="/" className="font-semibold text-sm" onClick={() => setOpen(false)}>
          Quintacle
        </Link>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle menu"
          aria-expanded={open}
          className="flex flex-col gap-1.5 p-2 -mr-2"
        >
          <span className="block w-5 h-0.5 bg-current" />
          <span className="block w-5 h-0.5 bg-current" />
          <span className="block w-5 h-0.5 bg-current" />
        </button>
      </nav>

      {open && (
        <div className="fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <div className="relative ml-auto w-72 max-w-[85vw] h-full bg-white dark:bg-black border-l border-black/10 dark:border-white/10 p-4 space-y-1 overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <span className="font-semibold text-sm">Menu</span>
              <button onClick={() => setOpen(false)} className="text-sm opacity-60 hover:opacity-100 px-2">
                ✕
              </button>
            </div>
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className={`block rounded px-3 py-2 text-sm hover:bg-black/5 dark:hover:bg-white/10 ${
                  pathname === link.href ? "bg-black/5 dark:bg-white/10 font-medium" : ""
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
