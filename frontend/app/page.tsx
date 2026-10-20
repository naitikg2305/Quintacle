"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  BookOpen,
  BookUser,
  Briefcase,
  CalendarDays,
  FileText,
  FolderKanban,
  FolderTree,
  GraduationCap,
  House,
  Image as ImageIcon,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Plane,
  Shirt,
  Target,
  TrendingUp,
  User,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { listTodos, Todo } from "@/lib/api";
import { Panel, Stat } from "@/components/ui/Panel";
import { todayIso } from "@/lib/date";

type Tile = { href: string; label: string; icon: LucideIcon; blurb: string };

// Folder tiles open the EXISTING browse surface at that root — no new pages.
const browse = (path: string) => `/kb/browse?path=${encodeURIComponent(path)}`;

// §10 home-page regroup: the owner's clusters — Me (small, top) · Life ·
// Productivity · Fun — presentation only, every destination already exists.
// Chat is the primary surface (it absorbed Drop in §9), so it stays above
// the clusters rather than buried in one.

const ME: Tile[] = [
  { href: browse("Me"), label: "Me", icon: BookUser, blurb: "Your quick-reference self." },
  { href: "/profile", label: "Profile", icon: User, blurb: "Body stats and targets." },
];

const LIFE: Tile[] = [
  { href: "/journal", label: "Journal", icon: BookOpen, blurb: "The daily log — write the day, it files itself." },
  { href: "/day", label: "Calendar", icon: CalendarDays, blurb: "What's due, and what actually happened, by day." },
  { href: "/todos", label: "Todos", icon: ListChecks, blurb: "Everything open, due and done." },
  { href: "/habits", label: "Dashboard", icon: LayoutDashboard, blurb: "Habits and targets — fitness, nutrition, spend — and how the week is going." },
  { href: "/wardrobe", label: "Wardrobe", icon: Shirt, blurb: "Clothes, outfits and what you actually wear." },
  { href: "/finance", label: "Finance", icon: Wallet, blurb: "The spending ledger, cards and budgets." },
  { href: "/home", label: "Home", icon: House, blurb: "The household — records and upkeep." },
  { href: "/documents", label: "Documents", icon: FileText, blurb: "IDs, statements, paperwork — filed and findable." },
  { href: "/people", label: "People", icon: Users, blurb: "Everyone you know, and everything connected to them." },
];

const PRODUCTIVITY: Tile[] = [
  { href: browse("Career"), label: "Career", icon: Briefcase, blurb: "One folder per employer — roles, docs, history." },
  { href: browse("Projects"), label: "Projects", icon: FolderKanban, blurb: "Endeavors — idea, active, archived." },
  { href: browse("Knowledge"), label: "Knowledge", icon: GraduationCap, blurb: "Lectures, research and reference." },
  { href: "/stocks", label: "Stocks", icon: TrendingUp, blurb: "Research notes and the trade ledger." },
  { href: "/day", label: "Goals calendar", icon: Target, blurb: "Habits week by week, met or missed — the calendar's Habits tab." },
];

const FUN: Tile[] = [
  { href: "/travel", label: "Travel", icon: Plane, blurb: "Trips taken and places visited." },
  { href: "/gallery", label: "Gallery", icon: ImageIcon, blurb: "Photos — who, where, what." },
];

const CLUSTERS: { title: string; tiles: Tile[] }[] = [
  { title: "Life", tiles: LIFE },
  { title: "Productivity", tiles: PRODUCTIVITY },
  { title: "Fun", tiles: FUN },
];

function TileLink({ tile }: { tile: Tile }) {
  return (
    <Link
      href={tile.href}
      className="group rounded-xl border border-line bg-surface-2/50 p-3 transition-all hover:border-accent/50 hover:shadow-glow md:p-4"
    >
      <tile.icon size={22} className="text-accent" />
      <p className="mt-2 font-medium md:mt-3">{tile.label}</p>
      <p className="mt-1 hidden text-sm text-muted sm:block">{tile.blurb}</p>
    </Link>
  );
}

function greeting(hour: number): string {
  if (hour < 5) return "Late night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function Home() {
  const [todos, setTodos] = useState<Todo[] | null>(null);
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    listTodos().then(setTodos).catch(() => setTodos([]));
  }, []);

  const today = now ? todayIso() : "";
  const open = (todos ?? []).filter((t) => !t.done);
  const dueToday = open.filter((t) => t.due_date === today).length;
  const overdue = open.filter((t) => t.due_date && t.due_date < today).length;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-accent">
            {now ? now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }) : " "}
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
            {now ? greeting(now.getHours()) : "Welcome"}.
          </h1>
        </div>
        {/* Me, small at top: the quick-reference self (§10). */}
        <div className="flex flex-wrap gap-2">
          {ME.map((t) => (
            <Link
              key={t.label}
              href={t.href}
              title={t.blurb}
              className="flex items-center gap-1.5 rounded-lg border border-line bg-surface-2/50 px-3 py-1.5 text-sm text-muted transition-colors hover:border-accent/50 hover:text-foreground"
            >
              <t.icon size={14} className="text-accent" />
              {t.label}
            </Link>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Due today" value={todos ? dueToday : "–"} tone={dueToday > 0 ? "warn" : "ok"} />
        <Stat label="Overdue" value={todos ? overdue : "–"} tone={overdue > 0 ? "danger" : "ok"} />
        <Stat label="Open todos" value={todos ? open.length : "–"} />
      </div>

      {/* The primary surface: Chat absorbed Drop (§9), so one big tile covers both. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link
          href="/kb"
          className="group flex items-start gap-4 rounded-xl border border-accent/40 bg-surface-2/50 p-4 transition-all hover:border-accent/70 hover:shadow-glow sm:col-span-2 md:p-5"
        >
          <MessageSquare size={26} className="shrink-0 text-accent" />
          <div>
            <p className="font-medium md:text-lg">Chat</p>
            <p className="mt-1 text-sm text-muted">
              Talk to your knowledge base — and drop anything: text, photos, PDFs get sorted for you.
            </p>
          </div>
        </Link>
        <Link
          href="/kb/browse"
          className="group flex items-start gap-4 rounded-xl border border-line bg-surface-2/50 p-4 transition-all hover:border-accent/50 hover:shadow-glow md:p-5"
        >
          <FolderTree size={26} className="shrink-0 text-accent" />
          <div>
            <p className="font-medium md:text-lg">Browse</p>
            <p className="mt-1 text-sm text-muted">Everything you&apos;ve stored, folder by folder.</p>
          </div>
        </Link>
      </div>

      {CLUSTERS.map((c) => (
        <Panel key={c.title} title={c.title}>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {c.tiles.map((t) => (
              <TileLink key={t.label} tile={t} />
            ))}
          </div>
        </Panel>
      ))}
    </div>
  );
}
