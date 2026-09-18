import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

// No fixed width here: callers that pass their own `w-*` class (w-28, w-auto...)
// get it; everyone else gets full width. (Two conflicting utilities on one
// element resolve by stylesheet order, not className order.)
const BASE =
  "rounded-lg border border-line bg-surface px-3 py-2 text-sm text-foreground placeholder:text-muted/70 transition-colors focus:border-accent/60 focus:outline-none focus:ring-1 focus:ring-accent/40";

const widthFor = (className?: string) => (/(^|\s)!?w-/.test(className ?? "") ? "" : "w-full");

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(BASE, widthFor(className), className)} />;
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(BASE, widthFor(className), "pr-8", className)} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(BASE, widthFor(className), "resize-y", className)} />;
}
