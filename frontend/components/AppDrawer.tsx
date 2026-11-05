"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { APPS, DRAWER_APPS, GROUP_ORDER, isAppActive, readRecentApps, type AppEntry } from "@/lib/apps";

// The ⊞ Apps drawer (2026-11-05): one component for phone (bottom sheet) and
// desktop (centered panel). Search over every app, a Recent row, then the
// grouped bubble grid — all driven by lib/apps.ts. Esc / backdrop close,
// Tab is trapped inside, focus returns to the opener on close.

function Bubble({ app, path, index, onPick, first }: { app: AppEntry; path: string; index: number; onPick: () => void; first?: boolean }) {
  const active = isAppActive(app, path);
  const tint = app.tint ?? "var(--color-accent)";
  return (
    <Link
      href={app.href}
      onClick={onPick}
      data-first-match={first ? "" : undefined}
      className="qa-bubble group flex flex-col items-center gap-1.5 rounded-xl p-1.5 text-center outline-none"
      style={{ "--tint": tint, animationDelay: `${Math.min(index, 18) * 18}ms` } as CSSProperties}
      aria-current={active ? "page" : undefined}
    >
      <span
        className={cn(
          "grid h-14 w-14 place-items-center rounded-full border transition-transform duration-150 group-hover:scale-110 group-focus-visible:scale-110 motion-reduce:transition-none motion-reduce:group-hover:scale-100",
          active ? "border-[var(--tint)] shadow-[0_0_18px_-2px_var(--tint)]" : "border-white/10"
        )}
        style={{
          background: `radial-gradient(circle at 30% 25%, color-mix(in srgb, ${tint} 42%, transparent), color-mix(in srgb, ${tint} 10%, #0a111d) 70%)`,
        }}
      >
        <app.icon size={22} style={{ color: tint }} />
      </span>
      <span className={cn("line-clamp-2 text-[11px] leading-tight", active ? "text-foreground" : "text-muted group-hover:text-foreground")}>
        {app.label}
      </span>
    </Link>
  );
}

export default function AppDrawer({ open, onClose, path }: { open: boolean; onClose: () => void; path: string }) {
  const [query, setQuery] = useState("");
  const [recent, setRecent] = useState<AppEntry[]>([]);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset per open
    setQuery("");
    setRecent(readRecentApps().map((id) => APPS.find((a) => a.id === id)).filter((a): a is AppEntry => !!a));
    const t = setTimeout(() => searchRef.current?.focus(), 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusable = panelRef.current.querySelectorAll<HTMLElement>("a[href], button, input");
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      opener?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const q = query.trim().toLowerCase();
  const matches = q
    ? APPS.filter((a) => `${a.label} ${a.keywords ?? ""} ${a.group}`.toLowerCase().includes(q))
    : [];

  // Stagger index per bubble across sections (Recent first, then groups).
  const sections = GROUP_ORDER.map((g) => ({ ...g, apps: DRAWER_APPS.filter((a) => a.group === g.id) })).filter((g) => g.apps.length);
  const offsets = sections.reduce<number[]>((acc, g, k) => [...acc, k === 0 ? recent.length : acc[k - 1] + sections[k - 1].apps.length], []);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center md:items-center" role="dialog" aria-modal="true" aria-label="Apps">
      <button aria-label="Close apps" tabIndex={-1} onClick={onClose} className="qa-fade absolute inset-0 bg-black/65 backdrop-blur-sm" />
      <div
        ref={panelRef}
        className="qa-pop relative flex max-h-[88dvh] w-full flex-col overflow-hidden rounded-t-3xl border border-line-strong bg-surface/95 shadow-glow md:max-w-2xl md:rounded-3xl"
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-[radial-gradient(60%_100%_at_50%_0%,rgb(34_211_238/0.14),transparent)]" />
        <div className="relative flex items-center gap-2 px-4 pb-3 pt-4">
          <label className="flex flex-1 items-center gap-2 rounded-full border border-line bg-surface-2/70 px-3 py-2 focus-within:border-accent/60">
            <Search size={16} className="text-muted" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search apps"
              aria-label="Search apps"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none focus-visible:outline-none"
              onKeyDown={(e) => {
                if (e.key === "Enter" && matches[0]) {
                  e.preventDefault();
                  (panelRef.current?.querySelector("[data-first-match]") as HTMLElement | null)?.click();
                }
              }}
            />
          </label>
          <button onClick={onClose} aria-label="Close" className="rounded-full p-2 text-muted hover:bg-white/5 hover:text-foreground">
            <X size={18} />
          </button>
        </div>

        <div className="relative overflow-y-auto px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
          {q ? (
            matches.length ? (
              <div className="grid grid-cols-4 gap-x-2 gap-y-3 sm:grid-cols-6">
                {matches.map((a, idx) => (
                  <Bubble key={a.id} app={a} path={path} index={idx} onPick={onClose} first={idx === 0} />
                ))}
              </div>
            ) : (
              <p className="py-10 text-center text-sm text-muted">No app matches “{query}”.</p>
            )
          ) : (
            <div className="space-y-4">
              {recent.length > 0 && (
                <section>
                  <h3 className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-accent/80">Recent</h3>
                  <div className="grid grid-cols-4 gap-x-2 gap-y-3 sm:grid-cols-6">
                    {recent.map((a, idx) => (
                      <Bubble key={a.id} app={a} path={path} index={idx} onPick={onClose} />
                    ))}
                  </div>
                </section>
              )}
              {sections.map((g, k) => {
                const { apps } = g;
                return (
                  <section key={g.id}>
                    <h3 className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted">
                      {g.label}
                      <span className="h-px flex-1 bg-line" />
                    </h3>
                    <div className="grid grid-cols-4 gap-x-2 gap-y-3 sm:grid-cols-6">
                      {apps.map((a, idx) => (
                        <Bubble key={a.id} app={a} path={path} index={offsets[k] + idx} onPick={onClose} />
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
