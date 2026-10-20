"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  BookOpen,
  CalendarDays,
  Ellipsis,
  FileText,
  FolderTree,
  House,
  Image as ImageIcon,
  KeyRound,
  Layers,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Network,
  Plane,
  RefreshCw,
  Shirt,
  TrendingUp,
  User,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { listChatModels } from "@/lib/api";
import { cn } from "@/lib/cn";
import { BottomSheet } from "@/components/ui/BottomSheet";

type NavItem = { href: string; label: string; icon: LucideIcon; match?: (path: string) => boolean };

// The four surfaces the app is built around — also the phone's bottom tabs.
// Drop retired into Chat (next-wave §9): the chat page's scratchpad is the
// drop lane now; /kb/drop redirects there.
const CORE: NavItem[] = [
  { href: "/kb", label: "Chat", icon: MessageSquare, match: (p) => p === "/kb" || p.startsWith("/kb/drop") },
  { href: "/kb/browse", label: "Browse", icon: FolderTree, match: (p) => p.startsWith("/kb/browse") || p.startsWith("/kb/folder") },
  { href: "/habits", label: "Dashboard", icon: LayoutDashboard },
  { href: "/day", label: "Calendar", icon: CalendarDays },
];

// §10 home-page regroup, mirrored here: Life · Productivity · Fun.
const LIFE: NavItem[] = [
  { href: "/journal", label: "Journal", icon: BookOpen },
  { href: "/todos", label: "Todos", icon: ListChecks },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/wardrobe", label: "Wardrobe", icon: Shirt },
  { href: "/home", label: "Home", icon: House },
  { href: "/finance", label: "Finance", icon: Wallet },
  { href: "/people", label: "People", icon: Users },
  { href: "/profile", label: "Profile", icon: User },
];

const PRODUCTIVITY: NavItem[] = [
  { href: "/stocks", label: "Stocks", icon: TrendingUp },
];

const FUN: NavItem[] = [
  { href: "/travel", label: "Travel", icon: Plane },
  { href: "/gallery", label: "Gallery", icon: ImageIcon },
];

const TOOLS: NavItem[] = [
  { href: "/kb/batch", label: "Batch import", icon: Layers },
  { href: "/kb/graph", label: "Graph", icon: Network },
  { href: "/vault", label: "Vault", icon: KeyRound },
  { href: "/sync", label: "Sync", icon: RefreshCw },
];

function isActive(item: NavItem, path: string): boolean {
  if (item.match) return item.match(path);
  return path === item.href || path.startsWith(item.href + "/");
}

function Logo({ onClick }: { onClick?: () => void }) {
  return (
    <Link href="/" onClick={onClick} className="flex items-center gap-2">
      <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_10px_2px_rgb(34_211_238/0.7)]" />
      <span className="font-mono text-sm font-semibold tracking-[0.32em] text-accent">QUINTACLE</span>
    </Link>
  );
}

// Backend heartbeat + clock — the little "systems online" readout.
function StatusReadout({ className }: { className?: string }) {
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

  return (
    <div className={cn("flex items-center gap-3 font-mono text-[10px] uppercase tracking-wider text-muted", className)}>
      <span className="flex items-center gap-1.5">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            online === null ? "bg-muted" : online ? "bg-ok shadow-[0_0_8px_rgb(52_211_153/0.8)]" : "bg-danger"
          )}
        />
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

function SidebarGroup({ label, items, path }: { label: string; items: NavItem[]; path: string }) {
  return (
    <div className="space-y-0.5">
      <p className="px-3 pb-1 pt-3 font-mono text-[10px] uppercase tracking-[0.18em] text-muted/70">{label}</p>
      {items.map((item) => {
        const active = isActive(item, path);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              active
                ? "bg-accent/10 text-accent shadow-[inset_2px_0_0_var(--color-accent)]"
                : "text-muted hover:bg-white/5 hover:text-foreground"
            )}
          >
            <item.icon size={16} />
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    setMoreOpen(false);
  }, [path]);

  const moreActive = [...LIFE, ...PRODUCTIVITY, ...FUN, ...TOOLS].some((i) => isActive(i, path));

  return (
    <div className="min-h-dvh">
      {/* Desktop: fixed sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-surface/70 px-3 py-4 backdrop-blur-md md:flex">
        <div className="px-3 pb-2">
          <Logo />
        </div>
        <nav className="flex-1 overflow-y-auto">
          <SidebarGroup label="Core" items={CORE} path={path} />
          <SidebarGroup label="Life" items={LIFE} path={path} />
          <SidebarGroup label="Productivity" items={PRODUCTIVITY} path={path} />
          <SidebarGroup label="Fun" items={FUN} path={path} />
          <SidebarGroup label="Tools" items={TOOLS} path={path} />
        </nav>
        <StatusReadout className="border-t border-line px-3 pt-3" />
      </aside>

      {/* Phone: slim top strip */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-background/80 px-4 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur-md md:hidden">
        <Logo />
        <StatusReadout />
      </header>

      <main className="px-4 py-4 pb-28 md:ml-60 md:px-6 md:py-6 md:pb-8">{children}</main>

      {/* Phone: bottom tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line-strong bg-surface/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden">
        {CORE.map((item) => {
          const active = isActive(item, path);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn("flex flex-col items-center gap-0.5 py-2 text-[10px]", active ? "text-accent" : "text-muted")}
            >
              <item.icon size={20} className={active ? "drop-shadow-[0_0_6px_rgb(34_211_238/0.8)]" : ""} />
              {item.label}
            </Link>
          );
        })}
        <button
          onClick={() => setMoreOpen(true)}
          className={cn("flex flex-col items-center gap-0.5 py-2 text-[10px]", moreActive ? "text-accent" : "text-muted")}
        >
          <Ellipsis size={20} />
          More
        </button>
      </nav>

      <BottomSheet open={moreOpen} onClose={() => setMoreOpen(false)} title="All sections">
        <div className="grid grid-cols-3 gap-2">
          {[...LIFE, ...PRODUCTIVITY, ...FUN, ...TOOLS].map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex flex-col items-center gap-1.5 rounded-lg border p-3 text-xs",
                isActive(item, path) ? "border-accent/50 bg-accent/10 text-accent" : "border-line text-muted"
              )}
            >
              <item.icon size={20} />
              {item.label}
            </Link>
          ))}
        </div>
      </BottomSheet>
    </div>
  );
}
