"use client";

import { useEffect, useState } from "react";
import { Ingredient, listIngredients, MealComponent, ParsedMealComposition } from "@/lib/api";
import { SourceBadge, UsdaDbNotice } from "@/components/NutrientPanel";
import UsdaMatchPicker, { DraftNutrientPanel } from "@/components/UsdaMatchPicker";
import { BreakdownComponent } from "@/lib/nutritionApi";

type Props = {
  value: ParsedMealComposition;
  onChange: (next: ParsedMealComposition) => void;
};

function computeTotals(components: MealComponent[]): ParsedMealComposition["totals"] {
  const totals = { protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, kcal: 0 };
  for (const c of components) {
    totals.protein_g += c.protein_g;
    totals.carbs_g += c.carbs_g;
    totals.fat_g += c.fat_g;
    totals.fiber_g += c.fiber_g;
    totals.kcal += c.kcal;
  }
  return totals;
}

// Rescaling a component's macros to a new quantity is pure deterministic
// arithmetic — no AI call, whether the component is a known ingredient or a
// brand-new one. basis_amount_g always tracks "what amount these macros are
// for", updated on every edit so scaling stays exact.
function rescale(comp: MealComponent, newQuantity: number): MealComponent {
  const ratio = comp.basis_amount_g ? newQuantity / comp.basis_amount_g : 0;
  return {
    ...comp,
    quantity_g: newQuantity,
    basis_amount_g: newQuantity,
    protein_g: comp.protein_g * ratio,
    carbs_g: comp.carbs_g * ratio,
    fat_g: comp.fat_g * ratio,
    fiber_g: comp.fiber_g * ratio,
    kcal: comp.kcal * ratio,
    // 2026-11-05: micros scale with the macros (they used to stay at the
    // proposal's quantity while basis_amount_g moved).
    new_ingredient_micros: comp.new_ingredient_micros?.map((m) => ({ ...m, amount: m.amount * ratio })),
  };
}

// What the backend needs to compute the full panel for one draft component:
// library ingredient → its stored values; USDA match → the db; else inline.
function toBreakdown(c: MealComponent): BreakdownComponent {
  if (c.ingredient_id != null) return { name: c.name, ingredient_id: c.ingredient_id, quantity_g: c.quantity_g };
  if (c.source === "usda" && c.fdc_id) return { name: c.name || "new ingredient", fdc_id: c.fdc_id, quantity_g: c.quantity_g };
  return {
    name: c.name || "new ingredient",
    quantity_g: c.quantity_g,
    protein_g: c.protein_g,
    carbs_g: c.carbs_g,
    fat_g: c.fat_g,
    fiber_g: c.fiber_g,
    kcal: c.kcal,
    micros: c.new_ingredient_micros ?? [],
    source: c.source || "estimated",
  };
}

// Shared by the Drop page's "recipe:"/"dish:" AI proposal, the KB chat's
// "Suggest meal" flow, and manual "+ Composed meal" — all three produce or
// edit the exact same ParsedMealComposition shape, reviewed here before
// POST /logs/meals/from-ingredients computes the real, authoritative totals.
// 2026-11-05: new components arrive USDA-matched where possible (source
// badge + "change match"), and "Show all nutrients" renders the full panel
// with per-ingredient contributions.
export default function MealCompositionEditor({ value, onChange }: Props) {
  const [library, setLibrary] = useState<Ingredient[]>([]);
  const [picked, setPicked] = useState("");
  const [showPanel, setShowPanel] = useState(false);

  useEffect(() => {
    listIngredients().then(setLibrary);
  }, []);

  function setComponents(components: MealComponent[]) {
    onChange({ ...value, components, totals: computeTotals(components) });
  }

  function updateQuantity(i: number, quantity_g: number) {
    setComponents(value.components.map((c, idx) => (idx === i ? rescale(c, quantity_g) : c)));
  }

  function updateNewMacro(i: number, patch: Partial<MealComponent>) {
    setComponents(value.components.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }

  // Hand-typed macros make a USDA component the owner's own numbers (the
  // backend would otherwise re-read USDA by fdc_id on Save).
  function editNewMacro(i: number, patch: Partial<MealComponent>) {
    const c = value.components[i];
    updateNewMacro(i, c.source === "usda" ? { ...patch, source: "manual", fdc_id: null } : patch);
  }

  function removeComponent(i: number) {
    setComponents(value.components.filter((_, idx) => idx !== i));
  }

  function addFromLibrary() {
    const ingredient = library.find((i) => String(i.id) === picked);
    if (!ingredient) return;
    setComponents([
      ...value.components,
      {
        name: ingredient.name,
        ingredient_id: ingredient.id,
        quantity_g: ingredient.basis_amount_g,
        basis_amount_g: ingredient.basis_amount_g,
        is_new: false,
        protein_g: ingredient.protein_g,
        carbs_g: ingredient.carbs_g,
        fat_g: ingredient.fat_g,
        fiber_g: ingredient.fiber_g,
        kcal: ingredient.kcal,
        source: ingredient.source,
      },
    ]);
    setPicked("");
  }

  function addManualNew() {
    setComponents([
      ...value.components,
      { name: "", ingredient_id: null, quantity_g: 100, basis_amount_g: 100, is_new: true, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, kcal: 0 },
    ]);
  }

  return (
    <div className="space-y-2">
      <input
        className="border rounded px-2 py-1 text-sm w-full"
        placeholder="meal name"
        value={value.meal_name}
        onChange={(e) => onChange({ ...value, meal_name: e.target.value })}
      />
      <UsdaDbNotice />

      {value.components.map((c, i) => (
        <div key={i} className="space-y-1 border-b pb-1 last:border-b-0">
          <div className="flex flex-wrap gap-2 items-center text-xs">
            {c.is_new ? (
              <input
                className="border rounded px-1 py-0.5 w-32"
                placeholder="new ingredient name"
                value={c.name}
                onChange={(e) => updateNewMacro(i, { name: e.target.value })}
              />
            ) : (
              <span className="w-32 truncate">{c.name}</span>
            )}
            <input
              type="number"
              className="border rounded px-1 py-0.5 w-16"
              value={c.quantity_g}
              onChange={(e) => updateQuantity(i, Number(e.target.value) || 0)}
            />
            <span className="opacity-50">g</span>
            {c.is_new ? (
              <>
                <input
                  type="number"
                  title="protein"
                  className="border rounded px-1 py-0.5 w-14"
                  value={c.protein_g}
                  onChange={(e) => editNewMacro(i, { protein_g: Number(e.target.value) })}
                />
                <input
                  type="number"
                  title="carbs"
                  className="border rounded px-1 py-0.5 w-14"
                  value={c.carbs_g}
                  onChange={(e) => editNewMacro(i, { carbs_g: Number(e.target.value) })}
                />
                <input
                  type="number"
                  title="fat"
                  className="border rounded px-1 py-0.5 w-14"
                  value={c.fat_g}
                  onChange={(e) => editNewMacro(i, { fat_g: Number(e.target.value) })}
                />
                <input
                  type="number"
                  title="kcal"
                  className="border rounded px-1 py-0.5 w-16"
                  value={c.kcal}
                  onChange={(e) => editNewMacro(i, { kcal: Number(e.target.value) })}
                />
                <span className="opacity-50 px-1 rounded bg-black/5 dark:bg-white/10">new</span>
              </>
            ) : (
              <>
                <span className="opacity-60 flex-1">
                  {c.protein_g.toFixed(1)}p / {c.carbs_g.toFixed(1)}c / {c.fat_g.toFixed(1)}f · {c.kcal.toFixed(0)}kcal
                </span>
                <SourceBadge source={c.source || "estimated"} />
              </>
            )}
            <button onClick={() => removeComponent(i)} className="opacity-50 hover:opacity-100 px-1 ml-auto">
              ✕
            </button>
          </div>
          {c.is_new && (
            <UsdaMatchPicker
              name={c.name}
              grams={c.quantity_g}
              source={c.source}
              fdcId={c.fdc_id}
              description={c.usda_description}
              candidates={c.usda_candidates}
              onApply={(f, candidates) =>
                updateNewMacro(i, {
                  protein_g: f.protein_g,
                  carbs_g: f.carbs_g,
                  fat_g: f.fat_g,
                  fiber_g: f.fiber_g,
                  kcal: f.kcal,
                  basis_amount_g: c.quantity_g,
                  new_ingredient_micros: f.micros,
                  source: "usda",
                  fdc_id: f.fdc_id,
                  usda_description: f.usda_description,
                  usda_candidates: candidates,
                })
              }
            />
          )}
        </div>
      ))}

      <div className="flex gap-2 items-center text-xs">
        <select className="border rounded px-2 py-1 flex-1 min-w-0" value={picked} onChange={(e) => setPicked(e.target.value)}>
          <option value="">add from ingredient library...</option>
          {library.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
        <button onClick={addFromLibrary} disabled={!picked} className="border rounded px-2 py-1 disabled:opacity-40">
          + add
        </button>
        <button onClick={addManualNew} className="border rounded px-2 py-1">
          + new ingredient
        </button>
      </div>

      <p className="text-xs opacity-70">
        Totals: {value.totals.protein_g.toFixed(1)}p / {value.totals.carbs_g.toFixed(1)}c / {value.totals.fat_g.toFixed(1)}f /{" "}
        {value.totals.fiber_g.toFixed(1)} fiber · {value.totals.kcal.toFixed(0)} kcal
      </p>
      {value.components.length > 0 && (
        <button type="button" className="text-xs underline opacity-80" onClick={() => setShowPanel(!showPanel)}>
          {showPanel ? "Hide" : "Show"} all nutrients (fatty acids, flavonoids, carotenoids…)
        </button>
      )}
      {showPanel && value.components.length > 0 && (
        <DraftNutrientPanel title="All nutrients · this meal" components={value.components.map(toBreakdown)} />
      )}
    </div>
  );
}
