# Perception and the auto photo-journal

Derived from code at commit `1a46c92` on 2026-10-15.

Two halves, built as one wave: a fully local **perception** package
([core/quintacle_core/perception/](../../core/quintacle_core/perception/)) —
object tags, face detection/recognition with enrollment, deterministic scene
attributes, zero LLM calls — and the **auto photo-journal**
([core/quintacle_core/nodes/kb/auto_journal.py](../../core/quintacle_core/nodes/kb/auto_journal.py))
that turns a committed photo into a deterministic journal line plus graph
edges, with a "who is this?" tag flow for unknown faces. Phone-runtime
counterpart (TFLite backend) at the end; its parity numbers live in
[phone/tier2-perception-tflite/README.md](../../phone/tier2-perception-tflite/README.md)
and are cited, not re-derived, here.

## The perception contract (`perception/__init__.py`)

Three functions, consumed by the auto-journal side and the HTTP/MCP surfaces
(docstring in the module calls them out as do-not-rename):

```
perceive_photo(data, mime) -> PerceptionResult | None   # None = deps missing
enroll_face(embedding_id, person_name)                  # stdlib-only, always works
lens_people() -> list[str]                              # names with >=1 enrolled embedding
```

`PerceptionResult` (pydantic): `tags` (deduped YOLO labels,
best-confidence first), `scene`
(`{"daylight": bool|None, "outdoor_hint": bool|None, "brightness": float}`),
`faces` (list of `FaceObservation`: `box` as 0-1 x/y/w/h fractions,
`embedding_id` persisted at observation time, `match` =
`{"person_name", "score"}` or `None` for unknown).

`perceive_photo` upright-rotates via `ImageOps.exif_transpose` before any
model looks (phone photos are stored rotated with an EXIF Orientation tag),
reads scene EXIF off the pre-transpose original, raises `ValueError` for
undecodable bytes, and returns `None` — with ONE warning log, not one per
call — when the heavy deps are absent, so callers wire it in unconditionally.

**Dependency discipline:** onnxruntime + numpy live in
`core/perception-requirements.txt` (~75 MB installed), deliberately NOT in
`core/requirements.txt`; all heavy imports are lazy inside `perceive_photo`.
`enroll_face`/`lens_people` are stdlib-only (json + pure-python cosine in
`storage.py`) and work in any install.

## The models (`perception/yolo.py`, `faces.py`, `scene.py`, `download.py`)

| Job | Model | File / size | Source |
|---|---|---|---|
| Object tags (80 COCO classes) | YOLOX-nano, 416px, conf ≥ 0.35 | `yolox_nano.onnx` ~3.5 MB | official Megvii YOLOX release asset |
| Face detect (boxes + 5 landmarks) | SCRFD-500M, 640px letterbox | `det_500m.onnx` ~2.5 MB | insightface `buffalo_sc` zip |
| Face embed (512-d, L2-normed) | MobileFaceNet ArcFace | `w600k_mbf.onnx` ~13 MB | insightface `buffalo_sc` zip |

All run on onnxruntime **CPUExecutionProvider**; decode/NMS/Umeyama
alignment are reimplemented in numpy so there is no cv2 or torch anywhere
(torch-family wheels are GB-scale and facenet-pytorch's pins don't resolve
on Python 3.14 — the `yolo.py`/`faces.py` module docstrings carry the full
reasoning). Weights download on **first use only** into the perception
models dir (`download.py` — the only network traffic the package ever
makes); inference is fully offline. Scene attributes (`scene.py`) are not a
model at all: EXIF capture hour → `daylight`, top-of-frame sky-like pixel
fraction → `outdoor_hint` (True or None, never False — no visible sky
proves nothing), mean luma → `brightness`; every value is `None` rather
than a guess when the photo can't say.

### Two thresholds, two owners

- `perception.FACE_MATCH_THRESHOLD = 0.55` (`perception/__init__.py`) —
  the cosine floor below which `perceive_photo` reports a face as unknown
  rather than naming it. 0.55 favors "unknown" over a false name.
- `auto_journal.MATCH_THRESHOLD = 0.8` (env `QUINTACLE_FACE_MATCH_THRESHOLD`,
  `nodes/kb/auto_journal.py`) — the stricter floor a match must clear before
  the journal/graph *assert* the name. A 0.55–0.8 match still rides to the
  UI as an unknown face carrying `suggested_name`, so the tag panel can
  offer it without the journal ever claiming it (`split_faces`).

## Storage and privacy (`perception/storage.py`)

Everything lives under `<data dir>/perception/` (default
`~/.quintacle/perception/`): `models/` (downloaded weights, overridable via
`QUINTACLE_PERCEPTION_MODELS_DIR`), `embeddings/` (one small JSON per face
observation: id, vector, source = `{mime, sha256-of-photo}`, created_at),
`profiles.json` (`{"people": {"<name>": [embedding_ids]}}`).

**Biometric privacy rule (stated in `storage.py` and enforced by shape):
embedding vectors never leave `~/.quintacle/perception/`.** They are never
written into KB markdown, never sent to any API/LLM, never put on graph
edges — everything downstream (proposal payloads, journal lines, edges,
MCP responses) carries person NAMES and opaque `embedding_id`s only. The
photo itself is referenced by content sha256, never re-stored. The
directory syncs device-to-device as opaque bytes via the existing LAN sync.
Matching is best-of cosine over every enrolled embedding (`best_match`);
`load_embedding` clamps ids to bare alnum so an id arriving over HTTP/MCP
can't smuggle a path.

## Where perception is wired

- **Drop**: `POST /drop` runs `perceive_photo` over a dropped image and
  attaches the result as a `perception` field on photo-bearing proposals
  (`core/quintacle_core/api.py`; any failure degrades to "no perception
  field", never a failed drop).
- **REST**: `POST /kb/asset/perceive`
  (`core/quintacle_core/nodes/kb/api.py`) — perception over a stored KB
  asset, free.
- **MCP**: the `perceive_photo` tool
  (`core/quintacle_core/mcp_server/server.py`) — "LOCAL & FREE" twin of the
  billed `describe_photo`; image bytes and vectors never cross MCP.
- **Commit hook**: the auto-journal below.

## The auto photo-journal (`nodes/kb/auto_journal.py`)

When `/kb/entries/with-asset` commits a photo entry (single Drop and
batch-drop review both commit through it), `process_photo_commit(...)` runs:

1. **Perception**: the proposal's carried `perception` payload if the
   frontend kept one through review, else one fresh `perceive_photo_safe()`
   pass. The seam is lazy and failure-tolerant — module absent, declining,
   or raising all read as "no perception"; a photo save can never fail
   because face recognition isn't installed.
2. **The line** — `auto_journal_line(...)`, the pure composer: zero LLM
   calls, same facts in → same line out, absent parts omitted. Format:

   ```
   📷 <EXIF h:mm AM/PM> — with <names> at <Place> · <scene word> · <≤4 tags> (photo: <title>)
   ```

   e.g. `📷 2:14 PM — with Alex at Hermann Park · sunny · dog, frisbee
   (photo: Lake hike)`. The scene word is one conservative deterministic
   mapping (`_scene_word`: night / sunny / outdoors / indoors / nothing);
   the place comes from `place_from_photo_folder` — the trailing trip/city
   segment of the EXIF-derived `media/photos/<year>/<month>/<place>` folder
   already decided at propose time, so no second geocode call (a bare
   year/month folder deliberately yields no place).
3. **Marker-based, undoable, dedup-checked append**: the line lands in the
   EXIF **date's** journal wrapped in the same marker machinery MCP appends
   use (`nodes/journal/store.py`: `save(date, content,
   marker="auto-photo:<folder>/<slug>")`). The marker id is derived from
   folder/slug, so a re-commit of the same photo never double-appends
   (`has_marked_append` checked first), and `strip_marked_append` /
   `rewrite_marked_append` give per-photo undo and in-place edit. No EXIF
   date → no journal line.
4. **Edges, never copied text**: photo note → person profile
   (`pictured_with`), journal day → person (`pictured_with`), photo note →
   matching travel experience (`at_location`), all with
   `source_of_edge="photo_perception"`, all idempotent via `create_edge`.
5. **Return payload**: matched people, `unknown_faces` (each with
   `embedding_id`, box, optional `suggested_name`), journal date/line,
   edges — this feeds the Drop page's tag panel.

`maybe_polish(line)` is the one optional LLM touch: OFF by default,
`QUINTACLE_AUTOJOURNAL_POLISH=1` routes the already-composed FACTS through
one billed `DEFAULT_MODEL` call for phrasing; any failure falls back to the
deterministic line.

### The tag flow ("who is this?")

`POST /perception/tag` (`nodes/kb/perception_api.py`, body: embedding_id +
person_name + photo folder/slug) → `tag_unknown_face(...)`:

- enrolls the stored embedding (seam tolerated absent — the rest still
  happens and enrollment catches up when perception installs),
- creates the person entry if new, canonicalized against known people first
  (`normalize.canonicalize_name` — "alex" doesn't fork a second Alex),
- creates the `pictured_with` edges (photo note and, via the asset's
  re-read EXIF, the journal day),
- folds the name **into the photo's existing marker-tagged journal line in
  place** (`add_person_to_line` + `rewrite_marked_append`) — one line per
  photo stays the record, one marker still undoes everything about that
  photo — or composes a fresh line if the photo never got one.

Tagging is always optional; dismissing the panel simply never calls the
endpoint. UI: the Drop page's unknown-faces panel
(`frontend/app/kb/drop/page.tsx`).

### Appearances, derived from the graph

`GET /people/{name}/appearances` (`nodes/people/api.py`) computes where a
person appears — photos and journal dates — purely from `pictured_with`
edges via `reverse_lookup` on their profile id. Nothing is written into the
person's file; the photo note and the journal line are the only records,
and the person page (or any LLM walking the graph) derives the rest. UI:
"Appears in" on `frontend/app/people/page.tsx`; the Day page shows the
day's photos strip (`frontend/app/day/page.tsx`).

## The TFLite backend (phone lane, desktop-proven)

`perception/backend_tflite.py` runs the SAME three models on LiteRT
(`ai-edge-litert`) when `QUINTACLE_PERCEPTION_BACKEND=tflite`; default
`onnx` leaves the ONNX path byte-for-byte untouched. The design point is
**zero duplicated math**: `yolo.py`/`faces.py` only ever touch a session
object through the onnxruntime interface (`get_inputs()[0].name`,
`run(None, {name: blob})`), so the backend installs `_LiteRTSession`
adapters into their session caches and all preprocessing / decode / NMS /
alignment / embedding code runs unchanged — parity bugs can only come from
converted weights. Boundary translation only: NCHW→NHWC input transpose,
`resize_tensor_input` for flatbuffer-collapsed dynamic dims, and outputs
mapped back to ONNX order **by unique static shape, never by name**
(onnx2tf's tf_converter backend reattaches ONNX tensor names to the wrong
outputs — observed and documented in the Tier 2 README).

The `.tflite` files are build artifacts from
`phone/tier2-perception-tflite/convert.py` (its own Python 3.12 venv;
onnx2tf doesn't support 3.14), placed in
`<models dir>/tflite/<name>_<variant>.tflite` — never auto-downloaded,
never committed. Missing litert or missing files degrade to the same
perceive_photo-returns-None-with-one-warning path.

**Parity story — cited from
[phone/tier2-perception-tflite/README.md](../../phone/tier2-perception-tflite/README.md)
(desktop, 2026-10-15, 14 real photos):** float32 conversion is exact for
this purpose (embedding cosine 1.0000, identical boxes/tags);
dynamic-range-quant drifts but harmlessly (cosine 0.943–0.990, box IoU
≥ 0.994, tags wobbled on 2/14 marginal detections); cross-backend
enrollment — face enrolled from an ONNX embedding, matched by TFLite on
different photos — holds **11/11 at the 0.55 threshold** for both
variants, so desktop-enrolls → phone-matches works. LiteRT+XNNPACK
measured ~2.6x faster than onnxruntime CPU (361 → 132–138 ms/photo).
DRQ set is ~5.7 MB vs ~19 MB ONNX. **No device has run this yet** — the
NNAPI/QNN delegate path (`QUINTACLE_TFLITE_DELEGATE`) is wired but a
desktop no-op, and the README's device-pending list is the honest status.

## Env knobs

| Variable | Values (default first) | Read by |
|---|---|---|
| `QUINTACLE_PERCEPTION_BACKEND` | `onnx` \| `tflite` | `perception/backend_tflite.py` |
| `QUINTACLE_TFLITE_VARIANT` | `float32` \| `dynamic_range_quant` | `backend_tflite.py` (picks which converted file) |
| `QUINTACLE_TFLITE_DELEGATE` | unset \| delegate name or `.so` path | `backend_tflite.py` (desktop: warn once, CPU fallback) |
| `QUINTACLE_PERCEPTION_MODELS_DIR` | `<data dir>/perception/models` | `perception/storage.py` (tests reuse one weight copy) |
| `QUINTACLE_FACE_MATCH_THRESHOLD` | `0.8` | `nodes/kb/auto_journal.py` (journal/graph assertion floor) |
| `QUINTACLE_AUTOJOURNAL_POLISH` | unset \| `1` (billed) | `auto_journal.maybe_polish` |
| `QUINTACLE_DATA_DIR` | `~/.quintacle` | perception root lives under it |

## Tests

`core/tests/test_perception.py`, `core/tests/test_backend_tflite.py`
(two-tier skip: env/degradation tests always run; model/interpreter tests
skip without deps/artifacts), `core/tests/test_auto_journal.py`. Suite at
this commit, verified in a fresh venv: **335 passed / 5 skipped** with
`perception-requirements.txt` installed (the 5 are TFLite interpreter tests
needing converted models); **331 passed / 9 skipped** on the minimal
`requirements.txt`-only venv.
