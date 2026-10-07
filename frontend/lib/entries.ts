import {
  BLANK_SET,
  createCreditCard,
  createDocument,
  createExperience,
  createGroomingItem,
  createGroomingRoutine,
  createHomeItem,
  createIngredient,
  createInvestment,
  createMealFromIngredients,
  createOutfit,
  createPerson,
  createResidence,
  createRoutine,
  createTodo,
  createWardrobeItem,
  KBSuggestion,
  logActivity,
  logBodyStat,
  logExercise,
  logExpense,
  logFood,
  logSubstance,
  ParsedEntry,
  pushKBEntry,
  pushKBEntryWithAsset,
} from "./api";
import { todayIso } from "./date";

export const BLANK: Record<ParsedEntry["type"], ParsedEntry> = {
  activity: { type: "activity", category: "productivity", description: "", hours: 0, entry_date: null },
  food: { type: "food", meal_type: "lunch", description: "", meal_id: null, estimated_kcal: 0, entry_date: null },
  exercise: { type: "exercise", exercise_name: "", sets: [{ ...BLANK_SET }], notes: "", entry_date: null },
  substance: { type: "substance", substance: "", amount: 0, notes: "", entry_date: null },
  todo: { type: "todo", title: "", due_date: todayIso(), start_time: null, end_time: null, priority: 2 },
  body_stat: { type: "body_stat", metric: "weight", value: 0, unit: "lb", entry_date: null },
  finance: { type: "finance", amount: 0, merchant: "", category: "", notes: "", entry_date: null, kind: "regular" },
  kb_entry: { type: "kb_entry", folder: "", title: "", content: "" },
  ingredient_preset: {
    type: "ingredient_preset",
    suggested_name: "",
    basis_amount_g: 100,
    protein_g: 0,
    carbs_g: 0,
    fat_g: 0,
    fiber_g: 0,
    kcal: 0,
    micros: [],
  },
  meal_composition: { type: "meal_composition", meal_name: "", components: [], totals: { protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, kcal: 0 } },
  workout_routine: { type: "workout_routine", name: "", exercises: [] },
  wardrobe_item: { type: "wardrobe_item", suggested_name: "", category: "accessory", description: "" },
  outfit_composition: { type: "outfit_composition", outfit_name: "", items: [] },
  outfit_photo: { type: "outfit_photo", suggested_name: "", description: "" },
  grooming_item: { type: "grooming_item", suggested_name: "", category: "skincare", description: "" },
  grooming_routine_composition: { type: "grooming_routine_composition", routine_name: "", steps: [] },
  document_entry: {
    type: "document_entry",
    suggested_name: "",
    doc_type: "id",
    issued_date: null,
    expiry_date: null,
    notes: "",
  },
  home_item: {
    type: "home_item",
    suggested_name: "",
    category: "furniture",
    location: "",
    purchase_price: null,
    purchase_date: null,
    residence_name: null,
    notes: "",
  },
  residence_entry: {
    type: "residence_entry",
    suggested_name: "",
    city: "",
    address: "",
    moved_in: null,
    moved_out: null,
    notes: "",
  },
  experience_entry: {
    type: "experience_entry",
    suggested_name: "",
    kind: "restaurant",
    city: "",
    rating: "",
    would_return: null,
    visited_date: null,
    notes: "",
    links: [],
  },
  person_entry: {
    type: "person_entry",
    suggested_name: "",
    category: "friend",
    how_met: "",
    met_date: null,
    notes: "",
  },
  credit_card_entry: {
    type: "credit_card_entry",
    suggested_name: "",
    issuer: "",
    annual_fee: null,
    rewards_summary: "",
    points_balance: null,
    signup_bonus: "",
    notes: "",
  },
  investment_entry: {
    type: "investment_entry",
    suggested_name: "",
    symbol: "",
    shares: null,
    cost_basis: null,
    account: "",
    purchase_date: null,
    notes: "",
  },
};

// Shared by the Journal page's nightly dump and the general Drop page — both
// ultimately produce the same ParsedEntry union (parse_journal_dump now
// covers finance/kb_entry too), so both commit through the exact same logic.
// `assets` are the file(s) behind a proposal, if the drop that produced it
// came with any attached — otherwise a plain text entry.
//
// `date` is the page's date picker — only a FALLBACK now. Each dated entry
// type carries its own entry_date, resolved by AI from the text itself
// ("last Tuesday I..."); when present it wins, so a multi-day dump splits
// across the right dates instead of everything landing on whatever date
// happens to be selected in the UI.
//
// Every asset-carrying type takes every photo dropped with it — no fixed
// cap anywhere (a multi-page document, several angles of an item, whatever
// you actually attached). outfit_photo is the one exception: a full-look
// shot is inherently a single photo, not a multi-page thing, so it still
// only takes the first.
export async function commitEntry(date: string, entry: ParsedEntry, assets: File[] = []) {
  const asset = assets[0] ?? null;
  switch (entry.type) {
    case "activity":
      return logActivity({
        date: entry.entry_date ?? date,
        category: entry.category,
        description: entry.description,
        hours: entry.hours,
      });
    case "food":
      return entry.meal_id
        ? logFood({ date: entry.entry_date ?? date, meal_type: entry.meal_type, meal_id: entry.meal_id, notes: entry.description })
        : logFood({
            date: entry.entry_date ?? date,
            meal_type: entry.meal_type,
            freeform_kcal: entry.estimated_kcal,
            notes: entry.description,
          });
    case "exercise":
      return logExercise({
        date: entry.entry_date ?? date,
        exercise_name: entry.exercise_name,
        sets: entry.sets,
        notes: entry.notes,
      });
    case "substance":
      return logSubstance({ date: entry.entry_date ?? date, substance: entry.substance, amount: entry.amount, notes: entry.notes });
    case "todo":
      return createTodo({
        title: entry.title,
        due_date: entry.due_date,
        start_time: entry.start_time,
        end_time: entry.end_time,
        priority: entry.priority,
      });
    case "body_stat":
      return logBodyStat({ date: entry.entry_date ?? date, metric: entry.metric, value: entry.value, unit: entry.unit });
    case "finance":
      return logExpense({
        date: entry.entry_date ?? date,
        amount: entry.amount,
        merchant: entry.merchant,
        category: entry.category,
        notes: entry.notes,
        kind: entry.kind,
      });
    case "kb_entry": {
      const suggestion: KBSuggestion = { folder: entry.folder, title: entry.title, content: entry.content, links: entry.links };
      return assets.length > 0 ? pushKBEntryWithAsset(suggestion, assets) : pushKBEntry(suggestion);
    }
    case "ingredient_preset":
      return createIngredient({
        name: entry.suggested_name,
        basis_amount_g: entry.basis_amount_g,
        protein_g: entry.protein_g,
        carbs_g: entry.carbs_g,
        fat_g: entry.fat_g,
        fiber_g: entry.fiber_g,
        kcal: entry.kcal,
        micros: entry.micros,
      });
    case "meal_composition":
      return createMealFromIngredients(entry.meal_name, entry.components);
    case "workout_routine":
      return createRoutine(entry.name, entry.exercises);
    case "wardrobe_item":
      // Unlike ingredient/label photos, a wardrobe item's photo is kept, not
      // discarded — attach every one this drop came with.
      return createWardrobeItem(entry.suggested_name, entry.category, entry.description, assets);
    case "outfit_composition": {
      // New items get created first so the outfit can reference them by the
      // exact name that ends up saved — mirrors add-missing-ingredients-first
      // in createMealFromIngredients on the backend.
      for (const it of entry.items) {
        if (it.is_new) await createWardrobeItem(it.name, it.category, it.description ?? "");
      }
      return createOutfit(
        entry.outfit_name,
        entry.items.map((it) => it.name)
      );
    }
    case "outfit_photo":
      // Saved AS IS — the photo itself is the outfit record, no item list.
      return createOutfit(entry.suggested_name, [], asset);
    case "grooming_item":
      return createGroomingItem(entry.suggested_name, entry.category, entry.description, assets);
    case "grooming_routine_composition": {
      for (const s of entry.steps) {
        if (s.is_new) await createGroomingItem(s.name, s.category, s.description ?? "");
      }
      return createGroomingRoutine(
        entry.routine_name,
        entry.steps.map((s) => s.name)
      );
    }
    case "document_entry":
      // Unlike grooming/wardrobe items (photo captioned then discarded), a
      // document's scan IS the point — attach every page this drop came with.
      return createDocument(
        {
          name: entry.suggested_name,
          doc_type: entry.doc_type,
          issued_date: entry.issued_date,
          expiry_date: entry.expiry_date,
          notes: entry.notes,
        },
        assets
      );
    case "home_item":
      // Same reasoning as wardrobe/grooming — what does this actually look
      // like stays useful, so the photo is kept, not discarded.
      return createHomeItem(
        {
          name: entry.suggested_name,
          residence_name: entry.residence_name ?? "",
          category: entry.category,
          location: entry.location,
          purchase_price: entry.purchase_price,
          purchase_date: entry.purchase_date,
          notes: entry.notes,
        },
        assets
      );
    case "residence_entry":
      return createResidence({
        name: entry.suggested_name,
        city: entry.city,
        address: entry.address,
        moved_in: entry.moved_in,
        moved_out: entry.moved_out,
        notes: entry.notes,
      });
    case "experience_entry":
      return createExperience({
        name: entry.suggested_name,
        city: entry.city,
        kind: entry.kind,
        rating: entry.rating,
        would_return: entry.would_return,
        visited_date: entry.visited_date,
        notes: entry.notes,
        links: entry.links,
      });
    case "person_entry":
      return createPerson({
        name: entry.suggested_name,
        category: entry.category,
        how_met: entry.how_met,
        met_date: entry.met_date,
        notes: entry.notes,
      });
    case "credit_card_entry":
      return createCreditCard({
        name: entry.suggested_name,
        issuer: entry.issuer,
        annual_fee: entry.annual_fee,
        rewards_summary: entry.rewards_summary,
        points_balance: entry.points_balance,
        signup_bonus: entry.signup_bonus,
        notes: entry.notes,
      });
    case "investment_entry":
      return createInvestment({
        name: entry.suggested_name,
        symbol: entry.symbol,
        shares: entry.shares,
        cost_basis: entry.cost_basis,
        account: entry.account,
        purchase_date: entry.purchase_date,
        notes: entry.notes,
      });
  }
}
