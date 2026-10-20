"use client";

import { useState } from "react";
import {
  Activity,
  Apple,
  Armchair,
  Banknote,
  Building2,
  Camera,
  ChefHat,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  CreditCard,
  Droplets,
  Dumbbell,
  FileText,
  ListChecks,
  ListOrdered,
  MapPin,
  Pill,
  Scale,
  Shirt,
  Tag,
  Target,
  TrendingUp,
  User,
  Utensils,
  type LucideIcon,
} from "lucide-react";
import { ParsedEntry } from "@/lib/api";

// The manual type-button grid, moved verbatim from the Drop page (next-wave
// §9 — chat absorbs drop): every entry type a drop can produce, added by
// hand as a blank review card (lib/entries.ts BLANK via useParsedEntries'
// addManual) — no AI call involved.
const MANUAL: { type: ParsedEntry["type"]; label: string; icon: LucideIcon }[] = [
  { type: "activity", label: "Activity", icon: Activity },
  { type: "food", label: "Food", icon: Utensils },
  { type: "exercise", label: "Exercise", icon: Dumbbell },
  { type: "substance", label: "Substance", icon: Pill },
  { type: "todo", label: "Todo", icon: ListChecks },
  { type: "body_stat", label: "Weight", icon: Scale },
  { type: "ingredient_preset", label: "Ingredient", icon: Apple },
  { type: "meal_composition", label: "Composed meal", icon: ChefHat },
  { type: "workout_routine", label: "Routine", icon: ClipboardList },
  { type: "wardrobe_item", label: "Wardrobe item", icon: Shirt },
  { type: "outfit_composition", label: "Outfit", icon: Tag },
  { type: "outfit_photo", label: "Outfit photo", icon: Camera },
  { type: "grooming_item", label: "Product", icon: Droplets },
  { type: "grooming_routine_composition", label: "Grooming routine", icon: ListOrdered },
  { type: "document_entry", label: "Document", icon: FileText },
  { type: "home_item", label: "Home item", icon: Armchair },
  { type: "residence_entry", label: "Residence", icon: Building2 },
  { type: "experience_entry", label: "Experience", icon: MapPin },
  { type: "person_entry", label: "Person", icon: User },
  { type: "credit_card_entry", label: "Credit card", icon: CreditCard },
  { type: "stock_transaction", label: "Stock trade", icon: TrendingUp },
  { type: "habit_entry", label: "Goal / budget", icon: Target },
  { type: "income", label: "Income", icon: Banknote },
];

// Collapsible by default — the scratchpad column is tight, and manual adds
// are the exception, not the rule.
export default function ManualAddGrid({ onAdd, columnsClass = "grid-cols-2" }: { onAdd: (type: ParsedEntry["type"]) => void; columnsClass?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-accent"
      >
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />} or add manually
      </button>
      {open && (
        <div className={`mt-2 grid gap-2 ${columnsClass}`}>
          {MANUAL.map((m) => (
            <button
              key={m.type}
              onClick={() => onAdd(m.type)}
              className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-left text-xs text-muted transition-colors hover:border-accent/50 hover:bg-accent/10 hover:text-foreground"
            >
              <m.icon size={15} className="shrink-0 text-accent" />
              {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
