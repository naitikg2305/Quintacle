export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: options?.body ? { "content-type": "application/json" } : undefined,
    ...options,
  });
  if (!res.ok) {
    throw new Error(`${options?.method ?? "GET"} ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

// --- schedule (Calendar A) ---

export type Todo = {
  id: string;
  title: string;
  priority: number;
  due_date: string | null;
  start_time: string | null;
  end_time: string | null;
  done: boolean;
  category: string;
  completed_at: string | null;
  created_at: string;
  notes: string;
};

export const listTodos = () => request<Todo[]>("/schedule/todos");
export const createTodo = (body: {
  title: string;
  category?: string;
  priority?: number;
  due_date?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  notes?: string;
}) => request<Todo>("/schedule/todos", { method: "POST", body: JSON.stringify(body) });
export const updateTodo = (
  id: string,
  body: Partial<Pick<Todo, "done" | "title" | "priority" | "due_date" | "start_time" | "end_time">>
) => request<Todo>(`/schedule/todos/${id}`, { method: "PATCH", body: JSON.stringify(body) });

// --- logs (activities / habits / meals) ---

export type Habit = {
  id: number;
  name: string;
  target_amount: number;
  target_period: string;
  match_category: string | null;
  unit: string;
  metric: string;
  direction: "at_least" | "at_most";
};

export type HabitProgress = {
  habit: string;
  unit: string;
  target_period: string;
  metric: string;
  direction: "at_least" | "at_most";
  window: { start: string; end: string };
  current: number;
  target: number;
  met: boolean;
};

export const listHabits = () => request<Habit[]>("/logs/habits");
export const createHabit = (body: Omit<Habit, "id">) =>
  request<Habit>("/logs/habits", { method: "POST", body: JSON.stringify(body) });
export const habitProgress = (id: number) => request<HabitProgress>(`/logs/habits/${id}/progress`);

export type HabitHistoryPoint = { window: { start: string; end: string }; current: number; target: number; met: boolean };

export const habitHistory = (id: number, periods = 8) =>
  request<HabitHistoryPoint[]>(`/logs/habits/${id}/history?periods=${periods}`);

export const logActivity = (body: { date: string; category: string; description: string; hours: number }) =>
  request("/logs/activities", { method: "POST", body: JSON.stringify(body) });

export type ActivityEntry = { id: number; date: string; category: string; description: string; hours: number };

export const activitiesInRange = (start: string, end: string) =>
  request<ActivityEntry[]>(`/logs/activities?start=${start}&end=${end}`);

export type Meal = { id: number; name: string; protein_g: number; carbs_g: number; fat_g: number; kcal: number; notes: string };

export const listMeals = () => request<Meal[]>("/logs/meals");

export type Ingredient = {
  id: number;
  name: string;
  basis_amount_g: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  kcal: number;
  notes: string;
};

export const listIngredients = () => request<Ingredient[]>("/logs/ingredients");

export const createIngredient = (body: {
  name: string;
  basis_amount_g: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  kcal: number;
  notes?: string;
  micros?: MicroEstimate[];
}) => request<Ingredient>("/logs/ingredients", { method: "POST", body: JSON.stringify(body) });

export type MealComponent = {
  name: string;
  ingredient_id: number | null;
  quantity_g: number;
  basis_amount_g: number;
  is_new: boolean;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  kcal: number;
  new_ingredient_micros?: MicroEstimate[];
};

export type MealCompositionResult = {
  meal_name: string;
  components: MealComponent[];
  totals: { protein_g: number; carbs_g: number; fat_g: number; fiber_g: number; kcal: number };
};

export const suggestMealComposition = (description: string) =>
  request<MealCompositionResult>("/logs/meals/suggest-composition", { method: "POST", body: JSON.stringify({ description }) });

export const createMealFromIngredients = (name: string, components: MealComponent[], notes = "") =>
  request<{ id: number }>("/logs/meals/from-ingredients", {
    method: "POST",
    body: JSON.stringify({
      name,
      notes,
      components: components.map((c) =>
        c.ingredient_id != null
          ? { ingredient_id: c.ingredient_id, quantity_g: c.quantity_g }
          : {
              name: c.name,
              quantity_g: c.quantity_g,
              basis_amount_g: c.basis_amount_g,
              protein_g: c.protein_g,
              carbs_g: c.carbs_g,
              fat_g: c.fat_g,
              fiber_g: c.fiber_g,
              kcal: c.kcal,
              micros: c.new_ingredient_micros ?? [],
            }
      ),
    }),
  });

export const logFood = (body: {
  date: string;
  meal_type: string;
  meal_id?: number | null;
  freeform_kcal?: number;
  notes?: string;
  servings?: number;
}) => request("/logs/food", { method: "POST", body: JSON.stringify({ servings: 1, ...body }) });

export type ExerciseSet = {
  reps: number | null;
  weight: number | null;
  weight_unit: string;
  duration_min: number | null;
  distance: number | null;
  distance_unit: string;
  calories_burned: number | null;
};

export const BLANK_SET: ExerciseSet = {
  reps: null,
  weight: null,
  weight_unit: "lb",
  duration_min: null,
  distance: null,
  distance_unit: "mi",
  calories_burned: null,
};

export const logExercise = (body: { date: string; exercise_name: string; sets: ExerciseSet[]; notes?: string }) =>
  request("/logs/exercise", { method: "POST", body: JSON.stringify(body) });

export const listExerciseNames = () => request<string[]>("/logs/exercise-names");

export function formatSets(sets: ExerciseSet[]): string {
  if (sets.length === 0) return "";
  return sets
    .map((s) => {
      if (s.duration_min != null || s.distance != null) {
        const bits = [];
        if (s.duration_min != null) bits.push(`${s.duration_min}min`);
        if (s.distance != null) bits.push(`${s.distance}${s.distance_unit}`);
        if (s.calories_burned != null) bits.push(`${s.calories_burned}kcal`);
        return bits.join(" ");
      }
      if (s.weight != null) return `${s.reps}@${s.weight}${s.weight_unit}`;
      return `${s.reps}`;
    })
    .join(", ");
}

export const logSubstance = (body: { date: string; substance: string; amount: number; notes?: string }) =>
  request("/logs/substances", { method: "POST", body: JSON.stringify(body) });

export const logBodyStat = (body: { date: string; metric: string; value: number; unit?: string }) =>
  request("/logs/body-stats", { method: "POST", body: JSON.stringify(body) });

export type NutritionHistoryPoint = { date: string; kcal: number; protein_g: number; kcal_burned: number };

export const getNutritionHistory = (days = 8) => request<NutritionHistoryPoint[]>(`/logs/nutrition-history?days=${days}`);

// --- profile ---

export type ActivityLevel = "sedentary" | "light" | "moderate" | "active" | "very_active";

export type Profile = {
  height_cm: number | null;
  sex: "male" | "female" | null;
  birthdate: string | null;
  activity_level: ActivityLevel;
  home_countries: string[];
};

export type Targets =
  | { error: string }
  | { age: number; weight_kg: number; bmr: number; tdee_kcal: number; protein_target_g: number };

export const getProfile = () => request<Profile>("/profile");
export const updateProfile = (body: Profile) => request<Profile>("/profile", { method: "PUT", body: JSON.stringify(body) });
export const getTargets = () => request<Targets>("/profile/targets");

// --- journal (Calendar B source) ---

export const saveJournal = (date: string, content: string) =>
  request(`/journal/${date}`, { method: "POST", headers: { "content-type": "text/plain" }, body: content });
export const getJournal = (date: string) => request<{ date: string; content: string | null }>(`/journal/${date}`);

// entry_date: resolved from the text itself (e.g. "last Tuesday I..."), null
// if no date was stated/implied — commitEntry() falls back to the page's
// date picker in that case. Lets a multi-day dump ("recap my whole week")
// correctly split across the right dates instead of everything silently
// landing on whatever date happens to be selected in the UI.
export type ParsedActivity = {
  type: "activity";
  category: string;
  description: string;
  hours: number;
  entry_date: string | null;
};
export type ParsedFood = {
  type: "food";
  meal_type: string;
  description: string;
  meal_id: number | null;
  estimated_kcal: number;
  entry_date: string | null;
};
export type ParsedExercise = {
  type: "exercise";
  exercise_name: string;
  sets: ExerciseSet[];
  notes: string;
  entry_date: string | null;
};
export type ParsedSubstance = {
  type: "substance";
  substance: string;
  amount: number;
  notes: string;
  entry_date: string | null;
};
export type ParsedTodo = {
  type: "todo";
  title: string;
  due_date: string | null;
  start_time: string | null;
  end_time: string | null;
  priority: number;
};
export type ParsedBodyStat = {
  type: "body_stat";
  metric: string;
  value: number;
  unit: string;
  entry_date: string | null;
};
export const FINANCE_KINDS = ["subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"] as const;
export type FinanceKind = (typeof FINANCE_KINDS)[number];

export type ParsedFinance = {
  type: "finance";
  amount: number;
  merchant: string;
  category: string;
  notes: string;
  entry_date: string | null;
  kind: FinanceKind;
};
export type ParsedKBEntry = { type: "kb_entry"; folder: string; title: string; content: string; links?: string[] };
export type MicroEstimate = { nutrient: string; amount: number; unit: string };
export type ParsedIngredientPreset = {
  type: "ingredient_preset";
  suggested_name: string;
  basis_amount_g: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  kcal: number;
  micros: MicroEstimate[];
};
export type ParsedMealComposition = {
  type: "meal_composition";
  meal_name: string;
  components: MealComponent[];
  totals: { protein_g: number; carbs_g: number; fat_g: number; fiber_g: number; kcal: number };
};
export type ParsedWorkoutRoutine = { type: "workout_routine"; name: string; exercises: string[] };

export type WardrobeItem = { name: string; category: string; description: string; assets?: string[] };
export type OutfitItemComponent = { name: string; category: string; description?: string; is_new: boolean };
export type ParsedWardrobeItem = { type: "wardrobe_item"; suggested_name: string; category: string; description: string };
export type ParsedOutfitComposition = { type: "outfit_composition"; outfit_name: string; items: OutfitItemComponent[] };
export type ParsedOutfitPhoto = { type: "outfit_photo"; suggested_name: string; description: string };

export type GroomingItem = { name: string; category: string; description: string; assets?: string[] };
export type GroomingRoutineStep = { name: string; category: string; description?: string; is_new: boolean };
export type ParsedGroomingItem = { type: "grooming_item"; suggested_name: string; category: string; description: string };
export type ParsedGroomingRoutineComposition = { type: "grooming_routine_composition"; routine_name: string; steps: GroomingRoutineStep[] };

export type ParsedDocumentEntry = {
  type: "document_entry";
  suggested_name: string;
  doc_type: string;
  issued_date: string | null;
  expiry_date: string | null;
  notes: string;
};

export type ParsedHomeItem = {
  type: "home_item";
  suggested_name: string;
  category: string;
  location: string;
  purchase_price: number | null;
  purchase_date: string | null;
  residence_name: string | null;
  notes: string;
};

export type ParsedResidenceEntry = {
  type: "residence_entry";
  suggested_name: string;
  city: string;
  address: string;
  moved_in: string | null;
  moved_out: string | null;
  notes: string;
};

export type ParsedExperienceEntry = {
  type: "experience_entry";
  suggested_name: string;
  kind: string;
  city: string;
  rating: string;
  would_return: boolean | null;
  visited_date: string | null;
  notes: string;
  links: string[];
};

export type ParsedPersonEntry = {
  type: "person_entry";
  suggested_name: string;
  category: string;
  how_met: string;
  met_date: string | null;
  notes: string;
};

export type ParsedCreditCardEntry = {
  type: "credit_card_entry";
  suggested_name: string;
  issuer: string;
  annual_fee: number | null;
  rewards_summary: string;
  points_balance: number | null;
  signup_bonus: string;
  notes: string;
};

export type ParsedInvestmentEntry = {
  type: "investment_entry";
  suggested_name: string;
  symbol: string;
  shares: number | null;
  cost_basis: number | null;
  account: string;
  purchase_date: string | null;
  notes: string;
};

export type ParsedEntry =
  | ParsedActivity
  | ParsedFood
  | ParsedExercise
  | ParsedSubstance
  | ParsedTodo
  | ParsedBodyStat
  | ParsedFinance
  | ParsedKBEntry
  | ParsedIngredientPreset
  | ParsedMealComposition
  | ParsedWorkoutRoutine
  | ParsedWardrobeItem
  | ParsedOutfitComposition
  | ParsedGroomingItem
  | ParsedGroomingRoutineComposition
  | ParsedDocumentEntry
  | ParsedHomeItem
  | ParsedResidenceEntry
  | ParsedExperienceEntry
  | ParsedPersonEntry
  | ParsedOutfitPhoto
  | ParsedCreditCardEntry
  | ParsedInvestmentEntry;

export const listWardrobeItems = () => request<WardrobeItem[]>("/wardrobe/items");

export async function createWardrobeItem(
  name: string,
  category: string,
  description = "",
  files: File[] = []
): Promise<WardrobeItem> {
  const form = new FormData();
  form.append("name", name);
  form.append("category", category);
  form.append("description", description);
  for (const f of files) form.append("files", f);
  const res = await fetch(`${API_BASE}/wardrobe/items`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`create wardrobe item failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export function wardrobeAssetUrl(path: string): string {
  return `${API_BASE}/wardrobe/asset?path=${encodeURIComponent(path)}`;
}
export function outfitAssetUrl(path: string): string {
  return `${API_BASE}/wardrobe/outfits/asset?path=${encodeURIComponent(path)}`;
}
export type Outfit = { name: string; items: string[]; asset?: string | null };
export const listOutfits = () => request<Outfit[]>("/wardrobe/outfits");

// items may be empty — a full-outfit photo (mirror selfie) is saved AS IS,
// the photo (file) being the record, not a list of matched wardrobe items.
export async function createOutfit(name: string, items: string[], file?: File | null): Promise<Outfit> {
  const form = new FormData();
  form.append("name", name);
  form.append("items", JSON.stringify(items));
  if (file) form.append("file", file);
  const res = await fetch(`${API_BASE}/wardrobe/outfits`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`create outfit failed: ${res.status} ${await res.text()}`);
  return res.json();
}
export const suggestOutfitComposition = (description: string) =>
  request<{ outfit_name: string; items: OutfitItemComponent[] }>("/wardrobe/outfits/suggest", {
    method: "POST",
    body: JSON.stringify({ description }),
  });

export const listRoutines = () => request<{ name: string; exercises: string[] }[]>("/logs/routines");
export const createRoutine = (name: string, exercises: string[]) =>
  request<{ name: string; exercises: string[] }>("/logs/routines", { method: "POST", body: JSON.stringify({ name, exercises }) });
export const suggestWorkoutRoutine = (description: string) =>
  request<{ name: string; exercises: string[] }>("/logs/routines/suggest", {
    method: "POST",
    body: JSON.stringify({ description }),
  });

export const listGroomingItems = () => request<GroomingItem[]>("/grooming/items");

export async function createGroomingItem(
  name: string,
  category: string,
  description = "",
  files: File[] = []
): Promise<GroomingItem> {
  const form = new FormData();
  form.append("name", name);
  form.append("category", category);
  form.append("description", description);
  for (const f of files) form.append("files", f);
  const res = await fetch(`${API_BASE}/grooming/items`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`create grooming item failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export function groomingAssetUrl(path: string): string {
  return `${API_BASE}/grooming/asset?path=${encodeURIComponent(path)}`;
}
export const listGroomingRoutines = () => request<{ name: string; steps: string[] }[]>("/grooming/routines");
export const createGroomingRoutine = (name: string, steps: string[]) =>
  request<{ name: string; steps: string[] }>("/grooming/routines", { method: "POST", body: JSON.stringify({ name, steps }) });
export const suggestGroomingRoutine = (description: string) =>
  request<{ routine_name: string; steps: GroomingRoutineStep[] }>("/grooming/routines/suggest", {
    method: "POST",
    body: JSON.stringify({ description }),
  });

export type Document = {
  name: string;
  slug: string;
  doc_type: string;
  issued_date: string | null;
  expiry_date: string | null;
  status: string;
  notes: string;
  assets: string[];
};

export const listDocuments = () => request<Document[]>("/documents");

export async function createDocument(
  fields: { name: string; doc_type?: string; issued_date?: string | null; expiry_date?: string | null; status?: string; notes?: string },
  files: File[] = []
): Promise<{ name: string; slug: string; assets: string[]; todo_created: boolean }> {
  const form = new FormData();
  form.append("name", fields.name);
  form.append("doc_type", fields.doc_type ?? "");
  form.append("issued_date", fields.issued_date ?? "");
  form.append("expiry_date", fields.expiry_date ?? "");
  form.append("status", fields.status ?? "active");
  form.append("notes", fields.notes ?? "");
  for (const f of files) form.append("files", f);
  const res = await fetch(`${API_BASE}/documents`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`create document failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export function documentAssetUrl(path: string): string {
  return `${API_BASE}/documents/asset?path=${encodeURIComponent(path)}`;
}

export type Residence = {
  name: string;
  slug: string;
  folder: string;
  city: string;
  address: string;
  moved_in: string | null;
  moved_out: string | null;
  notes: string;
};

export type HomeItem = {
  name: string;
  slug: string;
  category: string;
  location: string;
  purchase_price: number | null;
  purchase_date: string | null;
  notes: string;
  assets?: string[];
};

export const listResidences = () => request<Residence[]>("/home/residences");

export const createResidence = (fields: {
  name: string;
  city: string;
  address?: string;
  moved_in?: string | null;
  moved_out?: string | null;
  notes?: string;
}) => request<{ name: string; slug: string; folder: string }>("/home/residences", { method: "POST", body: JSON.stringify(fields) });

export const listHomeItems = (residenceName: string) =>
  request<HomeItem[]>(`/home/items?residence_name=${encodeURIComponent(residenceName)}`);

export async function createHomeItem(
  fields: {
    name: string;
    residence_name?: string;
    category?: string;
    location?: string;
    purchase_price?: number | null;
    purchase_date?: string | null;
    notes?: string;
  },
  files: File[] = []
): Promise<{ name: string; slug: string; residence: string; assets: string[] }> {
  const form = new FormData();
  form.append("name", fields.name);
  form.append("residence_name", fields.residence_name ?? "");
  form.append("category", fields.category ?? "");
  form.append("location", fields.location ?? "");
  if (fields.purchase_price != null) form.append("purchase_price", String(fields.purchase_price));
  form.append("purchase_date", fields.purchase_date ?? "");
  form.append("notes", fields.notes ?? "");
  for (const f of files) form.append("files", f);
  const res = await fetch(`${API_BASE}/home/items`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`create home item failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export function homeAssetUrl(residenceFolder: string, path: string): string {
  return `${API_BASE}/home/asset?residence_folder=${encodeURIComponent(residenceFolder)}&path=${encodeURIComponent(path)}`;
}

export type Experience = {
  name: string;
  slug: string;
  folder: string;
  city: string;
  kind: string;
  rating: string;
  would_return: boolean | null;
  visited_date: string | null;
  notes: string;
  links: string[];
};

export const listExperiences = (city?: string) =>
  request<Experience[]>(`/travel/experiences${city ? `?city=${encodeURIComponent(city)}` : ""}`);

export const createExperience = (fields: {
  name: string;
  city: string;
  kind: string;
  rating?: string;
  would_return?: boolean | null;
  visited_date?: string | null;
  notes?: string;
  links?: string[];
}) => request<{ name: string; slug: string; folder: string }>("/travel/experiences", { method: "POST", body: JSON.stringify(fields) });

export type Person = {
  name: string;
  slug: string;
  folder: string;
  category: string;
  how_met: string;
  met_date: string | null;
  notes: string;
};

export const listPeople = () => request<Person[]>("/people");

export const createPerson = (fields: { name: string; category?: string; how_met?: string; met_date?: string | null; notes?: string }) =>
  request<{ name: string; slug: string; folder: string }>("/people", { method: "POST", body: JSON.stringify(fields) });

export type CreditCard = {
  name: string;
  slug: string;
  issuer: string;
  annual_fee: number | null;
  rewards_summary: string;
  points_balance: number | null;
  signup_bonus: string;
  notes: string;
};

export const listCreditCards = () => request<CreditCard[]>("/credit-cards");

export const createCreditCard = (fields: {
  name: string;
  issuer?: string;
  annual_fee?: number | null;
  rewards_summary?: string;
  points_balance?: number | null;
  signup_bonus?: string;
  notes?: string;
}) => request<{ name: string; slug: string }>("/credit-cards", { method: "POST", body: JSON.stringify(fields) });

export type Investment = {
  name: string;
  slug: string;
  symbol: string;
  shares: number | null;
  cost_basis: number | null;
  account: string;
  purchase_date: string | null;
  notes: string;
};

export const listInvestments = () => request<Investment[]>("/investments");

export const createInvestment = (fields: {
  name: string;
  symbol?: string;
  shares?: number | null;
  cost_basis?: number | null;
  account?: string;
  purchase_date?: string | null;
  notes?: string;
}) => request<{ name: string; slug: string }>("/investments", { method: "POST", body: JSON.stringify(fields) });

export const parseJournal = (date: string, content: string) =>
  request<ParsedEntry[]>(`/journal/${date}/parse`, {
    method: "POST",
    headers: { "content-type": "text/plain" },
    body: content,
  });

export const logExpense = (body: {
  date: string;
  amount: number;
  merchant?: string;
  category?: string;
  notes?: string;
  kind?: FinanceKind;
}) => request("/logs/expenses", { method: "POST", body: JSON.stringify(body) });

export type Expense = {
  id: number;
  date: string;
  amount: number;
  merchant: string;
  category: string;
  notes: string;
  kind: FinanceKind;
};

export const listExpenses = (start: string, end: string) =>
  request<Expense[]>(`/logs/expenses?start=${start}&end=${end}`);

export const createMeal = (body: {
  name: string;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  kcal: number;
  notes?: string;
  micros?: MicroEstimate[];
}) => request<Meal>("/logs/meals", { method: "POST", body: JSON.stringify(body) });

// The one general drop: text (optionally "keyword: ..." prefixed) plus an
// optional file. Deterministic routing first, AI only where determinism
// can't decide — see nodes/drop_router.py. Never writes; review then commit
// each returned entry through its own existing endpoint.
export async function proposeDrop(
  text: string,
  file: File | null,
  keepAsIs = false,
  file2: File | null = null,
  referenceDate = ""
): Promise<{ entries: ParsedEntry[] }> {
  const form = new FormData();
  form.append("text", text);
  if (file) form.append("file", file);
  if (file2) form.append("file2", file2);
  form.append("keep_as_is", String(keepAsIs));
  if (referenceDate) form.append("reference_date", referenceDate);
  const res = await fetch(`${API_BASE}/drop`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`drop failed: ${res.status} ${await res.text()}`);
  return res.json();
}

// --- day detail (Calendar B) ---

export type DayDetail = {
  date: string;
  journal: string | null;
  todos_due: Todo[];
  todos_completed: Todo[];
  activities: { id: number; date: string; category: string; description: string; hours: number }[];
  exercise: { id: number; date: string; exercise_name: string; performance_text: string; sets: ExerciseSet[]; notes: string }[];
  food: { entries: unknown[]; totals: Record<string, number> };
  body_stats: unknown[];
  substances: unknown[];
};

export const getDayDetail = (date: string) => request<DayDetail>(`/day/${date}`);

export const getDayCounts = (start: string, end: string) =>
  request<Record<string, number>>(`/day/counts?start=${start}&end=${end}`);

export type MicroTotal = {
  nutrient: string;
  amount: number;
  unit: string;
  rda: number;
  pct_of_rda: number;
  is_limit: boolean;
};

export type NutritionForDate = {
  date: string;
  macros: {
    total_kcal: number;
    total_protein_g: number;
    total_carbs_g: number;
    total_fat_g: number;
    total_fiber_g: number;
  };
  micros: MicroTotal[];
  energy_balance: { kcal_in: number; kcal_burned: number; net_kcal: number };
};

export const getNutritionForDate = (date: string) => request<NutritionForDate>(`/logs/nutrition/${date}`);

// --- knowledge base ---

export const listKBFolders = () => request<string[]>("/kb/folders");
export const listKBEntries = (folder: string) => request<string[]>(`/kb/entries?folder=${encodeURIComponent(folder)}`);
export const listKBFiles = (folder: string) => request<string[]>(`/kb/files?folder=${encodeURIComponent(folder)}`);
// `meta` is every frontmatter key that isn't plumbing (structured entries —
// wardrobe, documents, home items... — keep their fields there); `assets` is
// the frontmatter photo list. `fields` is the freeform key/value the Browse
// editor writes.
export type KBEntryFull = {
  folder: string;
  slug: string;
  title: string;
  content: string;
  fields: Record<string, string>;
  meta: Record<string, unknown>;
  assets: string[];
};

export const readKBEntry = (folder: string, slug: string) =>
  request<KBEntryFull>(`/kb/entry?folder=${encodeURIComponent(folder)}&slug=${encodeURIComponent(slug)}`);

export type KBEntryRow = { slug: string; title: string; meta: Record<string, unknown>; assets: string[]; snippet: string };
export type KBLayout = "list" | "gallery" | "cards" | "table";
export type KBView = {
  layout: KBLayout;
  columns: string[];
  badges: string[];
  sort_by: string | null;
  sort_dir: "asc" | "desc";
  source?: "saved" | "inferred";
};

export const listKBEntriesMeta = (folder: string) =>
  request<KBEntryRow[]>(`/kb/entries-meta?folder=${encodeURIComponent(folder)}`);
export const getKBView = (folder: string) => request<KBView>(`/kb/view?folder=${encodeURIComponent(folder)}`);
export const saveKBView = (folder: string, view: KBView) =>
  request<KBView>(`/kb/view?folder=${encodeURIComponent(folder)}`, {
    method: "PUT",
    body: JSON.stringify({
      layout: view.layout,
      columns: view.columns,
      badges: view.badges,
      sort_by: view.sort_by,
      sort_dir: view.sort_dir,
    }),
  });
export const searchKBEntries = (q: string) =>
  request<{ folder: string; slug: string; snippet: string }[]>(`/kb/search?q=${encodeURIComponent(q)}`);

export type KBSuggestion = { folder: string; title: string; content: string; links?: string[]; fields?: Record<string, string> };

// target.slug given -> merge-update that one existing entry. target.folder
// alone (no slug) -> folder-scoped new entry, folder fixed, never AI-guessed.
export const sortKBEntry = (content: string, target?: { folder: string; slug?: string }) => {
  const params = new URLSearchParams();
  if (target?.folder) params.set("target_folder", target.folder);
  if (target?.slug) params.set("target_slug", target.slug);
  const qs = params.toString();
  return request<KBSuggestion>(`/kb/sort${qs ? `?${qs}` : ""}`, {
    method: "POST",
    headers: { "content-type": "text/plain" },
    body: content,
  });
};

export const pushKBEntry = (body: KBSuggestion) =>
  request<{ folder: string; slug: string }>("/kb/entries", { method: "POST", body: JSON.stringify(body) });

// FormData needs the browser to set its own multipart boundary in
// content-type — request()'s default JSON header would break the upload,
// so these bypass it with a raw fetch.
export async function dropIntoKB(file: File, description: string): Promise<KBSuggestion> {
  const form = new FormData();
  form.append("file", file);
  form.append("description", description);
  const res = await fetch(`${API_BASE}/kb/drop`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`drop failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function pushKBEntryWithAsset(
  suggestion: KBSuggestion,
  files: File[]
): Promise<{ folder: string; slug: string; assets: string[]; location: unknown }> {
  const form = new FormData();
  form.append("folder", suggestion.folder);
  form.append("title", suggestion.title);
  form.append("content", suggestion.content);
  for (const f of files) form.append("files", f);
  form.append("links", (suggestion.links ?? []).join(","));
  const res = await fetch(`${API_BASE}/kb/entries/with-asset`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`push failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export function kbAssetUrl(folder: string, path: string): string {
  return `${API_BASE}/kb/asset?folder=${encodeURIComponent(folder)}&path=${encodeURIComponent(path)}`;
}

export async function addKBEntryAsset(folder: string, slug: string, file: File): Promise<{ asset: string }> {
  const form = new FormData();
  form.append("folder", folder);
  form.append("slug", slug);
  form.append("file", file);
  const res = await fetch(`${API_BASE}/kb/entry/asset`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`attach failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function replaceKBAsset(folder: string, path: string, file: File): Promise<void> {
  const form = new FormData();
  form.append("folder", folder);
  form.append("path", path);
  form.append("file", file);
  const res = await fetch(`${API_BASE}/kb/asset/replace`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`replace failed: ${res.status} ${await res.text()}`);
}

export type SpreadsheetSheet = { name: string; rows: string[][] };

export const getKBSpreadsheet = (folder: string, path: string) =>
  request<{ sheets: SpreadsheetSheet[] }>(`/kb/asset/spreadsheet?folder=${encodeURIComponent(folder)}&path=${encodeURIComponent(path)}`);

export const saveKBSpreadsheet = (folder: string, path: string, sheets: SpreadsheetSheet[]) =>
  request(`/kb/asset/spreadsheet?folder=${encodeURIComponent(folder)}&path=${encodeURIComponent(path)}`, {
    method: "PUT",
    body: JSON.stringify({ sheets }),
  });

export type Photo = { folder: string; slug: string; title: string; assets: string[] };
export const listPhotos = () => request<Photo[]>("/kb/photos");

export type BatchFile = { filename: string; title: string; content: string; links?: string[] };
export type Bucket = { folder: string; files: BatchFile[] };

// One AI call sees every dropped file at once and buckets them by shared
// folder — review/edit, reassign a file to a different bucket, or pull it
// out to place individually, then each file commits through the existing
// single-file pushKBEntryWithAsset (no new commit path needed).
export async function proposeBatchDrop(
  files: File[],
  manualDate = "",
  manualTripName = ""
): Promise<{ buckets: Bucket[] }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (manualDate) form.append("manual_date", manualDate);
  if (manualTripName) form.append("manual_trip_name", manualTripName);
  const res = await fetch(`${API_BASE}/kb/batch-drop`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`batch drop failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export type GraphNode = {
  id: string;
  type: "note" | "asset" | "journal_day" | "ingredient" | "meal" | "routine" | "exercise" | "wardrobe_item" | "outfit";
  label: string;
  folder?: string;
  slug?: string;
  path?: string;
  location?: { lat: number; lon: number };
};
export type GraphEdge = { source: string; target: string; kind: string };

export const getGraph = () => request<{ nodes: GraphNode[]; edges: GraphEdge[] }>("/graph");

export type ChatContentBlock =
  | { type: "text"; text: string }
  | { type: "image"; source: { type: "base64"; media_type: string; data: string } }
  | { type: "document"; source: { type: "base64"; media_type: "application/pdf"; data: string } };

export type ChatMessage = { role: "user" | "assistant"; content: string | ChatContentBlock[] };

const CHAT_IMAGE_MIME: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", webp: "image/webp" };

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

// A photo or PDF attached to a single chat turn — read live, sent alongside
// the typed text as Anthropic content blocks. Only images/PDF are supported
// here (Claude reads both natively); anything else throws rather than
// silently sending nothing.
export async function buildChatMessage(text: string, file?: File | null): Promise<ChatMessage> {
  if (!file) return { role: "user", content: text };
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  const data = await readFileAsBase64(file);
  const blocks: ChatContentBlock[] = [];
  if (text.trim()) blocks.push({ type: "text", text });
  if (ext in CHAT_IMAGE_MIME) {
    blocks.push({ type: "image", source: { type: "base64", media_type: CHAT_IMAGE_MIME[ext], data } });
  } else if (ext === "pdf") {
    blocks.push({ type: "document", source: { type: "base64", media_type: "application/pdf", data } });
  } else {
    throw new Error(`can't attach .${ext} to chat — only photos and PDFs are supported here`);
  }
  return { role: "user", content: blocks };
}

// A user bubble's plain display text — the typed text if there's no
// attachment, or just the text block(s) when there is one (the attachment
// itself renders separately, see ChatLog).
export function chatMessageText(content: ChatMessage["content"]): string {
  if (typeof content === "string") return content;
  return content
    .filter((b): b is Extract<ChatContentBlock, { type: "text" }> => b.type === "text")
    .map((b) => b.text)
    .join("\n");
}

export type ChatModel = { id: string; label: string; provider: "anthropic" | "openai"; price: string };

export const listChatModels = () => request<ChatModel[]>("/kb/models");

// `model` is the picker's choice; the old `research` flag stays for callers
// (folder chat, read-only chat) that never got a picker — the backend uses it
// only when no model is given.
export const chatWithKB = (messages: ChatMessage[], use_kb: boolean, research: boolean, folder?: string, model?: string) =>
  request<{ reply: string }>("/kb/chat", {
    method: "POST",
    body: JSON.stringify({ messages, use_kb, research, folder: folder ?? null, model: model ?? null }),
  });

// Anthropic has no image generation model — this one call goes to a
// separate OpenAI-backed endpoint. Never writes; returns the image for
// preview, pushed into the KB the same way any other drop is (approval
// before write) via the existing pushKBEntryWithAsset.
export const generateImage = (prompt: string) =>
  request<{ data: string; mime_type: string }>("/kb/generate-image", { method: "POST", body: JSON.stringify({ prompt }) });

export function base64ToFile(base64: string, mimeType: string, filename: string): File {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new File([bytes], filename, { type: mimeType });
}

export type ChatSession = { id: string; title: string };

export const listChatSessions = () => request<ChatSession[]>("/kb/chats");
export const createChatSession = (title: string) =>
  request<{ id: string }>("/kb/chats", { method: "POST", body: JSON.stringify({ title }) });
export const loadChatSession = (id: string) => request<ChatMessage[]>(`/kb/chats/${id}`);
export const saveChatSession = (id: string, title: string, messages: ChatMessage[]) =>
  request(`/kb/chats/${id}`, { method: "PUT", body: JSON.stringify({ title, messages }) });
export const deleteChatSession = (id: string) => request(`/kb/chats/${id}`, { method: "DELETE" });

// --- vault (encrypted secrets — entries live outside kb/, never reach any AI surface) ---

export type VaultStatus = { initialized: boolean; locked: boolean; auto_lock_seconds_remaining: number | null };
export type VaultEntrySummary = { slug: string; name: string; username: string; url: string; updated_at: string };
export type VaultEntry = VaultEntrySummary & { secret: string; notes: string };

export const vaultStatus = () => request<VaultStatus>("/vault/status");
export const vaultInit = (passphrase: string) =>
  request<VaultStatus>("/vault/init", { method: "POST", body: JSON.stringify({ passphrase }) });
export const vaultUnlock = (passphrase: string) =>
  request<VaultStatus>("/vault/unlock", { method: "POST", body: JSON.stringify({ passphrase }) });
export const vaultLock = () => request<VaultStatus>("/vault/lock", { method: "POST" });
export const listVaultEntries = () => request<VaultEntrySummary[]>("/vault/entries");
export const getVaultEntry = (slug: string) => request<VaultEntry>(`/vault/entries/${encodeURIComponent(slug)}`);
export const putVaultEntry = (
  slug: string,
  body: { name: string; username?: string; secret?: string; url?: string; notes?: string }
) => request<VaultEntrySummary>(`/vault/entries/${encodeURIComponent(slug)}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteVaultEntry = (slug: string) =>
  request<{ deleted: string }>(`/vault/entries/${encodeURIComponent(slug)}`, { method: "DELETE" });
// --- sync (manual LAN sync — pull from a peer device running the same backend) ---

export type SyncReport = {
  pulled: string[];
  merged_journals: string[];
  overwritten_with_snapshot: string[];
  skipped_identical: number;
  kept_local_newer: number;
  errors: string[];
  warnings: string[];
  rebuilt: { logs: Record<string, number>; graph_edges: number };
  push_back?: SyncReport;
};

export const syncPull = (body: { peer_url: string; push_back?: boolean; self_url?: string }) =>
  request<SyncReport>("/sync/pull", { method: "POST", body: JSON.stringify(body) });
