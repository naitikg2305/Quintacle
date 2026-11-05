import {
  BookOpen,
  Brain,
  Briefcase,
  CalendarDays,
  FileText,
  FolderKanban,
  FolderTree,
  GraduationCap,
  House,
  Image as ImageIcon,
  KeyRound,
  Lightbulb,
  Layers,
  ListChecks,
  MessageSquare,
  Network,
  Plane,
  RefreshCw,
  ScrollText,
  Shirt,
  Target,
  User,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

// The ONE list of every page in the app (2026-11-05 nav redo). The shell's
// rail / bottom bar take the `core` group; the ⊞ Apps drawer takes the rest
// (grouped in GROUP_ORDER) and searches all of them. Adding a page later =
// one entry here — nothing else in the nav needs touching.

export type AppGroup = "core" | "life" | "productivity" | "fun" | "tools";

export type AppEntry = {
  id: string;
  href: string;
  label: string;
  icon: LucideIcon;
  group: AppGroup;
  /** Bubble tint in the drawer (any CSS colour). Defaults to the accent. */
  tint?: string;
  /** Custom active-route test; default is exact or `href/` prefix match. */
  match?: (path: string) => boolean;
  /** Extra words the drawer search matches ("money" → Finance). */
  keywords?: string;
};

export const APPS: AppEntry[] = [
  // Core — always visible (rail on desktop, bottom bar on phone).
  { id: "chat", href: "/kb", label: "Chat", icon: MessageSquare, group: "core", match: (p) => p === "/kb" || p.startsWith("/kb/drop"), keywords: "drop scratchpad ask" },
  { id: "browse", href: "/kb/browse", label: "Browse", icon: FolderTree, group: "core", match: (p) => p.startsWith("/kb/browse") || p.startsWith("/kb/folder"), keywords: "files notes kb" },
  { id: "calendar", href: "/day", label: "Calendar", icon: CalendarDays, group: "core", keywords: "day schedule" },
  { id: "graph", href: "/kb/graph", label: "Graph", icon: Network, group: "core", keywords: "connections links" },

  // Life
  { id: "journal", href: "/journal", label: "Journal", icon: BookOpen, group: "life", tint: "#a78bfa", keywords: "diary write" },
  { id: "todos", href: "/todos", label: "Todos", icon: ListChecks, group: "life", tint: "#fbbf24", keywords: "tasks" },
  { id: "habits", href: "/habits", label: "Habits", icon: Target, group: "life", tint: "#34d399", keywords: "goals budget" },
  { id: "documents", href: "/documents", label: "Documents", icon: FileText, group: "life", tint: "#60a5fa", keywords: "papers ids" },
  { id: "wardrobe", href: "/wardrobe", label: "Wardrobe", icon: Shirt, group: "life", tint: "#f472b6", keywords: "clothes outfits" },
  { id: "household", href: "/home", label: "Household", icon: House, group: "life", tint: "#fb923c", keywords: "home grooming" },
  { id: "finance", href: "/finance", label: "Finance", icon: Wallet, group: "life", tint: "#4ade80", keywords: "money spend expenses income budget subscriptions accounts 401k net worth stocks investments portfolio" },
  { id: "people", href: "/people", label: "People", icon: Users, group: "life", tint: "#38bdf8", keywords: "contacts friends" },
  { id: "profile", href: "/profile", label: "Profile", icon: User, group: "life", tint: "#22d3ee", keywords: "me targets" },
  { id: "soft-record", href: "/soft-record", label: "Chat memory", icon: Brain, group: "life", tint: "#c084fc", keywords: "soft record facts" },

  // Productivity
  { id: "projects", href: "/projects", label: "Projects", icon: FolderKanban, group: "productivity", tint: "#22d3ee", keywords: "github repos stl builds doing planned done" },
  { id: "business", href: "/business", label: "Business ideas", icon: Lightbulb, group: "productivity", tint: "#fbbf24", keywords: "startup ideas board" },
  { id: "career", href: "/career", label: "Career", icon: Briefcase, group: "productivity", tint: "#60a5fa", keywords: "minfy work roles contracts timeline experience" },
  { id: "knowledge", href: "/knowledge", label: "Knowledge", icon: GraduationCap, group: "productivity", tint: "#a78bfa", keywords: "notes topics learning tech research lectures" },
  { id: "career-updates", href: "/career/updates", label: "Career updates", icon: ScrollText, group: "productivity", tint: "#93c5fd", keywords: "record resume website work log" },

  // Fun
  { id: "travel", href: "/travel", label: "Travel", icon: Plane, group: "fun", tint: "#2dd4bf", keywords: "trips places" },
  { id: "gallery", href: "/gallery", label: "Gallery", icon: ImageIcon, group: "fun", tint: "#f472b6", keywords: "photos pictures" },

  // Tools
  { id: "batch", href: "/kb/batch", label: "Batch import", icon: Layers, group: "tools", tint: "#94a3b8", keywords: "import upload" },
  { id: "vault", href: "/vault", label: "Vault", icon: KeyRound, group: "tools", tint: "#fbbf24", keywords: "passwords secrets" },
  { id: "sync", href: "/sync", label: "Sync", icon: RefreshCw, group: "tools", tint: "#94a3b8", keywords: "phone backup" },
];

export const GROUP_ORDER: { id: Exclude<AppGroup, "core">; label: string }[] = [
  { id: "life", label: "Life" },
  { id: "productivity", label: "Productivity" },
  { id: "fun", label: "Fun" },
  { id: "tools", label: "Tools" },
];

export const CORE_APPS = APPS.filter((a) => a.group === "core");
export const DRAWER_APPS = APPS.filter((a) => a.group !== "core");

export function isAppActive(app: AppEntry, path: string): boolean {
  if (app.match) return app.match(path);
  return path === app.href || path.startsWith(app.href + "/");
}

/** The app owning a route, if any — most specific href wins (/kb/graph over /kb). */
export function appForPath(path: string): AppEntry | undefined {
  return [...APPS].sort((a, b) => b.href.length - a.href.length).find((a) => isAppActive(a, path));
}

// "Recent" row in the drawer — per-device convenience only, so plain
// localStorage, every access wrapped (private windows / blocked storage).
const RECENT_KEY = "quintacle.recentApps";

export function readRecentApps(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const ids = raw ? JSON.parse(raw) : [];
    return Array.isArray(ids) ? ids.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function pushRecentApp(id: string): void {
  try {
    const next = [id, ...readRecentApps().filter((x) => x !== id)].slice(0, 4);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // storage unavailable — the Recent row just stays empty
  }
}
