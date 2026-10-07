# Quintacle — On-device inference on the Galaxy S25 Ultra

Status: **research, 2026-10-07. Nothing built.** Numbers below are from
Qualcomm AI Hub model cards, Google's LiteRT-LM model cards, vendor
announcements, and one independent write-up — cited inline. Where a number
is for a sibling chip (S26 Ultra / 8 Elite Gen 5) rather than the S25U
itself, it says so. First thing to do is get *real* S25U numbers with the
no-code test at the bottom.

## The hardware, precisely

| | |
|---|---|
| SoC | Qualcomm **SM8750-AC "Snapdragon 8 Elite for Galaxy"** (3nm TSMC). Not "8 Gen 2 Elite" — 8 Gen 2 was the S23, 8 Gen 3 the S24, 8 Elite the S25. The "for Galaxy" bin is overclocked vs. the stock 8 Elite. |
| CPU | 2× Oryon V2 prime @ 4.47 GHz + 6× Oryon V2 performance @ 3.53 GHz |
| GPU | Adreno 830 @ 1.2 GHz (OpenCL, Vulkan) |
| NPU | **Hexagon NPU** — 6-core vector + 8-core scalar accelerator. Qualcomm claims **45% faster and 45% better perf/watt than the 8 Gen 3's NPU**. Qualcomm stopped publishing a TOPS figure for this generation; the 8 Gen 3 was ~45 TOPS INT8, so "60-ish" is a reasonable but unofficial ballpark. |
| RAM | **12GB** (US) or 16GB (some markets), LPDDR5X |
| Battery | 5000 mAh |

**On the "natural language chip" point:** there is no separate NLP chip. The
Hexagon NPU *is* the thing — it's a general tensor accelerator that happens
to be what Galaxy AI's on-device language features run on, alongside the
Sensing Hub for always-on low-power stuff. It's the same silicon any
third-party app can target. That's the good news: nothing is locked to
Samsung.

**Scale vs. the Coral:** a Coral USB TPU is ~4 TOPS INT8, vision-only, 8MB
on-chip. The Hexagon NPU is an order of magnitude more compute, runs
transformer decode natively at W4A16, and has 12GB of host RAM behind it.
Not comparable.

## What actually runs, with measured numbers

### On the NPU, via Qualcomm Genie (AI Hub model cards, S25U-class silicon)

| Model | Precision | Decode tok/s | TTFT | Context | Source |
|---|---|---|---|---|---|
| Llama 3.2 **3B** Instruct | W4A16 | **26.5** (8 Elite for Galaxy) / 28.2 (Gen 5 for Galaxy) | 0.08–2.5 s | 4096 | [AI Hub card](https://huggingface.co/qualcomm/Llama-v3.2-3B-Instruct) |
| Llama 3.2 **1B** Instruct | W4A16 | **~54** (8 Elite) | — | — | [AI Hub card](https://huggingface.co/qualcomm/Llama-v3.2-1B-Instruct) |
| Llama 3 **8B** Instruct | W4A16 | **~15** (8 Elite) | — | 4096 | [AI Hub card](https://huggingface.co/qualcomm/Llama-v3-8B-Instruct) |
| **Qwen3-8B** | W4A16 | export exists for 8 Elite; mobile number not published (X Elite laptop: 13.6, X2 Elite: 25) | — | 4096 | [AI Hub card](https://huggingface.co/qualcomm/Qwen3-8B), Apache 2.0 |

An independent write-up on an 8 Elite with an older toolchain got ~10 tok/s
for 3B and ~5 for 8B on NPU and called 3B "fluid and interactive"
([grapeup](https://grapeup.com/blog/running-llms-on-device-with-qualcomm-snapdragon-8-elite)).
The AI Hub numbers above are newer and higher; expect reality to land
between them.

### On the GPU/CPU, via Google LiteRT-LM (S26 Ultra = 8 Elite Gen 5, one gen newer)

| Model | Backend | Prefill tok/s | Decode tok/s | TTFT | RAM | Source |
|---|---|---|---|---|---|---|
| **Gemma 4 E2B** (2B effective, 32K ctx) | GPU | 3,808 | **52.1** | 0.3 s | 676 MB | [litert-community card](https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm) |
| Gemma 4 E2B | CPU | 557 | 46.9 | 1.8 s | 1,733 MB | same |

S25U will be somewhat lower (one GPU gen back) but the same class. **Note
the RAM**: under 1GB for a usable 2B model. NPU for Gemma on Qualcomm is in
Google's early-access program, not GA.

### What the numbers mean for Quintacle's actual jobs

`architecture.md`'s LLM edges are (a) narration of fetched facts, (b)
structured extraction from a dump, (c) classification, and — per the
2026-09-30 amendment — (d) embeddings.

- **1–4B class at 25–50 tok/s** is comfortably interactive for narration and
  single-entry extraction ("food: had a burrito" → schema). This is the
  sweet spot. Leaves 8+ GB for the OS and the app on a 12GB phone.
- **8B at ~15 tok/s** is usable but not snappy, eats ~5GB, and will heat the
  phone on sustained use. Feasible on 16GB, tight on 12GB. Only worth it if
  the 3–4B models fail the UC2 nightly-dump test.
- **The multi-entry journal parse (UC2)** is the one job that might exceed a
  small model — six entry types, implied dates, meal/routine matching in
  one shot. Test it before assuming. If it fails locally, that one call
  stays cloud and everything else goes on-device; that's already the
  four-tier plan.
- **Embeddings:** Google ships **EmbeddingGemma** for on-device embedding
  through the same LiteRT-LM stack, and the AI Edge Gallery app already
  does on-device semantic media search with it. **This resolves the
  "Android can't embed" constraint in the `architecture.md` amendment** —
  the phone *can* embed, just not through Python/sentence-transformers.
  Home server is no longer required for indexing; it's optional.

## The five ways in, ranked for this project

### 1. Qualcomm GenieX — the NPU path, and now a real Android SDK

- **What:** Qualcomm's multi-platform inference SDK. **Kotlin SDK on Maven
  Central**, sample app in `qualcomm/ai-hub-apps` on GitHub. Supports 8
  Elite / 8 Elite Gen 5 on Android. ([GenieX FAQ](https://geniex.aihub.qualcomm.com/en/resources/faq))
- **Two runtimes inside it:**
  - **llama.cpp** — any GGUF from Hugging Face, with NPU → GPU → CPU
    fallback. The flexible one.
  - **QAIRT (AI Engine Direct)** — precompiled AI Hub models, NPU only. The
    fast one. Models are exported via the AI Hub Python library; Llama
    exports can't be redistributed (Meta license) so you compile your own.
    Qwen3 is Apache 2.0 and avoids that.
- **Structured output:** llama.cpp supports GBNF grammars / JSON-schema
  constrained decoding. This matters — every Quintacle LLM edge is a
  Pydantic schema call today. Grammar-constrained decoding is how a 3B
  model gets reliably valid JSON.
- **Verdict:** the right primary path. NPU, Kotlin, any model, grammars.
- **Cost of entry:** a real APK with native libs (Capacitor plugin or a
  small Kotlin module). Not reachable from Termux — see below.

### 2. Google LiteRT-LM — Gemma 4 + EmbeddingGemma, GPU today, NPU soon

- **What:** Google's on-device LLM runtime (`.litertlm` models), Kotlin/C++/
  Python/Swift/JS APIs. Gemma 4 E2B/4B, EmbeddingGemma, FunctionGemma. GPU
  on Samsung today; Qualcomm NPU in early access.
- **Verdict:** the right path for **embeddings** regardless of what runs
  the LLM, and a strong LLM option if Gemma 4 E2B passes the tests —
  under 1GB RAM at 50 tok/s is hard to argue with. Fewer moving parts than
  GenieX. Lose the NPU until Google's NPU support goes GA.

### 3. ML Kit GenAI / Gemini Nano via AICore — free, zero-download, but fixed tasks

- **What:** Android system service hosting a shared Gemini Nano. The S25U
  is **confirmed supported for the feature APIs**: Summarization,
  Proofreading, Rewriting, Image Description. The open-ended **Prompt API**
  device list is split by nano version (v2 / v3 / v4); S25U is not
  explicitly listed in what I pulled — verify on the device list before
  counting on it. ([ML Kit GenAI overview](https://developers.google.com/ml-kit/genai))
- **Verdict:** useful for exactly what the names say — summarize a dropped
  article, describe a dropped photo — at zero model-management cost. Not a
  general extraction engine. Side option, not the core.

### 4. llama.cpp directly, in Termux — the test-it-tonight path

- **What:** llama.cpp builds on Android with the **Adreno OpenCL backend**
  (8 Elite / Adreno 830 verified, Q4_0 quant, use `--pure` when quantizing)
  and an **experimental Hexagon NPU backend** (v79 = 8 Elite; Q4_0/Q8_0/
  MXFP4/FP32). ([OpenCL backend](https://www.qualcomm.com/developer/blog/2024/11/introducing-new-opn-cl-gpu-backend-llama-cpp-for-qualcomm-adreno-gpu))
- **Termux reality:** CPU works. OpenCL GPU usually works (needs the vendor
  `libOpenCL.so` on the linker path). **Hexagon NPU from Termux is not
  realistic** — it needs the Hexagon SDK runtime libs and DSP access that an
  unprivileged shell doesn't get. So Termux = CPU/GPU numbers, APK = NPU.
- **Relevance:** the Android APK doc already plans a Termux-hosted FastAPI
  backend. That backend could shell out to a `llama-server` binary on
  CPU/GPU *today* with zero Kotlin. Not the end state, but a real
  intermediate.

### 5. ExecuTorch + QNN — PyTorch's path, more work, no extra benefit here

Supports SM8750, Llama 3.2 1B/3B, static-shape export, SpinQuant
calibration recommended, docs say 16GB device for the larger models. It's
a fine path if you're already a PyTorch shop; for Quintacle it's strictly
more toolchain than GenieX for the same NPU.

## How it plugs into Quintacle

The core is Python. `stack.md` already says NPU inference is "explicitly
NOT everything Python" — Python orchestrates, native runs the model. Two
concrete shapes:

**A. Capacitor plugin (end state).** The APK doc moved to Capacitor + static
frontend + Termux backend. Add one Kotlin plugin wrapping GenieX (or
LiteRT-LM) that exposes three calls to the web layer:

```
narrate(facts_json)            -> text
extract(text, json_schema)     -> json   (grammar-constrained)
embed(text)                    -> float[]
```

The frontend calls these instead of hitting the cloud route when the
"run locally" switch is on. The FastAPI backend never has to know; the
privacy switch from `deployment-and-privacy.md` becomes a frontend routing
decision. Embeddings get POSTed back to the backend to store in
`sqlite-vec`.

**B. Backend shells out (intermediate).** Termux backend runs
`llama-server` (CPU/OpenCL), the existing `llm.py` modules get a second
client that speaks llama.cpp's OpenAI-compatible endpoint. `nodes/kb/chat.py`
already has an OpenAI code path, so this is mostly a base-URL change plus
grammar/JSON-schema in the request. No NPU, but it proves the pipeline
with no native code.

Do B first to validate model quality against the use cases, then A for the
NPU and the battery.

## Battery and thermals — the honest part

- Short bursts (one drop, one narration) are negligible. 3B on NPU at 26
  tok/s for a 200-token answer is ~8 seconds of accelerator time.
- Sustained decode on 8B will throttle within minutes and visibly drain.
- The natural pattern: **interactive jobs use the 2–4B model; batch jobs
  (nightly journal parse, photo tagging, re-embedding) run on charge
  overnight**, where even 8B is fine. This is the same split the home-server
  doc already draws, just with the phone as the server.

## Open questions

- Does Gemma 4 E2B / Qwen3-4B pass UC2 (the multi-entry nightly dump) with
  grammar-constrained output? This single test decides how much of the LLM
  work goes on-device.
- Is the Prompt API (open-ended Gemini Nano) actually enabled on the S25U?
  Check the device list; if yes, it's a free fourth model with no download.
- Capacitor plugin vs. a native Kotlin module in a thin wrapper app —
  which is less friction given the frontend is static?
- 12GB vs 16GB — which S25U is it? Decides whether 8B is on the table at all.

## Do this first (no code)

1. Install **Google AI Edge Gallery** from the Play Store on the S25U.
2. Download Gemma 4 E2B and EmbeddingGemma inside it.
3. Hit the built-in **benchmark** — it reports prefill/decode tok/s and
   memory for *this* phone on CPU and GPU.
4. Paste the UC2 journal dump into its chat and ask for the entries as
   JSON. Eyeball the result.
5. Write the numbers and the verdict into this doc's table.

That's an evening, costs nothing, and replaces every "S26 Ultra" caveat
above with a real S25U number.

## Sources

- [AI Hub: Llama 3.2 3B](https://huggingface.co/qualcomm/Llama-v3.2-3B-Instruct) · [1B](https://huggingface.co/qualcomm/Llama-v3.2-1B-Instruct) · [Llama 3 8B](https://huggingface.co/qualcomm/Llama-v3-8B-Instruct) · [Qwen3-8B](https://huggingface.co/qualcomm/Qwen3-8B)
- [GenieX FAQ](https://geniex.aihub.qualcomm.com/en/resources/faq)
- [Gemma 4 E2B LiteRT-LM card](https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm)
- [LiteRT + NPU (Google blog)](https://developers.googleblog.com/en/building-real-world-on-device-ai-with-litert-and-npu/)
- [Google AI Edge Gallery](https://github.com/google-ai-edge/gallery)
- [ML Kit GenAI overview](https://developers.google.com/ml-kit/genai)
- [llama.cpp Adreno OpenCL backend (Qualcomm)](https://www.qualcomm.com/developer/blog/2024/11/introducing-new-opn-cl-gpu-backend-llama-cpp-for-qualcomm-adreno-gpu)
- [Running LLMs on 8 Elite (grapeup)](https://grapeup.com/blog/running-llms-on-device-with-qualcomm-snapdragon-8-elite)
- [8 Elite NPU claims (neowin)](https://www.neowin.net/news/qualcomm-announces-snapdragon-8-elite-flagship-smartphone-soc-with-major-improvements/) · [S25U hardware (GSMArena)](https://www.gsmarena.com/samsung_galaxy_s25_ultra-13322.php) · [8 Elite for Galaxy (Android Authority)](https://www.androidauthority.com/samsung-galaxy-s25-snapdragon-8-elite-for-galaxy-3517978)
