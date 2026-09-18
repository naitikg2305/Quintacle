"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CalendarDays, FolderTree, Inbox, LayoutDashboard, MessageSquare } from "lucide-react";
import { listTodos, Todo } from "@/lib/api";
import { Panel, Stat } from "@/components/ui/Panel";

const SURFACES = [
  { href: "/kb/drop", label: "Drop", icon: Inbox, blurb: "Dump anything — text, photos, PDFs. It gets sorted for you." },
  { href: "/kb", label: "Chat", icon: MessageSquare, blurb: "Talk to your knowledge base, with the web and any model." },
  { href: "/kb/browse", label: "Browse", icon: FolderTree, blurb: "Everything you've stored, folder by folder." },
  { href: "/habits", label: "Dashboard", icon: LayoutDashboard, blurb: "Habits, targets and how the week is going." },
  { href: "/day", label: "Calendar", icon: CalendarDays, blurb: "What's due, and what actually happened, by day." },
];

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

  const todayIso = now ? now.toISOString().slice(0, 10) : "";
  const open = (todos ?? []).filter((t) => !t.done);
  const dueToday = open.filter((t) => t.due_date === todayIso).length;
  const overdue = open.filter((t) => t.due_date && t.due_date < todayIso).length;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-accent">
          {now ? now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }) : " "}
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
          {now ? greeting(now.getHours()) : "Welcome"}.
        </h1>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Due today" value={todos ? dueToday : "–"} tone={dueToday > 0 ? "warn" : "ok"} />
        <Stat label="Overdue" value={todos ? overdue : "–"} tone={overdue > 0 ? "danger" : "ok"} />
        <Stat label="Open todos" value={todos ? open.length : "–"} />
      </div>

      <Panel title="Where to">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
          {SURFACES.map((s) => (
            <Link
              key={s.href}
              href={s.href}
              className="group rounded-xl border border-line bg-surface-2/50 p-3 transition-all hover:border-accent/50 hover:shadow-glow md:p-4"
            >
              <s.icon size={22} className="text-accent" />
              <p className="mt-2 font-medium md:mt-3">{s.label}</p>
              <p className="mt-1 hidden text-sm text-muted sm:block">{s.blurb}</p>
            </Link>
          ))}
        </div>
      </Panel>
    </div>
  );
}
