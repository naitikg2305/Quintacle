# Live-test coverage of model decision points — 2026-11-11

Read-only audit of `core/quintacle_core` (branch `redone-UI`) against the live suites
`core/tests/claude/local/` (Ollama, cloud blocked) and `core/tests/claude/subscription_or_api/`
(Claude via Max, metered API blocked). Both suites parametrize the shared checks in
`core/tests/claude/*_cases.py` (127 tests collected with `--collect-only`; nothing was run).

How to read the table:
- "Local-first" means `llm_dispatch.parse_structured` with provider `auto` (local Ollama first, cloud
  fallback) or `perception/image_policy.run_image_task` (default `local`; cloud only when the user picks
  "Redo with cloud" or on the auto fallback).
- "Covered" means a check reaches the decision through the endpoint the owner would hit AND asserts on
  what the model decided. A check that only asserts something is absent, or that the harness masks
  (`QUINTACLE_SUMMARY_PROVIDER`, `QUINTACLE_SOFT_RECORD_PROVIDER`, `QUINTACLE_VECTOR_LANE` and
  `QUINTACLE_WEB_SEARCH` are all forced `off` in `harness._env`), doesn't count.
- Not counted: `finance/llm.structure_investment` (finance/llm.py:61) has no callers, so it's dead code.
  The MCP end-to-end test `test_claude_saves_note_via_mcp_into_sandbox` checks the MCP *client's* tool
  choice, not a decision the app makes.

**Totals: 56 decision points — 20 yes, 5 partial, 31 NO.**

## Coverage table

| # | Decision point | file:line | Triggered by | Local/cloud path | Live check(s) | Covered? |
|---|---|---|---|---|---|---|
| 1 | `parse_journal_dump` — multi-type classification + field extraction of free text | nodes/journal/llm.py:357 | `/drop` unprefixed text and log-type prefixes (`food:`/`meal:`/`expense:`…); `POST /journal/{date}/parse` | local-first (parse_structured auto) | sort: check_journal_line; journal: check_full_day_sleep/_meal_preset/_push_routine/_mood/_finance/_reading, check_relative_date_journal, check_day_bundle_after_commit; presets: check_meal_prefix_seeded, check_push_day_log_not_preset; finance: check_netflix_subscription, check_macbook_big_purchase | yes |
| 2 | `_resolve_entry_dates` — second pass that re-dates entries | nodes/journal/llm.py:234 | same as #1 when `_DATE_SIGNAL_RE` matches | local-first | check_full_day_dates_stay_on_day ("8/10" triggers the pass; model must not move entries); check_relative_date_drop/_journal are masked because `apply_relative_dates` code overrides "yesterday" | partial |
| 3 | `_resolve_finance_kinds` — expense kind (subscription/big_purchase/…) | nodes/journal/llm.py:285 | same as #1 when any finance entry is proposed | local-first | check_netflix_subscription (subscription), check_macbook_big_purchase (big_purchase) | yes |
| 4 | `maybe_structure_experience` — additive "is this a visit?" + fields | nodes/travel/llm.py:68 | every `/drop` (most branches) and `/journal/{date}/parse` | local-first (regex gate, then model) | check_kyoto_experience (positive); check_bucket_list_typed/_note (negative) | yes |
| 5 | `structure_experience` — explicit experience fields | nodes/travel/llm.py:82 | `/drop` with `experience:`/`visit:` prefix | local-first | — | NO |
| 6 | `maybe_structure_person_mention` — additive new/known person detection | nodes/people/llm.py:95 | every `/drop` (except `person:`) and `/journal/{date}/parse` | local-first (regex gate, then model) | only negative `_no_person` asserts in lifestyle checks; the gate likely never fires on those inputs | NO |
| 7 | `structure_person` | nodes/people/llm.py:31 | `/drop` with `person:`/`friend:` prefix | local-first | — | NO |
| 8 | `classify_text_file_type` — vault document vs KB note | nodes/drop_router.py:468 | `/drop` of a non-image file with no prefix | local-first | sort: check_passport_pdf, check_insurance_pdf, check_trip_plan_pdf, check_eticket_pdf; files: check_docx_resume, check_xlsx_budget, check_pdf_file_metadata, check_scanned_pdf | yes |
| 9 | `suggest_kb_entry` — folder/title/content/links | nodes/kb/llm.py:90 | `/drop` kb_entry branch (files, `note:`); `POST /kb/sort`; `POST /kb/drop` | local-first | sort: check_trip_plan_pdf/_md, check_eticket_pdf, check_lecture_notes; travel: check_bucket_list_note, check_second_plan_reuses_region, check_vienna_plan_*; files: check_docx_resume, check_pptx_deck, check_md_with_local_image | yes |
| 10 | `suggest_kb_entry_for_folder` | nodes/kb/llm.py:114 | `POST /kb/sort` with `target_folder` | local-first | — | NO |
| 11 | `suggest_kb_update` — merge new text into an existing note | nodes/kb/llm.py:288 | `POST /kb/sort` with target folder+slug (private pinned local) | local-first | — | NO |
| 12 | `suggest_kb_placement` — file without rewording | nodes/kb/llm.py:141 | `/drop` with `keep_as_is` | local-first | — | NO |
| 13 | `suggest_kb_batch` (incl. `trip_name` for photo folders) | nodes/kb/llm.py:190 | `POST /kb/batch-drop` | local-first (no provider param, env default) | — | NO |
| 14 | `suggest_record_fold` / `suggest_record_fold_new` — distill chat into note points | nodes/kb/llm.py:262 / :272 | `POST /kb/record-that` | local-first (private pinned local) | — | NO |
| 15 | `structure_document` — vault fields (type, issue/expiry) | nodes/documents/llm.py:24 | `/drop` document_entry branch (PDF/photo) | local-first (photo text → local via `text_provider_for_image`) | check_passport_pdf, check_insurance_pdf, check_passport_photo | yes |
| 16 | `structure_home_item` | nodes/home/llm.py:22 | `/drop` `home:` prefix | local-first | check_home_text | yes |
| 17 | `structure_residence` | nodes/home/llm.py:153 | `/drop` residence prefix | local-first | — | NO |
| 18 | `structure_credit_card` | nodes/finance/llm.py:33 | `/drop` `creditcard:`/`card:` prefix | local-first | — | NO |
| 19 | `structure_stock_transaction` | nodes/stocks/llm.py:43 | `/drop` `stock:`/`invest:` prefix, or unprefixed text passing `looks_like_stock_transaction` | local-first | — | NO |
| 20 | `structure_habit` | nodes/logs/habit_llm.py:54 | `/drop` `habit:`/`goal:`/`budget:` prefix | local-first | — | NO |
| 21 | `describe_wardrobe_item_from_text` | nodes/wardrobe/llm.py:69 | `/drop` `wardrobe:`/`item:` prefix (text) | local-first | check_wardrobe_text | yes |
| 22 | `describe_grooming_item_from_text` | nodes/grooming/llm.py:74 | `/drop` `product:` prefix (text) | local-first | check_grooming_text | yes |
| 23 | `suggest_outfit` | nodes/wardrobe/llm.py:154 | `/drop` outfit prefix; `POST /wardrobe/outfits/suggest` | local-first | — | NO |
| 24 | `suggest_grooming_routine` | nodes/grooming/llm.py:106 | `/drop` `grooming:` prefix; `POST /grooming/routines/suggest` | local-first | — | NO |
| 25 | `suggest_workout_routine` | nodes/logs/routine_llm.py:26 | additive preset on unprefixed `/drop` (when `parse_routine_definition` can't parse it); `POST /logs/routines/suggest` | local-first | check_pull_day_unprefixed | yes |
| 26 | `suggest_meal_composition` | nodes/logs/meal_composer.py:65 | `/drop` `recipe:` prefix and the unprefixed additive preset; `POST /logs/meals/suggest-composition` | local-first | check_meal_plan, check_recipe_from_seeded, check_meal_prep_usda, check_lamb_meal_micros | yes |
| 27 | `estimate_nutrition` — macros from text | nodes/logs/nutrition_llm.py:64 | `/drop` `ingredient:` (label text, or no USDA match); `POST /logs/meals/estimate`; fallback inside meal composer | local-first | check_ingredient_prefix_label (label-text reading only); the no-USDA-match `source=estimated` path is never exercised | partial |
| 28 | `pick_candidate` — USDA row choice | nutrition_db/store.py:375 | ingredient/meal proposals (`usda_proposal`), chat nutrition lane, `GET /nutrition/match` | local-first (or deterministic when the ranking is confident) | check_broccoli_ingredient, check_meal_prep_usda, check_lamb_meal_micros, check_chat_lamb_selenium (confident top hits skip the model, so the model rung may not fire on every one) | yes |
| 29 | `extract_statement_transactions` — rows from a statement PDF/photo | nodes/finance/llm.py:92 (local rows :96) | `/drop` `statement:` + PDF/photo | local-first (text layer/OCR + parser, local model for leftovers) | check_statement_pdf (PDF only; statement photo untested) | yes |
| 30 | `classify_image_type` — photo kind (OCR rules → YOLO → local VLM label) | nodes/drop_router.py:381; perception/image_router.py:226 (`vlm_classify` :216) | every unprefixed photo `/drop` | local-first (image_policy) | check_label_photo, check_label_per_serving/_per_100g, check_restaurant_receipt, check_passport_photo, check_tshirt_photo, check_gps_photo_place; `prepared_meal` and `full_outfit` kinds never exercised | partial |
| 31 | `describe_images` — photo caption + OCR text at drop | nodes/kb/drop.py:58 (local :115) | `/drop` photo → kb_entry/document branches; docx scan fallback | local-first (`private` pins local) | check_passport_photo (OCR text feeds the dates); check_gps_photo_place (no assert on caption content) | partial |
| 32 | `estimate_nutrition_from_image` — label photo | nodes/logs/nutrition_llm.py:186 (local :118, local-LLM rung :148) | `/drop` photo classed nutrition_label | local-first | check_label_photo, check_label_per_serving, check_label_per_100g (clean renders likely finish at `ocr+parser`, so the :148 local-LLM rung isn't forced) | yes |
| 33 | Plain food photo → VLM names food + grams → USDA/estimate | nodes/logs/nutrition_llm.py:153–181 | `/drop` photo classed prepared_meal | local-first | — | NO |
| 34 | `extract_finance_from_receipt` | nodes/drop_router.py:565 (local :523, local-LLM rung :551) | `/drop` photo classed receipt | local-first | check_restaurant_receipt (the parser finds the total, so the :551 rung isn't forced) | yes |
| 35 | `describe_wardrobe_item` (photo) via `describe_item_local` | nodes/wardrobe/llm.py:27; perception/local_describe.py:62 | `/drop` photo classed outfit_item | local-first | check_tshirt_photo | yes |
| 36 | `describe_outfit_photo` | nodes/wardrobe/llm.py:87 | `/drop` photo classed full_outfit | local-first | check_outfit_photo is `pytest.skip` (no fixture) | NO |
| 37 | `describe_grooming_item` (photo) | nodes/grooming/llm.py:34 | `/drop` `product:` + photo | local-first | — | NO |
| 38 | `_describe_pdf` — text layer → OCR → cloud summary | nodes/kb/drop.py:~240 | any PDF `/drop`, `/kb/drop`, `/kb/batch-drop` | local-first | check_trip_plan_pdf, check_eticket_pdf, check_passport_pdf, check_insurance_pdf, check_pdf_file_metadata, check_scanned_pdf | yes |
| 39 | `_describe_docx` embedded-image caption fallback | nodes/kb/drop.py:296 | `.docx` drop with little text (scan pasted into Word) | local-first (via describe_images) | — (check_docx_resume has a text layer) | NO |
| 40 | `_describe_video` — frames → VLM | nodes/kb/drop.py:352 | video `/drop` | local-first | — | NO |
| 41 | `perceive_photo` — YOLO tags, face detection + face **match** to enrolled people | perception/__init__.py:77 | every photo `/drop`; `POST /kb/asset/perceive`; MCP `perceive_photo`; photo save → auto-journal | local-only | — (no check asserts `perception` or a face match) | NO |
| 42 | `geocode` — GPS → place (offline GeoNames, Claude fallback) | nodes/kb/photo_organizer.py:22; photo_place.py:170 | GPS photo `/drop` (photo folder), Save via `/kb/entries/with-asset` (📍 line) | local-first since 2026-11-11 | check_gps_photo_place: cloud asserts Paris/France/Europe; local asserts only coords + time, not the offline place | partial |
| 43 | `describe_images` with a question (on demand) | nodes/kb/api.py:398; mcp_server/server.py:707 | `POST /kb/asset/describe`; MCP `describe_photo` | local-first | — | NO |
| 44 | `maybe_polish` — auto-journal photo line rewrite | nodes/kb/auto_journal.py:250 | photo commit, only when `QUINTACLE_AUTOJOURNAL_POLISH=1` | **cloud-only** | — | NO |
| 45 | Chat answer, local model (`_run_local`) | nodes/kb/chat.py:1133 | `POST /kb/chat` with `local:*` | local | check_fact_recall, check_private_note, check_private_handoff, check_transcript_autosave, check_chat_lamb_selenium | yes |
| 46 | Chat answer, Max (`_run_max`) | nodes/kb/chat.py:871 | `POST /kb/chat` with `max:*` (user-chosen escalation) | cloud (user choice) | same five checks with provider=cloud (privacy captured via `_CaptureMax`) | yes |
| 47 | Chat answer, metered API (`_run_anthropic`, native web_search tool) | nodes/kb/chat.py:889 | `POST /kb/chat` with `claude-*`; also the Max failure fallback | cloud (user choice / fallback) | blocked on purpose in both suites | NO |
| 48 | Chat answer, OpenAI / Bedrock | nodes/kb/chat.py:956 / :1049 | `POST /kb/chat` with OpenAI/Bedrock model ids | cloud (user choice) | — | NO |
| 49 | Web lane for non-native providers (`needs_web` + query + model reads results) | web_search.py:341 | `POST /kb/chat` local/Bedrock with web on | local model; only the query leaves the machine | — (harness `QUINTACLE_WEB_SEARCH=off`; chat checks send `web: false`) | NO |
| 50 | Chat nutrition lane (USDA facts handed to the model) | nutrition_db/chat_lane.py:203 | `POST /kb/chat` food/nutrient question | local pick for local chat | check_chat_lamb_selenium | yes |
| 51 | Embeddings / vector retrieval lane | retrieval.py:178 (search :225) | chat context, MCP `search_index`, `/search`, every index write | local (Ollama `/api/embed`) | — (harness `QUINTACLE_VECTOR_LANE=off`; check_search_index_finds_seeded_note runs FTS + graph only) | NO |
| 52 | `prose_summary` — search-index one-liner | retrieval.py:505 | every note/journal save (`safe_index_note`/`_journal`), backfill | local (pinned) | — (harness `QUINTACLE_SUMMARY_PROVIDER=off`) | NO |
| 53 | Soft-record `extract_facts` | nodes/kb/soft_record.py:127 | `POST /transcripts/archive` with `final=true` (background) | local (pinned) | — (harness `QUINTACLE_SOFT_RECORD_PROVIDER=off`; check_transcript_autosave sends `final: false`) | NO |
| 54 | Career `draft_group` | nodes/career/draft.py:63 | `POST /career/record/run` | local-first | — | NO |
| 55 | Career `rank_candidates` | nodes/career/website.py:316 | `POST /career/website/run` | local-first | — | NO |
| 56 | `generate_image` | nodes/kb/image_gen.py:18 | `POST /kb/generate-image` | **cloud-only** (OpenAI gpt-image-1-mini) | — | NO |

## NO rows, ranked by how often the owner hits them

The owner uses drops, chat, photos and journal daily.

**Daily**
1. **#6 person-mention detection.** Runs on every unprefixed drop and every journal parse. Only false negatives are checked today.
2. **#41 local perception (tags + face match).** Runs on every photo drop and save. A wrong face match mislabels people in the graph.
3. **#33 food photo without a label.** Meal photos are daily. Partial #30 (`prepared_meal` kind never routed) belongs with this one.
4. **#52 prose_summary.** Runs on every note and journal save, and it feeds search and chat retrieval.
5. **#51 embeddings / vector lane.** Runs on every chat turn and every search, whenever sqlite-vec is installed.
6. **#53 soft-record extraction.** Runs on every closed, kept chat. Its facts get fed back into later chats.
7. **#49 web lane for local chat.**
8. **#47 metered-API chat.** This is also where Max failures fall back, silently apart from a note in the reply.

**Weekly-ish**

9. **#36 outfit photo and #37 grooming product photo.**
10. **#12 keep-as-is placement, #10/#11 `/kb/sort` (scoped and merge), #14 record-that.**
11. **#13 batch-drop**, including `trip_name` photo foldering.
12. **#7 `person:`, #5 `experience:`, #19 stock trade (prefixed and the unprefixed regex lane), #20 habit.**
13. **#23 outfit composer and #24 grooming routine composer.**
14. **#43 on-demand photo describe (app and MCP).**

**Rare**

15. **#40 video and #39 scanned DOCX.**
16. **#17 residence and #18 credit card.**
17. **#54/#55 career runs.**
18. **#48 OpenAI/Bedrock chat, #44 polish, #56 image generation.**

## Cloud-only paths and local-first violations

- **#44 `auto_journal.maybe_polish`** violates local-first. Prose polish is named as an easy, default-local task, but this calls `cloud_client()` with no local path. Mitigation: it's off by default and needs `QUINTACLE_AUTOJOURNAL_POLISH=1`.
- **#56 `generate_image`** is OpenAI-only with no local alternative. It's generative and user-initiated rather than a decision, so it's a documented exception, not an ingest violation.
- **#47/#48 cloud chat models** are user-chosen escalations, which is allowed. The caveat: `_run_max` falls back to the metered API by itself when Max fails. The reply flags it, but the user never chose the metered API.
- **Stale claims (docs only, the code is local-first now):**
  - The `llm_dispatch.py` module docstring still says "Geocoding also deliberately stays cloud".
  - The `check_gps_photo_place` docstring says "there is no local geocoder".
  - The `/kb/asset/describe` docstring says "BILLED: every call here costs real Anthropic API budget".
  - `describe_images` still honors the legacy `QUINTACLE_VISION` env. If that's set to `cloud` on a machine, image description silently defaults to cloud.

**Status 2026-11-11 (later the same day):** fixed in code, the findings above are kept as written.
`maybe_polish` (#44) now goes through `llm_dispatch.parse_structured` pinned to `provider="local"`, so cloud
only runs if the user sets `QUINTACLE_AUTOJOURNAL_POLISH_PROVIDER=auto|cloud`. `QUINTACLE_VISION` is read
only by `image_policy.image_provider()`, as a deprecated alias that logs a warning once and maps `cloud` to
`auto`. The three stale docstrings have dated correction notes. The Max-to-metered fallback is unchanged
because it's an owner decision. Faked tests are in
`core/tests/claude/existing/test_local_first_polish_and_vision_1111.py`.

## Suggested one-line live checks for each gap

These are descriptions only; none of these tests were written.

| Gap | Suggested check |
|---|---|
| #6 person mention | `/drop` "dinner with my friend Priya, she just moved to Denver" (people registry seeded with one other name) → expect a `person_entry` named Priya; a seeded name in the text → a `…/Mentions` kb_entry. |
| #41 perception | Enroll one face from a CC0 portrait, then `/drop` a second CC0 photo of the same person → the photo-bearing entry's `perception.faces[0].match.person_name` equals the enrolled name (no match for a different person). |
| #33 + #30 food photo | `/drop` a rendered or CC0 photo of a plated food → `ingredient_preset` with `source=usda`, a food name, and `basis_amount_g` that isn't the default 100 when the VLM gave grams. |
| #52 prose_summary | With summary provider `local`, POST a note, then read its retrieval row → summary is under 20 words, mentions a key term from the body, and isn't the deterministic first line. |
| #51 embeddings | With the vector lane on, seed a note "locker code 4417 at Gold's Gym", then search "gym combination" (no word overlap) → that note is in the top 3. |
| #53 soft record | `/transcripts/archive` `final: true` with user text "I'm switching to a 4-day split next week" → `GET /soft-record` holds one fact about a 4-day split and no assistant advice. |
| #49 web lane | Local chat with `web: true` on a current-events question → the reply cites a URL from the fetched results, and the captured outbound query has no note content. |
| #47 metered chat | Spend-capped: chat `claude-haiku-5-5` on the fact note → the reply contains 4417 and a private-note marker is absent from the request. |
| #36 outfit photo | `/drop` a CC0 photo of a person in everyday clothes → `outfit_photo`, not `wardrobe_item`. |
| #37 grooming photo | `/drop` `product:` + a rendered bottle label "CeraVe Hydrating Cleanser" → `grooming_item` named CeraVe … Cleanser, category skincare. |
| #12 keep-as-is | `/drop` the Lisbon plan .md with `keep_as_is` → folder under `Fun/Travel/Planned`, content byte-identical to the input. |
| #10 sort to folder | `POST /kb/sort` with `target_folder=Knowledge/Tech Notes` and Raft text → a title naming Raft, folder unchanged. |
| #11 sort merge | `POST /kb/sort` targeting "Lease 2026" with "rent is now $1,900" → the merged body keeps "renews every August" and adds $1,900. |
| #14 record-that | `POST /kb/record-that` on a 4-turn chat about a gym plan → points list the stated plan only, folder under an existing seeded folder. |
| #13 batch-drop | `POST /kb/batch-drop` with 2 GPS JPGs from the same Paris day + 1 lecture PDF → both photos share one folder/trip_name, the PDF lands elsewhere. |
| #7 person prefix | `/drop` "person: met Alex at the climbing gym last Saturday" with `reference_date` → name Alex, how_met mentions the climbing gym, met_date is the previous Saturday. |
| #5 experience prefix | `/drop` "visit: Blue Bottle Coffee in Arlington, 4/5, would go back" → city Arlington, rating 4, would_return true. |
| #19 stock | `/drop` "bought 10 shares of AAPL at $182.50" (unprefixed) → one `stock_transaction` buy, qty 10, price 182.50, no finance entry. |
| #20 habit | `/drop` "habit: gym 4 times a week" → `habit_entry` with a weekly target of 4. |
| #23 outfit composer | With wardrobe seeds, `/drop` outfit prefix "something for a cold office day" → components drawn only from seeded item names. |
| #24 grooming routine | With grooming seeds, `/drop` "grooming: morning routine with my cleanser" → the routine includes the seeded CeraVe Foaming Cleanser (`is_new` false). |
| #43 asset describe / MCP describe_photo | Save the receipt PNG as an asset, then `/kb/asset/describe` with question "what is the total?" → the reply contains the printed total. |
| #40 video | `/drop` a 3-second rendered MP4 of a red square moving → the description mentions red, pipeline not cloud in local mode. |
| #39 scanned docx | `/drop` a .docx holding only an image of the consistent-hashing lecture → the description mentions hashing. |
| #17 residence | `/drop` residence prefix "moved into 12 Oak St, Arlington on 2026-09-01" → name/city/moved_in exactly as typed. |
| #18 credit card | `/drop` "card: Chase Sapphire Preferred, $95 annual fee, 3x dining" → issuer Chase, annual_fee 95, no invented fields. |
| #54 career draft | `POST /career/record/run` on 2 seeded work-log notes → a draft that names only facts from those notes. |
| #55 career rank | `POST /career/website/run` with one blocked and two public notes → the blocked note is never ranked, and the more substantive note ranks first. |
| #48 OpenAI/Bedrock chat | Spend-capped: one fact-recall chat per provider → the reply contains 4417 and no private content in the request. |
| #44 polish | With the env flag on, save a GPS photo → the journal line keeps every fact and the 📷. Better fix: move it to the local model and test that. |
| #56 image gen | Spend-capped: `/kb/generate-image` "a red circle" → returns PNG bytes. Run it only on demand. |
| #2 dates (partial) | `/drop` "last Tuesday I paid $30 for a haircut" with reference 2026-11-12 → entry_date 2026-11-10 (a phrase the code rule may not cover, so the model pass has to decide). |
| #27 estimate (partial) | `/drop` "ingredient: grandma's lentil dal, 250g" (no USDA match) → `source=estimated`, kcal in a plausible 250–450 band, micros tagged estimated. |
| #30 classify (partial) | Covered by the #33 and #36 checks above, which route `prepared_meal` and `full_outfit`. |
| #31 describe (partial) | `/drop` a rendered scene with an obvious object (a red bicycle) and no EXIF → the kb_entry content mentions a bicycle. |
| #42 geocode (partial) | In the local suite, with GeoNames installed, the GPS check should also assert Paris/France in the 📍 line and folder (local mode resolves offline now). |
