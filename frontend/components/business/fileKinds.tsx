import { Box, File as FileGeneric, FileSpreadsheet, FileText, Film, Image as ImageIcon, Link2, NotebookText, Presentation } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { IdeaFileKind, IdeaStatus } from "@/lib/businessApi";

export const KIND_META: Record<IdeaFileKind, { label: string; icon: LucideIcon }> = {
  markdown: { label: "Notes", icon: NotebookText },
  image: { label: "Images", icon: ImageIcon },
  video: { label: "Videos", icon: Film },
  pdf: { label: "PDFs", icon: FileText },
  doc: { label: "Documents", icon: Presentation },
  spreadsheet: { label: "Spreadsheets", icon: FileSpreadsheet },
  model: { label: "3D models", icon: Box },
  link: { label: "Links", icon: Link2 },
  other: { label: "Other files", icon: FileGeneric },
};

export const KIND_ORDER: IdeaFileKind[] = ["markdown", "image", "video", "pdf", "doc", "spreadsheet", "model", "link", "other"];

export const STATUS_LABEL: Record<IdeaStatus, string> = {
  idea: "Idea",
  exploring: "Exploring",
  validating: "Validating",
  building: "Building",
  parked: "Parked",
  dropped: "Dropped",
};

export function statusTone(s: IdeaStatus): "accent" | "ok" | "warn" | "danger" | "muted" {
  switch (s) {
    case "exploring":
      return "accent";
    case "validating":
      return "warn";
    case "building":
      return "ok";
    case "dropped":
      return "danger";
    default:
      return "muted";
  }
}

export function FileKindCounts({ counts }: { counts: Partial<Record<IdeaFileKind, number>> }) {
  const kinds = KIND_ORDER.filter((k) => (counts[k] ?? 0) > 0);
  if (kinds.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
      {kinds.map((k) => {
        const { icon: Icon, label } = KIND_META[k];
        return (
          <span key={k} title={label} className="inline-flex items-center gap-1 font-mono text-[11px] text-muted">
            <Icon size={12} className="text-accent/80" />
            {counts[k]}
          </span>
        );
      })}
    </div>
  );
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
