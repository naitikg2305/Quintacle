# Nutrition — how the numbers are sourced and shown

Code-derived reference for food/nutrition. Before 2026-11-05 the nutrition
model was: ingredient presets estimated by a model per basis grams (or read
off a label photo), meals composed from ingredients in
`nodes/logs/meal_composer.py` by deterministic arithmetic, 30 tracked
nutrients against NIH ODS / FDA reference tables by sex and age
(`nodes/logs/nutrition_targets.py`), units canonicalized on write
(`_canonicalize_micros` in `nodes/logs/api.py`). All of that still holds.
The section below adds a real data source.

## 2026-11-06 — label photos read locally (OCR + deterministic parser)

A nutrition-label photo is no longer sent to a cloud model by default
(policy: [perception-and-autojournal.md](perception-and-autojournal.md#2026-11-06--local-first-images-ocr--yolo-first-cloud-only-on-request)).
`nutrition_llm.estimate_nutrition_from_image(photos, desc, provider)`:

1. local OCR → `nodes/logs/label_parser.parse_label` reads, in code, the US
   FDA panel: serving size + grams, servings per container, calories, total
   fat, saturated, trans, cholesterol, sodium, total carbohydrate, fiber,
   total sugars, "Includes Ng Added Sugars", protein, and every listed
   vitamin/mineral, amounts and %DV. A %DV-only row converts through the
   new `nutrition_targets.FDA_LABEL_DV` (the 21 CFR 101.9 label DVs, NOT the
   personal RDAs — calcium 1300 mg, iron 18 mg, potassium 4700 mg …). OCR
   noise handled: O/0, l/1, "rng", µg, glued numbers, a value on the next
   line, comma decimals, "<1g" = 0.5. EU per-100 g panels (kJ/kcal, "of
   which saturates", salt → sodium = salt ÷ 2.5) as a stretch.
   Code sanity: absurd grams dropped, calories that disagree with 4/4/9 lose
   confidence (the printed value is kept), calories derived from macros
   when missing (but then not "core").
2. calories + protein + carbs + fat all READ → done, `pipeline: "ocr+parser"`,
   no model. Otherwise the OCR TEXT goes to the local text model
   (`parse_structured(provider="local")`) and `overlay_parsed` lets every
   code-read value override the model's → `"ocr+local-llm"`.
3. Output = the old `NutritionEstimateFromImage` shape with `from_label=True`
   (→ `source: "label"`), `basis_amount_g` = serving grams (100 for per-100 g),
   plus `field_confidence` {field: 0–1}, `label_dv`, `serving_size_text`,
   `servings_per_container`, `per_100g`. The existing USDA fill
   (`_source_ingredient_image`) still fills nutrients the label doesn't list.
4. No label text → a food photo: local VLM "NAME / GRAMS" (YOLO tags as a
   hint), USDA match on that name; local text-model estimate only when USDA
   has no match. VLM down but YOLO saw "pizza" → name from the tag (`yolo`).

### 2026-11-07 correction — real-label failures (golden check on the owner's files)

- **Chicken-burger label → "Onion", 169 kcal.** The tilted photo's OCR rows
  chained ("ed Calories Amount per serving % Daily Value* 170 Peppers …"),
  so `_calories` missed the printed 170 and core wasn't complete. The local
  LLM then ran: the name came from a cut-off, tilted "Onion" fragment, the
  169 was code's own 4/4/9 derivation beating the model's read, and the
  USDA name match on "Onion" picked "Onions, raw". Fixes:
  - OCR deskew + center-distance row grouping (`perception/ocr.py`, see
    finance.md 2026-11-07) — "Calories 170" is one row again; `_calories`
    also reads "calories <panel words> 170" on one row (never the
    "2,000 calories" footnote).
  - `overlay_parsed(model, parse, name)`: a value code READ always wins; the
    model fills ONLY fields code didn't read; code's derived value only when
    the model gave none. The model never names a label —
    `suggested_name` = owner text / the OCR heuristic / "Labeled food".
  - `api._label_agrees_with_usda`: a NAME match whose per-100 g kcal/macros
    contradict the printed label (kcal off by > max(50, 40%), a macro by
    > max(8 g, 50%)) is dropped → profile match on the parsed numbers.
  - Profile match (`nutrition_db.store.nearest_by_profile`): hint words are
    distinct whole-word (prefix) hits of 4+ letters minus label/package
    vocabulary (a substring test let OCR'd "the"/"per" hit "Fish, pike,
    northern, liver"); when ingredient words imply a group (chicken, milk,
    egg …) a candidate matching none of them ranks ×2 lower; the placeholder
    "Labeled food" is no longer a hint ("food" hit every "Fast Foods" row).
- **Greek-yogurt label named "ada ice. If you'te".** `guess_product_name`
  now runs over the individual deskewed fragments and rejects: OCR
  confidence < 0.8, text clipped by the photo frame, text tilted > 8° off
  the page, lines no taller than the panel's own text, sentence fragments,
  apostrophe garble (only a possessive "'s" passes), non-word strings
  (vowel-less words, impossible starts like "ln"/"sg"), single generic
  words, and package boilerplate (distributor, certifications, claims,
  URLs). Nothing qualifies → "Labeled food", and `_source_ingredient_image`
  names it from the profile match's head
  (`label_parser.name_from_usda_description`: "Yogurt, Greek, plain,
  nonfat" → "Greek yogurt"; group prefixes like "Fast Foods," skipped).
- Golden check (read-only) after: yogurt name → "Greek yogurt" (numbers and
  fdc 330137 unchanged); burger `ocr+local-llm` → `ocr+parser`, kcal 170 /
  P 19 / C 3 / F 9 per 112 g, name "Chicken", profile match "Chicken,
  canned, meat only, with broth" (honest limit: USDA SR Legacy has no
  chicken-burger patty; the ingredient words make it chicken). Tests:
  `core/tests/test_real_world_ocr_fixes.py`.

## 2026-11-05 — USDA FoodData Central as the source of truth (offline)

**Why.** The owner studies nutrition closely ("I look deeply into it, like
calcium too") and wants real numbers, not AI guesses, for macros, every
micronutrient, omega-3/6, flavonoids and carotenoids. Planning a lamb meal
should show all of it.

### The offline db

`core/quintacle_core/nutrition_db/` is stdlib only (csv, sqlite3, zipfile,
urllib), so it runs on the phone the same as the desktop.

- **Install:** `python -m quintacle_core.nutrition_db fetch` (or
  `POST /nutrition/db/install`) downloads the official bulk CSV releases and
  builds `<QUINTACLE_DATA_DIR>/nutrition/usda.db`. Override the path with
  `QUINTACLE_USDA_DB`. Other subcommands: `build <zips|dirs>` (offline
  rebuild) and `match "<text>"` (prints ranked candidates).
- **Sources (verified 2026-11-05):**
  - FoodData Central download page: https://fdc.nal.usda.gov/download-datasets/
  - Foundation Foods CSV: the newest release is read from that page.
    **The 2026-10-29 zip was published without `food.csv` /
    `food_nutrient.csv`**, so each release is checked
    (`build.release_is_complete`) and the next newest is used. Currently
    that is https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_csv_2026-04-30.zip.
  - SR Legacy (final, 2018-04): https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
  - USDA Database for the Flavonoid Content of Selected Foods, Release 3.3:
    https://www.ars.usda.gov/ARSUserFiles/80400535/Data/Flav/Flav_R03-3.accdb.
    **It is published only as MS Access (.accdb) plus a PDF.** Release 3.1
    is an Access .mdb inside a zip, and the FNDDS flavonoid tables are
    Windows 7-Zip self-extractors. The stdlib can read none of them. When
    `mdb-export` (mdbtools) is on PATH, the installer exports the
    `FLAV_DAT` table and merges it by NDB number. Otherwise flavonoids are
    skipped and `/nutrition/db/status` says why. A `FLAV_DAT` CSV exported
    elsewhere can be passed with `--flavonoid-csv`. Foundation Foods carries
    a few isoflavone values (daidzein, genistein) on its own.
- **Size:** about 10 MB downloaded; the built db is **6.7 MB** (8,262 foods,
  322k nutrient rows). Download temp files are deleted after the build.
- **Schema:** `foods(fdc_id, description, category, source, ndb)`,
  `nutrients(id, name, unit, grp)`,
  `food_nutrient(fdc_id, nutrient_id, amount, approx)` per 100 g, already in
  Quintacle units, an FTS5 `foods_fts`, and a `meta` summary. Only
  `foundation_food` and `sr_legacy_food` rows are kept (Foundation's sample
  and sub-sample rows are dropped), and only nutrients the registry maps.

### Nutrient registry (`nutrition_db/nutrients.py`)

This is the one map from FDC nutrient ids to Quintacle names and units.
Sources are tried in priority order, with a unit factor (for example Copper
mg → mcg ×1000, Vitamin D IU ÷40). Groups: **Macros · Vitamins · Minerals ·
Fatty acids · Flavonoids · Carotenoids · Other**.

Added 2026-11-05:
- **Fatty acids (g):** ALA, EPA, DPA and DHA (omega-3); linoleic acid
  (omega-6); monounsaturated, polyunsaturated and trans fat.
- **Flavonoids (mg):** flavan-3-ols, flavonols, flavones, flavanones,
  anthocyanidins, isoflavones. Each class uses the published class total,
  else the sum of the individual compounds that are published (USDA's own
  definition).
- **Carotenoids (mcg):** beta-carotene, alpha-carotene, lycopene,
  lutein + zeaxanthin, beta-cryptoxanthin.
- **Other:** total sugars, caffeine, theobromine, water.

**Approximations, shown as ≈.** SR Legacy splits 18:3 into ALA (1404) for
only about 2k of 7.8k foods. The rest carry only the undifferentiated 18:3
total (1270), which in ordinary foods is overwhelmingly ALA. The same holds
for linoleic acid (1316 vs the 18:2 total 1269). The stand-in is stored with
`approx=1` and the UI marks it with ≈. **Unknown is never zero:** a nutrient
USDA doesn't publish for a food is absent, and the panel says "no data"
along with how many items had data.

The AI-estimate prompts still ask only for the original 30
(`NUTRIENT_UNITS`). The new compounds come only from USDA, never from a
model's guess. `ALL_NUTRIENT_UNITS` covers canonicalization for everything.

### Targets

- The existing RDA/AI/DV tables are unchanged, plus **ALA Adequate Intake:
  1.6 g/day men, 1.1 g/day women** (NIH ODS), shown as kind "AI (NIH ODS)".
  Because it sits in the table, `/logs/nutrition/{date}` now lists it too.
- Everything else new has **no official target**.
- Labelled **references**, never shown as a %:
  - EPA + DHA 250–500 mg/day: "common guidance", shown as a computed figure.
  - Flavan-3-ols 400–600 mg/day: "research suggestion (2022 flavan-3-ol
    guideline)".
- **Omega-6 : omega-3 ratio** = linoleic acid ÷ (ALA + EPA + DPA + DHA),
  computed in code, no target.

### Matching (deterministic first)

`store.match_food(text)` runs an FTS5 prefix query, then a code score.
- Coverage of the query's words counts most, judged on whole words so "egg"
  never hits "eggplant".
- Then precision: the plainest description wins.
- Then how early the first hit sits (USDA puts the food first:
  "Lamb, leg, …", "Nuts, almonds").
- Penalties: derived products ("Almond butter", "Salmon nuggets"), a
  different leading food ("Flour, almond"), processed or branded forms, and
  babyfood or restaurant rows, unless the user asked for them.
- Raw is the default for a bare name. "roast" maps to "roasted".
  "Separable lean only" wins a tie unless fat was asked for.

For example, "lamb leg roasted" returns *Lamb, leg, whole (shank and
sirloin), separable lean only, trimmed to 1/4" fat, choice, cooked,
roasted*.

`store.pick_candidate` accepts the top candidate when it is confident (score
≥ 0.8 with a 0.06 margin). Otherwise a model (local-first,
`llm_dispatch.parse_structured`) picks an **index** among the top 8, or 0
for none. Its output schema is `{choice: int}`, so it has no field to return
a number in. An out-of-range answer is rejected. If the model fails, the
deterministic top candidate is used when it clears 0.5.
`QUINTACLE_USDA_PICK_PROVIDER=off|auto|local|cloud`; the test suite sets
`off`. The owner can override any match in the UI.

### Preset sourcing (`nodes/logs/usda_sourcing.py`)

Precedence is **label > USDA > estimate**:
- **usda:** every number is read from the db by `fdc_id` at write time.
  `POST /logs/ingredients` with `source: "usda"` **ignores the client's
  numbers**, so a proposal can't carry edited or guessed numbers under a
  USDA badge. Editing a number in the review UI flips the preset to
  `manual`.
- **label:** a printed or typed label's values win. Any nutrient the label
  doesn't list is filled from the generic USDA match, tagged per nutrient
  (`micros[].source`).
- **estimated:** the AI estimate, used only when nothing matches.

Where this applies:
- **Drop text** (`ingredient: greek yogurt`): USDA numbers with **no
  estimate call** when matched. Typed label numbers go to the label path.
- **Drop photo:** `from_label` (new estimate field) decides. For a photo of
  a plain food, the model only identifies and weighs it; the numbers come
  from USDA.
- **Meal composer:** new components are matched to USDA and scaled to the
  proposed quantity. On save they become per-100 g USDA presets.

Stored data:
- Ingredient frontmatter gains `source`, `fdc_id` and `usda_description`
  (only written when known, so legacy files round-trip unchanged).
- `micros[]` gains `source` and `approx`.
- SQLite migrations add `ingredients.source/fdc_id/usda_description`,
  `ingredient_micros.source/approx` and `meal_micros.source`. The markdown
  rebuild carries them.
- Composed meals record each summed nutrient's source as the single source,
  or `mixed`.

**Backfill:** `POST /logs/ingredients/backfill-usda?dry_run=true` lists the
plan: estimated or legacy presets move to USDA numbers, and label presets
get their gaps filled. `dry_run=false` applies it and recomputes every
composed meal that uses a changed ingredient.

### Panels (`nutrition_db/panel.py`, `nodes/logs/nutrition_api.py`)

`build_panel` is pure code. For each nutrient it returns:
- the total, `has_data`, ≈, and the source badge (USDA / label / estimated /
  mixed);
- coverage (how many items had data);
- % of target where an official one exists, otherwise a labelled reference;
- per-component contributions ("Calcium: 96% from Yogurt").

It also returns the computed ratio and EPA+DHA figure. A day panel flattens
composed meals down to their ingredients, so contributions name foods, not
meals.

### Chat nutrition lane (`nutrition_db/chat_lane.py`)

Owner's question: "say I discuss a lamb meal — will it track everything
inside the lamb? Not even the official lamb labels have all of it."

The lane is shaped like the web lane: `chat_nutrition_block(user_text,
provider)` is called next to `chat_web_block` in `kb/chat.py`. How it works:
1. Regex cues decide whether the message is about food or nutrition
   (nutrient names, omega/flavonoid/macros/calories, "how much … in",
   "200g lamb", "2 eggs").
2. Code parses the items and quantities: g, kg, oz and lb; counted foods use
   typical portion weights (egg 50 g, …); no amount means 100 g, and the
   block says so.
3. Each item is matched (top candidate, or the index-only pick) and scaled.
4. The block, "Nutrition facts (USDA FoodData Central, per stated amounts)",
   gives per-item and total values for every nutrient with data, % of the
   owner's targets (profile sex and age), the USDA description assumed, the
   ratio and EPA+DHA, and the list of nutrients USDA has no value for
   ("unknown, not zero").
5. The system text tells the model: use these numbers, don't estimate
   others, say which match was used, suggest logging or composing the meal.

There is no block without the db; the lane never touches the network. It
works for every provider. It uses only the user's own message, never note
content. `QUINTACLE_CHAT_NUTRITION=off` disables it.

### Frontend

- `components/NutrientPanel.tsx`: grouped, collapsible panel, readable at
  390 px; "show N with no data" toggle; tap a row for contributions. Also
  holds `UsdaDbNotice`: "Nutrition database: not installed — Download
  (≈10 MB)". It starts the install job and polls status.
- `components/UsdaMatchPicker.tsx`: source badge, the USDA entry used, and
  "change match" (pick another candidate or search). Also `DraftNutrientPanel`,
  a live panel for unsaved drafts.
- Used in: the Day view (the full panel replaces the 30-row table), the
  meal composer ("Show all nutrients", per-component source and match
  override), and the ingredient preset review card.
- Client: `lib/nutritionApi.ts`.

### Endpoints

See `endpoints.md` § "2026-11-05 additions — Nutrition".

Tests: `core/tests/test_usda_nutrition.py` (23). The db is built from the
fixture CSVs in `core/tests/fixtures/usda/` with no network.
