// 2026-11-05 — the offline USDA FoodData Central db + full nutrient panels.
// Every number here is computed by the backend from stored presets / the
// USDA db (core/quintacle_core/nutrition_db); the UI only displays it.
import { request } from "./api";

export type NutrientSource = "usda" | "label" | "estimated" | "mixed" | "";

export type Contribution = { name: string; amount: number; pct: number; source: NutrientSource };

export type PanelNutrient = {
  nutrient: string;
  unit: string;
  amount: number;
  has_data: boolean;
  approx: boolean;
  source: NutrientSource;
  coverage: { with_data: number; of: number };
  target: { amount: number; unit: string; kind: string } | null;
  pct: number | null;
  is_limit: boolean;
  reference: { low: number; high: number; unit: string; label: string } | null;
  contributions: Contribution[];
};

export type NutrientPanelData = {
  groups: { group: string; nutrients: PanelNutrient[] }[];
  computed: {
    omega6_to_omega3: { value: number; omega6_g: number; omega3_g: number; label: string } | null;
    epa_dha: { amount_mg: number; reference: { low: number; high: number; label: string } | null } | null;
  };
  components: { name: string; source: NutrientSource; quantity_g?: number }[];
};

export type UsdaCandidate = { fdc_id: number; description: string; category: string; source: string; score: number };

export type UsdaDbStatus = {
  installed: boolean;
  path: string;
  summary: { foods: number; size_bytes: number; built_at: string; flavonoids: string; source_urls: string[] } | null;
  approx_download_mb: number;
  job: { state: "idle" | "running" | "done" | "error"; step: string; error: string | null };
};

export type UsdaFoodFields = {
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  kcal: number;
  basis_amount_g: number;
  micros: { nutrient: string; amount: number; unit: string; source?: string; approx?: boolean }[];
  source: "usda";
  fdc_id: number;
  usda_description: string;
};

export type BreakdownComponent = {
  name?: string;
  quantity_g: number;
  ingredient_id?: number | null;
  fdc_id?: number | null;
  protein_g?: number;
  carbs_g?: number;
  fat_g?: number;
  fiber_g?: number;
  kcal?: number;
  micros?: { nutrient: string; amount: number; unit: string }[];
  source?: string;
};

export const getUsdaDbStatus = () => request<UsdaDbStatus>("/nutrition/db/status");
export const installUsdaDb = () => request<{ started: boolean }>("/nutrition/db/install", { method: "POST" });
export const matchUsdaFood = (q: string) =>
  request<{ installed: boolean; candidates: UsdaCandidate[]; pick: UsdaCandidate | null }>(
    `/nutrition/match?q=${encodeURIComponent(q)}&pick=false`
  );
export const getUsdaFood = (fdcId: number, grams = 100) => request<UsdaFoodFields>(`/nutrition/food/${fdcId}?grams=${grams}`);
export const getDayNutrientPanel = (date: string) => request<NutrientPanelData>(`/nutrition/day/${date}`);
export const getMealNutrientPanel = (mealId: number) => request<NutrientPanelData>(`/nutrition/meal/${mealId}`);
export const getNutrientBreakdown = (components: BreakdownComponent[]) =>
  request<NutrientPanelData>("/nutrition/breakdown", { method: "POST", body: JSON.stringify({ components }) });
