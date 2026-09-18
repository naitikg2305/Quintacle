import type { HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

// The HUD card: dark glass surface, thin cyan-tinted border, optional
// header strip with a mono uppercase label (the "instrument panel" look).
export function Panel({
  title,
  icon: Icon,
  actions,
  className,
  bodyClassName,
  children,
  ...props
}: Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
  title?: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section
      {...props}
      className={cn("rounded-xl border border-line bg-surface/80 shadow-panel backdrop-blur-sm", className)}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
            {Icon && <Icon size={14} />}
            {title}
          </h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Badge({
  tone = "accent",
  className,
  children,
}: {
  tone?: "accent" | "ok" | "warn" | "danger" | "muted";
  className?: string;
  children: ReactNode;
}) {
  const tones = {
    accent: "border-accent/40 text-accent bg-accent/10",
    ok: "border-ok/40 text-ok bg-ok/10",
    warn: "border-warn/40 text-warn bg-warn/10",
    danger: "border-danger/40 text-danger bg-danger/10",
    muted: "border-line text-muted bg-white/5",
  };
  return (
    <span className={cn("inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider", tones[tone], className)}>
      {children}
    </span>
  );
}

// A single readout: small mono label over a big number.
export function Stat({
  label,
  value,
  hint,
  tone = "accent",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "accent" | "ok" | "warn" | "danger";
}) {
  const color = { accent: "text-accent", ok: "text-ok", warn: "text-warn", danger: "text-danger" }[tone];
  return (
    <div className="rounded-lg border border-line bg-surface-2/60 p-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">{label}</p>
      <p className={cn("mt-1 font-mono text-2xl font-semibold leading-none", color)}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  icon: Icon,
  actions,
}: {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2.5 text-xl font-semibold tracking-tight md:text-2xl">
          {Icon && <Icon size={22} className="text-accent" />}
          {title}
        </h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon, children }: { icon?: LucideIcon; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line p-6 text-center text-sm text-muted">
      {Icon && <Icon size={22} className="text-accent/60" />}
      {children}
    </div>
  );
}
