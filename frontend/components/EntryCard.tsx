"use client";

import { ExerciseSet, FINANCE_KINDS, Meal, ParsedEntry } from "@/lib/api";
import MealCompositionEditor from "./MealCompositionEditor";
import StatementImportCard from "./StatementImportCard";
import OutfitEditor from "./OutfitEditor";
import GroomingRoutineEditor from "./GroomingRoutineEditor";

const WARDROBE_CATEGORIES = ["jacket", "pants", "shirt", "shoes", "sunglasses", "accessory"];
const GROOMING_CATEGORIES = ["skincare", "haircare", "shaving", "oral", "fragrance", "tool"];
const DOC_TYPES = ["lease", "id", "passport", "immigration", "insurance", "medical", "financial", "warranty"];
const HOME_CATEGORIES = ["furniture", "decor", "electronics", "kitchen", "appliance", "storage"];
const PEOPLE_CATEGORIES = ["friend", "dating", "family", "coworker", "acquaintance", "other"];

const ACTIVITY_CATEGORIES = ["productivity", "social", "leisure", "yourself", "emotional"];
const MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"];

type Props = {
  entry: ParsedEntry;
  index: number;
  meals: Meal[];
  exerciseNames: string[];
  onUpdate: (i: number, patch: Partial<ParsedEntry>) => void;
  onRemove: (i: number) => void;
  onUpdateSet: (entryIndex: number, setIndex: number, patch: Partial<ExerciseSet>) => void;
  onAddSet: (entryIndex: number) => void;
  onRemoveSet: (entryIndex: number, setIndex: number) => void;
};

// One editable row per parsed entry, shared by the Journal page's nightly
// dump and the general Drop page — both produce the same ParsedEntry union,
// so both review it the same way before committing (Approval before write).
export default function EntryCard({ entry, index: i, meals, exerciseNames, onUpdate, onRemove, onUpdateSet, onAddSet, onRemoveSet }: Props) {
  return (
    <div className="flex gap-2 items-start border-b pb-2 last:border-b-0">
      <span className="text-xs uppercase opacity-50 w-16 pt-2 shrink-0">{entry.type.replace("_", " ")}</span>

      {"entry_date" in entry && (
        <input
          type="date"
          className="border rounded px-1 py-1 text-xs w-32 shrink-0"
          value={entry.entry_date ?? ""}
          title="Date this happened — resolved from the text if stated, blank uses today/the page's date"
          onChange={(e) => onUpdate(i, { entry_date: e.target.value || null })}
        />
      )}

      {entry.type === "activity" && (
        <>
          <select
            className="border rounded px-2 py-1 text-sm"
            value={entry.category}
            onChange={(e) => onUpdate(i, { category: e.target.value })}
          >
            {ACTIVITY_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="description"
            value={entry.description}
            onChange={(e) => onUpdate(i, { description: e.target.value })}
          />
          <input
            type="number"
            step="0.25"
            min="0"
            className="border rounded px-2 py-1 w-20 text-sm"
            value={entry.hours}
            onChange={(e) => onUpdate(i, { hours: Number(e.target.value) })}
          />
        </>
      )}

      {entry.type === "food" && (
        <>
          <select
            className="border rounded px-2 py-1 text-sm"
            value={entry.meal_type}
            onChange={(e) => onUpdate(i, { meal_type: e.target.value })}
          >
            {MEAL_TYPES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="what did you eat"
            value={entry.description}
            onChange={(e) => onUpdate(i, { description: e.target.value })}
          />
          {entry.meal_id ? (
            <span className="text-sm px-2 py-1 rounded bg-black/5 dark:bg-white/10 whitespace-nowrap">
              {meals.find((m) => m.id === entry.meal_id)?.name ?? `meal #${entry.meal_id}`} (preset)
            </span>
          ) : (
            <input
              type="number"
              min="0"
              className="border rounded px-2 py-1 w-24 text-sm"
              placeholder="kcal"
              value={entry.estimated_kcal}
              onChange={(e) => onUpdate(i, { estimated_kcal: Number(e.target.value) })}
            />
          )}
        </>
      )}

      {entry.type === "exercise" && (
        <div className="flex-1 space-y-1">
          <input
            className="border rounded px-2 py-1 text-sm font-semibold w-full"
            placeholder="exercise name"
            list="entry-card-exercise-names"
            value={entry.exercise_name}
            onChange={(e) => onUpdate(i, { exercise_name: e.target.value })}
          />
          <input
            className="border rounded px-2 py-1 text-xs w-full opacity-70"
            placeholder="notes (optional)"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
          {entry.sets.map((s, si) => (
            <div key={si} className="flex gap-1 items-center text-xs">
              <span className="opacity-40 w-4">{si + 1}</span>
              <input
                type="number"
                placeholder="reps"
                className="border rounded px-1 py-0.5 w-14"
                value={s.reps ?? ""}
                onChange={(e) => onUpdateSet(i, si, { reps: e.target.value ? Number(e.target.value) : null })}
              />
              <input
                type="number"
                placeholder="weight"
                className="border rounded px-1 py-0.5 w-16"
                value={s.weight ?? ""}
                onChange={(e) => onUpdateSet(i, si, { weight: e.target.value ? Number(e.target.value) : null })}
              />
              <span className="opacity-40">or</span>
              <input
                type="number"
                placeholder="min"
                className="border rounded px-1 py-0.5 w-14"
                value={s.duration_min ?? ""}
                onChange={(e) => onUpdateSet(i, si, { duration_min: e.target.value ? Number(e.target.value) : null })}
              />
              <input
                type="number"
                placeholder="dist"
                className="border rounded px-1 py-0.5 w-14"
                value={s.distance ?? ""}
                onChange={(e) => onUpdateSet(i, si, { distance: e.target.value ? Number(e.target.value) : null })}
              />
              <input
                type="number"
                placeholder="kcal burned"
                className="border rounded px-1 py-0.5 w-20"
                value={s.calories_burned ?? ""}
                onChange={(e) => onUpdateSet(i, si, { calories_burned: e.target.value ? Number(e.target.value) : null })}
              />
              <button onClick={() => onRemoveSet(i, si)} className="opacity-50 hover:opacity-100 px-1">
                ✕
              </button>
            </div>
          ))}
          <button onClick={() => onAddSet(i)} className="text-xs underline opacity-70 hover:opacity-100">
            + add set
          </button>
          <datalist id="entry-card-exercise-names">
            {exerciseNames.map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
        </div>
      )}

      {entry.type === "substance" && (
        <>
          <input
            className="border rounded px-2 py-1 text-sm w-32"
            placeholder="substance"
            value={entry.substance}
            onChange={(e) => onUpdate(i, { substance: e.target.value })}
          />
          <input
            type="number"
            min="0"
            className="border rounded px-2 py-1 w-20 text-sm"
            placeholder="amount"
            value={entry.amount}
            onChange={(e) => onUpdate(i, { amount: Number(e.target.value) })}
          />
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </>
      )}

      {entry.type === "todo" && (
        <>
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="title"
            value={entry.title}
            onChange={(e) => onUpdate(i, { title: e.target.value })}
          />
          <input
            type="date"
            className="border rounded px-2 py-1 text-sm"
            value={entry.due_date ?? ""}
            onChange={(e) => onUpdate(i, { due_date: e.target.value || null })}
          />
          <input
            type="time"
            className="border rounded px-2 py-1 text-sm w-24"
            value={entry.start_time ?? ""}
            onChange={(e) => onUpdate(i, { start_time: e.target.value || null })}
          />
          <span className="opacity-40 text-sm">to</span>
          <input
            type="time"
            className="border rounded px-2 py-1 text-sm w-24"
            value={entry.end_time ?? ""}
            onChange={(e) => onUpdate(i, { end_time: e.target.value || null })}
          />
          <select
            className="border rounded px-2 py-1 text-sm"
            value={entry.priority}
            onChange={(e) => onUpdate(i, { priority: Number(e.target.value) })}
          >
            <option value={1}>low</option>
            <option value={2}>medium</option>
            <option value={3}>high</option>
            <option value={4}>urgent</option>
          </select>
        </>
      )}

      {entry.type === "body_stat" && (
        <>
          <input
            className="border rounded px-2 py-1 text-sm w-28"
            placeholder="metric"
            value={entry.metric}
            onChange={(e) => onUpdate(i, { metric: e.target.value })}
          />
          <input
            type="number"
            className="border rounded px-2 py-1 text-sm w-24"
            placeholder="value"
            value={entry.value}
            onChange={(e) => onUpdate(i, { value: Number(e.target.value) })}
          />
          <select
            className="border rounded px-2 py-1 text-sm"
            value={entry.unit}
            onChange={(e) => onUpdate(i, { unit: e.target.value })}
          >
            <option value="lb">lb</option>
            <option value="kg">kg</option>
            <option value="%">%</option>
          </select>
        </>
      )}

      {entry.type === "finance" && (
        <>
          <input
            type="number"
            step="0.01"
            min="0"
            className="border rounded px-2 py-1 w-24 text-sm"
            placeholder="amount"
            value={entry.amount}
            onChange={(e) => onUpdate(i, { amount: Number(e.target.value) })}
          />
          <input
            className="border rounded px-2 py-1 text-sm w-32"
            placeholder="merchant"
            value={entry.merchant}
            onChange={(e) => onUpdate(i, { merchant: e.target.value })}
          />
          <input
            className="border rounded px-2 py-1 text-sm w-28"
            placeholder="category"
            value={entry.category}
            onChange={(e) => onUpdate(i, { category: e.target.value })}
          />
          <select
            className="border rounded px-2 py-1 text-sm"
            value={entry.kind}
            onChange={(e) => onUpdate(i, { kind: e.target.value as typeof entry.kind })}
          >
            {FINANCE_KINDS.map((k) => (
              <option key={k} value={k}>
                {k.replace("_", " ")}
              </option>
            ))}
          </select>
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </>
      )}

      {entry.type === "income" && (
        <>
          <input
            type="number"
            step="0.01"
            min="0"
            className="border rounded px-2 py-1 w-24 text-sm"
            placeholder="amount"
            value={entry.amount}
            onChange={(e) => onUpdate(i, { amount: Number(e.target.value) })}
          />
          <input
            className="border rounded px-2 py-1 text-sm w-40"
            placeholder="source (employer, sale...)"
            value={entry.source}
            onChange={(e) => onUpdate(i, { source: e.target.value })}
          />
          <select
            className="border rounded px-2 py-1 text-sm"
            value={entry.kind}
            onChange={(e) => onUpdate(i, { kind: e.target.value })}
          >
            <option value="salary">salary</option>
            <option value="other">other</option>
          </select>
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </>
      )}

      {entry.type === "statement_import" && (
        <StatementImportCard entry={entry} onUpdate={(patch) => onUpdate(i, patch)} />
      )}

      {entry.type === "kb_entry" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm w-56"
              placeholder="folder"
              value={entry.folder}
              onChange={(e) => onUpdate(i, { folder: e.target.value })}
            />
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="title"
              value={entry.title}
              onChange={(e) => onUpdate(i, { title: e.target.value })}
            />
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={4}
            value={entry.content}
            onChange={(e) => onUpdate(i, { content: e.target.value })}
          />
          <input
            className="w-full border rounded px-2 py-1 text-xs opacity-80"
            placeholder="linked notes (comma-separated, for the graph view)"
            value={(entry.links ?? []).join(", ")}
            onChange={(e) => onUpdate(i, { links: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
          />
        </div>
      )}

      {entry.type === "ingredient_preset" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="ingredient name"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <label className="flex items-center gap-1 text-xs">
              per
              <input
                type="number"
                className="border rounded px-1 py-1 w-16"
                value={entry.basis_amount_g}
                onChange={(e) => onUpdate(i, { basis_amount_g: Number(e.target.value) })}
              />
              g
            </label>
          </div>
          <div className="flex gap-2 text-xs">
            <label className="flex items-center gap-1">
              protein
              <input
                type="number"
                className="border rounded px-1 py-0.5 w-16"
                value={entry.protein_g}
                onChange={(e) => onUpdate(i, { protein_g: Number(e.target.value) })}
              />
            </label>
            <label className="flex items-center gap-1">
              carbs
              <input
                type="number"
                className="border rounded px-1 py-0.5 w-16"
                value={entry.carbs_g}
                onChange={(e) => onUpdate(i, { carbs_g: Number(e.target.value) })}
              />
            </label>
            <label className="flex items-center gap-1">
              fat
              <input
                type="number"
                className="border rounded px-1 py-0.5 w-16"
                value={entry.fat_g}
                onChange={(e) => onUpdate(i, { fat_g: Number(e.target.value) })}
              />
            </label>
            <label className="flex items-center gap-1">
              fiber
              <input
                type="number"
                className="border rounded px-1 py-0.5 w-16"
                value={entry.fiber_g}
                onChange={(e) => onUpdate(i, { fiber_g: Number(e.target.value) })}
              />
            </label>
            <label className="flex items-center gap-1">
              kcal
              <input
                type="number"
                className="border rounded px-1 py-0.5 w-16"
                value={entry.kcal}
                onChange={(e) => onUpdate(i, { kcal: Number(e.target.value) })}
              />
            </label>
          </div>
          {entry.micros.length > 0 && (
            <p className="text-xs opacity-50">{entry.micros.length} micronutrients estimated (not shown here)</p>
          )}
        </div>
      )}

      {entry.type === "meal_composition" && (
        <div className="flex-1">
          <MealCompositionEditor value={entry} onChange={(next) => onUpdate(i, next)} />
        </div>
      )}

      {entry.type === "workout_routine" && (
        <div className="flex-1 space-y-1">
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="routine name"
            value={entry.name}
            onChange={(e) => onUpdate(i, { name: e.target.value })}
          />
          {entry.exercises.map((ex, ei) => (
            <div key={ei} className="flex gap-1 items-center text-xs">
              <input
                className="border rounded px-1 py-0.5 flex-1"
                value={ex}
                onChange={(e) =>
                  onUpdate(i, { exercises: entry.exercises.map((x, xi) => (xi === ei ? e.target.value : x)) })
                }
              />
              <button
                onClick={() => onUpdate(i, { exercises: entry.exercises.filter((_, xi) => xi !== ei) })}
                className="opacity-50 hover:opacity-100 px-1"
              >
                ✕
              </button>
            </div>
          ))}
          <button
            onClick={() => onUpdate(i, { exercises: [...entry.exercises, ""] })}
            className="text-xs underline opacity-70 hover:opacity-100"
          >
            + add exercise
          </button>
        </div>
      )}

      {entry.type === "wardrobe_item" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="item name"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <select
              className="border rounded px-2 py-1 text-sm"
              value={entry.category}
              onChange={(e) => onUpdate(i, { category: e.target.value })}
            >
              {WARDROBE_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="description"
            value={entry.description}
            onChange={(e) => onUpdate(i, { description: e.target.value })}
          />
        </div>
      )}

      {entry.type === "outfit_composition" && (
        <div className="flex-1">
          <OutfitEditor value={entry} onChange={(next) => onUpdate(i, next)} />
        </div>
      )}

      {entry.type === "outfit_photo" && (
        <div className="flex-1 space-y-1">
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="outfit name"
            value={entry.suggested_name}
            onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
          />
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="description / vibe / occasion"
            value={entry.description}
            onChange={(e) => onUpdate(i, { description: e.target.value })}
          />
          <p className="text-xs opacity-50">Saved as is — the photo itself is the record, no item matching.</p>
        </div>
      )}

      {entry.type === "grooming_item" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="product name"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <select
              className="border rounded px-2 py-1 text-sm"
              value={entry.category}
              onChange={(e) => onUpdate(i, { category: e.target.value })}
            >
              {GROOMING_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="description"
            value={entry.description}
            onChange={(e) => onUpdate(i, { description: e.target.value })}
          />
        </div>
      )}

      {entry.type === "grooming_routine_composition" && (
        <div className="flex-1">
          <GroomingRoutineEditor value={entry} onChange={(next) => onUpdate(i, next)} />
        </div>
      )}

      {entry.type === "document_entry" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="document name"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <select
              className="border rounded px-2 py-1 text-sm"
              value={entry.doc_type}
              onChange={(e) => onUpdate(i, { doc_type: e.target.value })}
            >
              {DOC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2 text-xs">
            <label className="flex-1">
              issued
              <input
                type="date"
                className="block w-full border rounded px-2 py-1 mt-0.5"
                value={entry.issued_date ?? ""}
                onChange={(e) => onUpdate(i, { issued_date: e.target.value || null })}
              />
            </label>
            <label className="flex-1">
              expires
              <input
                type="date"
                className="block w-full border rounded px-2 py-1 mt-0.5"
                value={entry.expiry_date ?? ""}
                onChange={(e) => onUpdate(i, { expiry_date: e.target.value || null })}
              />
            </label>
          </div>
          {entry.expiry_date && (
            <p className="text-xs opacity-60">A "Renew: {entry.suggested_name || "..."}" todo will be created automatically.</p>
          )}
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </div>
      )}

      {entry.type === "home_item" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="item name"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <select
              className="border rounded px-2 py-1 text-sm"
              value={entry.category}
              onChange={(e) => onUpdate(i, { category: e.target.value })}
            >
              {HOME_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="location (e.g. closet, box 3)"
              value={entry.location}
              onChange={(e) => onUpdate(i, { location: e.target.value })}
            />
            <input
              className="border rounded px-2 py-1 text-sm w-32"
              placeholder="residence"
              value={entry.residence_name ?? ""}
              onChange={(e) => onUpdate(i, { residence_name: e.target.value || null })}
            />
          </div>
          <div className="flex gap-2 text-xs">
            <label className="flex-1">
              price
              <input
                type="number"
                className="block w-full border rounded px-2 py-1 mt-0.5"
                value={entry.purchase_price ?? ""}
                onChange={(e) => onUpdate(i, { purchase_price: e.target.value ? Number(e.target.value) : null })}
              />
            </label>
            <label className="flex-1">
              purchased
              <input
                type="date"
                className="block w-full border rounded px-2 py-1 mt-0.5"
                value={entry.purchase_date ?? ""}
                onChange={(e) => onUpdate(i, { purchase_date: e.target.value || null })}
              />
            </label>
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </div>
      )}

      {entry.type === "residence_entry" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="residence name (e.g. Iris 307)"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="city"
              value={entry.city}
              onChange={(e) => onUpdate(i, { city: e.target.value })}
            />
          </div>
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="address"
            value={entry.address}
            onChange={(e) => onUpdate(i, { address: e.target.value })}
          />
          <div className="flex gap-2 text-xs">
            <label className="flex-1">
              moved in
              <input
                type="date"
                className="block w-full border rounded px-2 py-1 mt-0.5"
                value={entry.moved_in ?? ""}
                onChange={(e) => onUpdate(i, { moved_in: e.target.value || null })}
              />
            </label>
            <label className="flex-1">
              moved out
              <input
                type="date"
                className="block w-full border rounded px-2 py-1 mt-0.5"
                value={entry.moved_out ?? ""}
                onChange={(e) => onUpdate(i, { moved_out: e.target.value || null })}
              />
            </label>
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </div>
      )}

      {entry.type === "experience_entry" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="name (e.g. Nobu)"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <input
              className="border rounded px-2 py-1 text-sm w-28"
              placeholder="kind"
              value={entry.kind}
              onChange={(e) => onUpdate(i, { kind: e.target.value })}
            />
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="city"
              value={entry.city}
              onChange={(e) => onUpdate(i, { city: e.target.value })}
            />
          </div>
          <div className="flex gap-2 items-center">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="rating / vibe"
              value={entry.rating}
              onChange={(e) => onUpdate(i, { rating: e.target.value })}
            />
            <label className="flex items-center gap-1 text-xs shrink-0">
              <input
                type="checkbox"
                checked={entry.would_return === true}
                onChange={(e) => onUpdate(i, { would_return: e.target.checked })}
              />
              would return
            </label>
            <input
              type="date"
              className="border rounded px-2 py-1 text-xs"
              value={entry.visited_date ?? ""}
              onChange={(e) => onUpdate(i, { visited_date: e.target.value || null })}
            />
          </div>
          {entry.links.length > 0 && (
            <p className="text-xs opacity-50">🔗 linked: {entry.links.join(", ")}</p>
          )}
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </div>
      )}

      {entry.type === "person_entry" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="name"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <select
              className="border rounded px-2 py-1 text-sm"
              value={entry.category}
              onChange={(e) => onUpdate(i, { category: e.target.value })}
            >
              {PEOPLE_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <input
              type="date"
              className="border rounded px-2 py-1 text-xs"
              value={entry.met_date ?? ""}
              onChange={(e) => onUpdate(i, { met_date: e.target.value || null })}
            />
          </div>
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="how you met"
            value={entry.how_met}
            onChange={(e) => onUpdate(i, { how_met: e.target.value })}
          />
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </div>
      )}

      {entry.type === "credit_card_entry" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="card name"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <input
              className="border rounded px-2 py-1 text-sm w-32"
              placeholder="issuer"
              value={entry.issuer}
              onChange={(e) => onUpdate(i, { issuer: e.target.value })}
            />
            <input
              type="number"
              step="0.01"
              className="border rounded px-2 py-1 text-sm w-24"
              placeholder="annual fee"
              value={entry.annual_fee ?? ""}
              onChange={(e) => onUpdate(i, { annual_fee: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
          <input
            className="border rounded px-2 py-1 text-sm w-full"
            placeholder="rewards summary (e.g. 3x dining, 2x travel)"
            value={entry.rewards_summary}
            onChange={(e) => onUpdate(i, { rewards_summary: e.target.value })}
          />
          <div className="flex gap-2">
            <input
              type="number"
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="points balance"
              value={entry.points_balance ?? ""}
              onChange={(e) => onUpdate(i, { points_balance: e.target.value ? Number(e.target.value) : null })}
            />
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="signup bonus"
              value={entry.signup_bonus}
              onChange={(e) => onUpdate(i, { signup_bonus: e.target.value })}
            />
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </div>
      )}

      {entry.type === "investment_entry" && (
        <div className="flex-1 space-y-1">
          <div className="flex gap-2">
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="name (e.g. Apple)"
              value={entry.suggested_name}
              onChange={(e) => onUpdate(i, { suggested_name: e.target.value })}
            />
            <input
              className="border rounded px-2 py-1 text-sm w-20"
              placeholder="ticker"
              value={entry.symbol}
              onChange={(e) => onUpdate(i, { symbol: e.target.value })}
            />
            <input
              type="date"
              className="border rounded px-2 py-1 text-xs"
              value={entry.purchase_date ?? ""}
              onChange={(e) => onUpdate(i, { purchase_date: e.target.value || null })}
            />
          </div>
          <div className="flex gap-2">
            <input
              type="number"
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="shares"
              value={entry.shares ?? ""}
              onChange={(e) => onUpdate(i, { shares: e.target.value ? Number(e.target.value) : null })}
            />
            <input
              type="number"
              step="0.01"
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="cost basis / share"
              value={entry.cost_basis ?? ""}
              onChange={(e) => onUpdate(i, { cost_basis: e.target.value ? Number(e.target.value) : null })}
            />
            <input
              className="border rounded px-2 py-1 text-sm flex-1"
              placeholder="account"
              value={entry.account}
              onChange={(e) => onUpdate(i, { account: e.target.value })}
            />
          </div>
          <textarea
            className="w-full border rounded p-2 text-sm"
            rows={2}
            placeholder="notes"
            value={entry.notes}
            onChange={(e) => onUpdate(i, { notes: e.target.value })}
          />
        </div>
      )}

      <button onClick={() => onRemove(i)} className="text-sm opacity-60 hover:opacity-100 px-2">
        ✕
      </button>
    </div>
  );
}
