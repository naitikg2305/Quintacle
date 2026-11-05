"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { LayoutGrid } from "lucide-react";
import { listChatModels } from "@/lib/api";
import { cn } from "@/lib/cn";
import { appForPath, CORE_APPS, DRAWER_APPS, isAppActive, pushRecentApp, type AppEntry } from "@/lib/apps";
import AppDrawer from "@/components/AppDrawer";

// 2026-11-05 nav redo: the dashboard IS "/" (no Home tab — the logo goes
// there). Four core surfaces — Chat, Browse, Calendar, Graph — plus the
// ⊞ Apps drawer for everything else. Desktop: slim icon rail. Phone: a
// 5-slot bottom bar with Apps as the raised centre button. Every page comes
// from lib/apps.ts.

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2" aria-label="Quintacle — dashboard">
      <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_10px_2px_rgb(34_211_238/0.7)]" />
      <span className="font-mono text-sm font-semibold tracking-[0.32em] text-accent">QUINTACLE</span>
    </Link>
  );
}

// Backend heartbeat + clock — the little "systems online" readout.
function StatusReadout({ className, compact }: { className?: string; compact?: boolean }) {
  const [online, setOnline] = useState<boolean | null>(null);
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    let alive = true;
    const ping = () =>
      listChatModels()
        .then(() => alive && setOnline(true))
        .catch(() => alive && setOnline(false));
    ping();
    setNow(new Date());
    const pingTimer = setInterval(ping, 30_000);
    const clockTimer = setInterval(() => setNow(new Date()), 30_000);
    return () => {
      alive = false;
      clearInterval(pingTimer);
      clearInterval(clockTimer);
    };
  }, []);

  const dot = (
    <span
      className={cn(
        "h-1.5 w-1.5 rounded-full",
        online === null ? "bg-muted" : online ? "bg-ok shadow-[0_0_8px_rgb(52_211_153/0.8)]" : "bg-danger"
      )}
    />
  );

  if (compact) {
    return (
      <div
        className={cn("flex flex-col items-center gap-1 font-mono text-[9px] uppercase tracking-wider text-muted", className)}
        title={online === null ? "Checking backend…" : online ? "Backend online" : "Backend offline"}
      >
        {dot}
        {now && (
          <span suppressHydrationWarning>
            {now.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }).replace(/\s?[AP]M$/i, "")}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className={cn("flex items-center gap-3 font-mono text-[10px] uppercase tracking-wider text-muted", className)}>
      <span className="flex items-center gap-1.5">
        {dot}
        {online === null ? "…" : online ? "online" : "offline"}
      </span>
      {now && (
        <span suppressHydrationWarning>
          {now.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ·{" "}
          {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
        </span>
      )}
    </div>
  );
}

function RailItem({ app, active }: { app: AppEntry; active: boolean }) {
  return (
    <Link
      href={app.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex w-full flex-col items-center gap-1 rounded-xl py-2 text-[10px] transition-colors",
        active ? "text-accent" : "text-muted hover:text-foreground"
      )}
    >
      {active && <span className="absolute left-0 top-1/2 h-7 w-0.5 -translate-y-1/2 rounded-r bg-accent shadow-[0_0_8px_rgb(34_211_238/0.9)]" />}
      <span
        className={cn(
          "grid h-9 w-9 place-items-center rounded-xl transition-colors",
          active ? "bg-accent/12 shadow-glow" : "group-hover:bg-white/5"
        )}
      >
        <app.icon size={18} />
      </span>
      {app.label}
    </Link>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [appsOpen, setAppsOpen] = useState(false);
  const closeApps = useCallback(() => setAppsOpen(false), []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- close on navigation
    setAppsOpen(false);
    const app = appForPath(path);
    if (app && app.group !== "core") pushRecentApp(app.id);
  }, [path]);

  const appsActive = DRAWER_APPS.some((a) => isAppActive(a, path));
  const [chat, browse, calendar, graph] = CORE_APPS;

  return (
    <div className="min-h-dvh">
      {/* Desktop: slim icon rail */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-20 flex-col items-center border-r border-line bg-surface/70 px-2 py-4 backdrop-blur-md md:flex">
        <Link
          href="/"
          aria-label="Quintacle — dashboard"
          aria-current={path === "/" ? "page" : undefined}
          className={cn(
            "mb-4 grid h-11 w-11 place-items-center rounded-2xl border font-mono text-lg font-bold transition-colors",
            path === "/" ? "border-accent/60 bg-accent/15 text-accent shadow-glow" : "border-line text-accent hover:border-accent/50"
          )}
        >
          Q
        </Link>
        <nav className="flex w-full flex-1 flex-col items-center gap-1" aria-label="Main">
          {CORE_APPS.map((app) => (
            <RailItem key={app.id} app={app} active={isAppActive(app, path)} />
          ))}
        </nav>
        <StatusReadout compact className="mb-3" />
        <button
          onClick={() => setAppsOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={appsOpen}
          className={cn(
            "flex w-full flex-col items-center gap-1 rounded-xl py-2 text-[10px] transition-colors",
            appsActive ? "text-accent" : "text-muted hover:text-foreground"
          )}
        >
          <span className="qa-glow grid h-10 w-10 place-items-center rounded-full bg-accent/15 text-accent">
            <LayoutGrid size={18} />
          </span>
          Apps
        </button>
      </aside>

      {/* Phone: slim top strip */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-background/80 px-4 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur-md md:hidden">
        <Logo />
        <StatusReadout />
      </header>

      <main className="px-4 py-4 pb-28 md:ml-20 md:px-6 md:py-6 md:pb-8">{children}</main>

      {/* Phone: 5-slot bottom bar — Apps raised in the centre */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 items-end border-t border-line-strong bg-surface/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
      >
        {[chat, browse].map((app) => (
          <BarItem key={app.id} app={app} active={isAppActive(app, path)} />
        ))}
        <button
          onClick={() => setAppsOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={appsOpen}
          className={cn("relative flex flex-col items-center pb-2 text-[10px]", appsActive ? "text-accent" : "text-muted")}
        >
          <span className="qa-glow -mt-5 mb-0.5 grid h-14 w-14 place-items-center rounded-full border border-accent/50 bg-[radial-gradient(circle_at_35%_30%,rgb(34_211_238/0.45),#0a111d_75%)] text-accent">
            <LayoutGrid size={24} />
          </span>
          Apps
        </button>
        {[calendar, graph].map((app) => (
          <BarItem key={app.id} app={app} active={isAppActive(app, path)} />
        ))}
      </nav>

      <AppDrawer open={appsOpen} onClose={closeApps} path={path} />
    </div>
  );
}

function BarItem({ app, active }: { app: AppEntry; active: boolean }) {
  return (
    <Link
      href={app.href}
      aria-current={active ? "page" : undefined}
      className={cn("flex flex-col items-center gap-0.5 py-2 text-[10px]", active ? "text-accent" : "text-muted")}
    >
      <app.icon size={20} className={active ? "drop-shadow-[0_0_6px_rgb(34_211_238/0.8)]" : ""} />
      {app.label}
    </Link>
  );
}
