# Quintacle — Self-hosting: AWS vs. a home server

Status: **idea, not started, no decision.** Parking note from a conversation
on 2026-09-29. Prompted by the MCP direction (`mcp-angle.md`): once Quintacle
is a thing models reach into, "reach into it from anywhere" becomes the
obvious next want.

Prices below are rough 2026 ballparks from memory, not quotes — re-check
before deciding. The shape of the comparison matters more than the digits.

## First, correct the mental model

"S3 buckets" don't run Quintacle. S3 is object storage; it could hold the
photo/media side (the 60GB Notebook) but the FastAPI core + SQLite +
markdown store needs a running process somewhere. On AWS that means EC2 /
Lightsail (or a container service). So the AWS option is really "a small
always-on Linux VM you rent," with S3 as optional media storage on the side.

Quintacle's actual footprint is tiny: one Python process, a SQLite file, a
folder of markdown. Megabytes of data, near-zero CPU at idle. Almost any
machine is overkill — the decision is about **where the data lives and who
else can touch the disk**, not about performance.

## Hard prerequisite either way: Quintacle has no auth

Checked `core/quintacle_core/api.py`: no auth of any kind, CORS is
`allow_origins=["*"]`. Today that's fine because it only listens on
localhost. The moment it's reachable off-box, anyone who finds it can read
the journal, finances, health stats, and location-bearing EXIF. Two ways to
handle this, and they're not equivalent:

1. **Put it on a private network (Tailscale / WireGuard) and never expose it
   publicly.** The API stays as it is — the network *is* the auth. Zero code
   changes. This is the route that fits Quintacle.
2. **Expose it publicly behind TLS + a reverse proxy + real auth.** Domain,
   certificates, login, rate limiting, and a permanent attack surface on the
   most personal data the user has. Real engineering work, permanent
   maintenance.

Option 1 works identically for AWS and for a home box. Option 2 is what
"host it on the internet" naively implies and should be avoided.

## Option A: AWS

Minimal viable setup: one small ARM instance, a small EBS volume, optional
S3 for media.

| Item | Rough monthly |
|---|---|
| EC2 `t4g.nano` / `t4g.micro` (0.5–1GB RAM, plenty) | ~$3–6 |
| or Lightsail smallest bundle (IP included) | ~$3.50–5 |
| EBS 20GB gp3 | ~$1.60 |
| Public IPv4 (AWS charges for these now) | ~$3.60 |
| S3 for ~60GB media, if migrated | ~$1.40 |
| Data transfer at this scale | ~$0 |
| **Total** | **~$8–15/mo, ~$100–180/yr** |

Plus the LLM API spend, which is the same regardless of hosting and already
exists today.

**What you get:** uptime that doesn't depend on home power or the home ISP.
Works when the home box is off, moved, or dead.

**What you give up:**
- The whole `deployment-and-privacy.md` thesis — "my data is safe, it never
  leaves the machine." The journal / dating / finance / health store sits on
  Amazon's disk. Encryption at rest helps but the operator still holds the
  keys unless client-side encryption is added, which SQLite doesn't do for
  free.
- Local inference tier. A `t4g.nano` runs FastAPI; it does not run a 7B
  model. The fully-offline "local client + local model" path from
  `mcp-angle.md` doesn't exist on this box. Every model call is cloud.
- Ongoing cost forever vs. one-time.

**Honest verdict:** technically trivial and cheap, but it's the option that
contradicts the project's stated reason for existing. Only makes sense if
"my data is safe" gets consciously demoted.

### Option A taken seriously: the all-AWS stack (2026-10-06)

The above treats AWS as "a VM you rent." This is the fuller version: what
Quintacle looks like if it lives *entirely* on AWS — app, data, media,
models, access — as a deliberate architecture rather than a fallback. It is
a real option and deserves a fair hearing, because it's the one that fully
delivers the original "no PC needed" goal from `android-apk-migration.md`:
phone works from anywhere, nothing at home has to be on, ever.

**What each piece maps to**

| Layer | Choice | Why / why not the alternatives |
|---|---|---|
| Backend | **EC2** (`t4g.small`, 2GB) running uvicorn as a systemd service | SQLite + markdown need a real filesystem and a single long-lived process. Lambda doesn't fit without replacing SQLite with DynamoDB/RDS — that's a rewrite, not a deploy. ECS Fargate works but adds a container pipeline for zero benefit at one user. |
| App data | **EBS gp3** volume, `~/.quintacle/` lives there | SQLite on EFS/NFS is a known footgun (locking). EBS is a local disk; snapshots are the backup. |
| Media | **S3** for photos/video/the Notebook; `kb/` assets could stay on EBS | $0.023/GB/mo. The code's asset paths would need an S3 backend or a mounted bucket (`mountpoint-s3`). |
| Frontend | **Static export → S3 + CloudFront**, *or* just serve it from the same EC2 | `android-apk-migration.md` already established the Next.js app is fully static-exportable. CloudFront is ~$0–1/mo at this traffic. Serving from EC2 is simpler and fine. |
| LLM | Direct Anthropic/OpenAI API **or** Bedrock (see the token-cost section below) | Cost-neutral either way. Bedrock keeps everything inside the AWS account but drops web search and batch. |
| Embeddings (future) | Local model on the instance (bge-small runs on 2GB CPU fine) or Bedrock Titan/Cohere embeddings | Local keeps note text off the model provider; Bedrock embeddings are cheap but every note goes through them. |
| Access | **Tailscale on the EC2 instance**, no public exposure | Same move as the home-server option — the instance is on your tailnet, the API stays unauthenticated-but-unreachable. No ALB, no Cognito, no TLS certs, no domain. Drop the public IPv4 entirely if you're tailnet-only (saves ~$3.60/mo). |
| Backups | EBS snapshots (daily, lifecycle-managed) + optional `restic` to S3 | Snapshots are a click to set up; restic adds encryption you hold the key to. |
| Secrets | SSM Parameter Store / Secrets Manager for API keys | Free tier covers it. Beats a `.env` on disk. |

**Rough monthly, all-in**

| Item | Monthly |
|---|---|
| EC2 `t4g.small` (2GB — enough headroom for an embedding model) | ~$12 |
| EBS 30GB gp3 + daily snapshots | ~$3–4 |
| S3, ~60GB media | ~$1.40 |
| CloudFront / static frontend | ~$0–1 |
| Public IPv4 (skip if tailnet-only) | $0–3.60 |
| Tailscale | $0 |
| LLM tokens (with retrieval, per section below) | ~$5–10 |
| **Total** | **~$20–30/mo, ~$250–350/yr** |

A `t4g.nano` instead of `small` drops ~$9/mo but can't run a local
embedding model; then embeddings go through Bedrock/Voyage/OpenAI.

**What this is genuinely best at**

- **"No PC needed," fully.** The strongest pro. Phone-only life with zero
  home infrastructure, no box to maintain, no home ISP dependency, survives
  moving apartments.
- **Zero sysadmin on hardware.** No disk to fail, no PSU, no power outage.
  Snapshots are automatic.
- **Scales without thought.** Thousands of KB entries, the 60GB Notebook,
  nightly re-embeds — none of it matters at this size.
- **One place.** App, data, models, backups, secrets under one account and
  one bill.

**What it's genuinely worst at**

- **The privacy thesis is gone, not demoted.** Journal, dating, finance,
  health, EXIF location — all on Amazon's disk, decrypted at rest by a key
  Amazon holds (KMS) unless client-side encryption is added, which SQLite
  doesn't do without SQLCipher and a key-management story. Tailscale hides
  the *network* surface; it does nothing about the disk.
- **No offline tier, ever.** No local LLM, no local vision. Every model call
  is cloud. The four-tier routing in `deployment-and-privacy.md` collapses
  to one tier.
- **Phone offline = app dead.** Unlike the home-server + local-copy plan,
  there's no on-device fallback unless the LAN-sync work gets built anyway,
  which erases most of the "simpler" argument.
- **Ongoing cost forever**, and it's 10× the Mac-mini's recurring cost.

**The honest comparison**

| | All-AWS | Home box + Tailscale |
|---|---|---|
| Works from anywhere | yes | yes (via tailnet) |
| Nothing at home must be on | **yes** | no |
| Data on your own disk | no | **yes** |
| Offline LLM / vision tier | no | **yes** (Mac mini) / vision only (Pi+Coral) |
| Recurring cost | ~$20–30/mo | ~$2–3/mo |
| Up-front cost | $0 | $0–800 |
| Sysadmin burden | low (AWS does hardware) | low-medium (you do hardware) |
| Fits `deployment-and-privacy.md` | **no** | yes |

It's a values choice, not a technical one. All-AWS wins on convenience and
"no PC needed"; home box wins on everything the project's docs say it's
*for*. Neither is wrong. Decide which sentence you'd rather be true:
"Quintacle runs no matter what's happening at home" or "Quintacle's data
has never been on a disk I don't own."

**If AWS is chosen anyway, the one non-negotiable:** tailnet-only, never a
public endpoint, and SQLCipher (or at minimum EBS encryption with a
customer-managed KMS key) before any journal data goes up. The code changes
for S3-backed assets and a client factory for Bedrock are both real work
and should be scoped before, not after, the migration.

## Option B: a home server (Mac mini or similar)

| Item | Rough cost |
|---|---|
| Mac mini M4 base (16GB / 256GB) | ~$600 one-time |
| Mac mini M4 24GB or 32GB (for bigger local models) | ~$800–1000 one-time |
| Or: a used/cheap N100 mini-PC (runs FastAPI, no inference muscle) | ~$150–200 one-time |
| Or: the existing Arch desktop, left on | $0 one-time |
| Electricity — Mac mini idles ~5–10W | ~$1–2/mo |
| Tailscale personal plan | $0 |
| Encrypted offsite backup of `~/.quintacle` to S3 / B2 / rsync.net (a few GB) | ~$0.50–1/mo |
| **Recurring total** | **~$2–3/mo** |

Break-even against AWS's ~$12/mo: roughly 3–4 years for a base Mac mini,
under a year for an N100 box, immediate for the existing desktop.

**Why the Mac mini specifically is interesting** (and not just "cheaper long
run"): 16GB+ of unified memory runs 7–8B local models comfortably; 24–32GB
runs bigger. That's the machine-local inference tier from
`deployment-and-privacy.md` made real on an always-on box instead of a
laptop that has to be open. It turns the home server into *both* the data
host *and* the offline brain — the AWS option can't be that.

**Access from anywhere:** install Tailscale on the mini, the phone, and the
laptop. All three land on a private WireGuard mesh with stable addresses.
The phone's frontend points at the mini's tailnet address instead of
`localhost:8000`; Claude Code on a laptop anywhere can reach the MCP server
over the same mesh (MCP supports remote HTTP transport, not just stdio). No
port forwarding, no public IP, no domain, no TLS setup, no auth code. From
the internet's point of view the box doesn't exist.

**What you give up:**
- Uptime is home power + home ISP. Outage at home = Quintacle unreachable
  from outside (still fine on the phone's own local copy if that sync path
  ever gets built).
- You're the sysadmin: OS updates, backups, disk. Small, but nonzero, and
  it's forever.
- Contradicts the "no PC needed" goal in `android-apk-migration.md` in
  letter, though not in spirit — a headless always-on box isn't "the laptop
  must be open." The two can coexist: phone runs standalone, syncs to the
  mini when reachable.

**Honest verdict:** this is the option consistent with everything already
written down about the project. The extra $600 buys the offline inference
tier as a side effect.

## Hardware options in detail (2026-09-29)

Three candidate classes, all ballpark prices. The dividing line is not
"can it run Quintacle" — everything here runs the core without noticing.
The line is **what else the box can be**: just the data host, a vision
accelerator, or the offline LLM brain.

### Raspberry Pi 5 + Coral TPU (done before, known quantity)

| Part | Rough cost |
|---|---|
| Pi 5, 8GB | ~$80 |
| Pi 5, 16GB | ~$120 |
| PSU, case, NVMe HAT + small SSD (don't run the store off SD) | ~$40–60 |
| Coral USB Accelerator (if still findable — supply has been flaky) | ~$60 |
| or Coral M.2 on the Pi's PCIe via an M.2 HAT | ~$25–40 + HAT |
| or Hailo-8L "AI HAT+" (13 TOPS, the official Pi AI kit) | ~$70 |
| Power draw | ~3–8W, under $1/mo |
| **Total** | **~$180–250** |

**What it does well:** hosts FastAPI + SQLite + markdown + Tailscale +
backups without breaking a sweat. And the Coral is a *perfect* fit for one
specific node: the media-analysis tier in `deployment-and-privacy.md`. Coral
runs int8 TFLite models — YOLO-class object detection, face detection, the
exact models already planned for "who/what is in frame" tagging at ingest
time. Nightly batch over the day's photos on a Pi + Coral is the intended
architecture, just on an always-on box instead of the laptop.

**What it can't do:** LLMs. The Coral is an int8 vision accelerator with 8MB
of on-chip memory; it has nothing to do with transformer inference. Pi 5 CPU
alone runs 1–3B models at a few tokens/s and a 7B at ~1–2 tokens/s, which is
"technically works, practically no." The Hailo-8L can run some tiny LLMs
but it's also really a vision chip. So: **Pi = data host + vision
accelerator, not the brain.**

**Known pain, from having done it:** Coral's software stack is stale —
`pycoral` pins old Python/TensorFlow versions, Google's maintenance has been
minimal for years. Budget for a venv with a pinned old Python or a container.
Hailo's stack is more current if the Coral pain isn't worth repeating.

**Verdict:** the cheapest box that gives Quintacle a *second* capability
(local vision) rather than just hosting. Best value if the photo-tagging
node is going to be built and the LLM tier stays cloud/laptop.

### Intel N100 mini-PC (Beelink Mini S12 Pro, GMKtec NucBox G3, Trigkey G4)

| Part | Rough cost |
|---|---|
| Whole unit, 16GB DDR5, 500GB NVMe, 2.5GbE + WiFi, ships with Windows (wipe it) | ~$130–200 |
| Power draw | ~6W idle, ~15W peak, ~$1/mo |

**What it does well:** everything the Pi does, faster, with a real x86
Linux install (Arch/Debian, no ARM wheel issues), replaceable RAM, and
2.5GbE for bulk-syncing photos or the 60GB Notebook. Near-silent. The
"boring Linux box" option.

**What it can't do:** LLMs, same as the Pi but for a different reason —
weak iGPU, slow single-channel memory, 4 small cores. An 8B model crawls at
a few tokens/s on CPU. No accelerator slot worth using (one M.2 for the SSD).
Also no Coral-style vision path unless you add a USB Coral, at which point
the Pi is cheaper for the same result.

**Verdict:** the most *convenient* data host — plain Linux, zero ARM
friction — but adds no second capability. Pick this over the Pi if the
vision node isn't happening soon and you just want a reliable server.

### Mac mini M4 — the only option that's also the offline brain

Apple Silicon's unified memory (shared CPU/GPU, high bandwidth) is why this
runs LLMs and the other two don't. Same "16GB" number, completely different
outcome.

| Config | Memory | Comfortable models (4-bit quant) | Rough speed | Price |
|---|---|---|---|---|
| Base | 16GB | 7–8B: Llama 3.1 8B, Qwen 2.5 7B, Mistral 7B | ~20–30 tok/s | ~$600 |
| Mid | 24GB | 14B, or 8B at higher precision with headroom | ~10–15 tok/s for 14B | ~$800 |
| Top | 32GB | 32B (e.g. Qwen 2.5 32B) | ~8–12 tok/s | ~$1000 |
| M4 Pro | 24–64GB | 70B at 4-bit on 64GB | ~5–8 tok/s for 70B | ~$1400+ |

Speeds are rough; the Pro's higher memory bandwidth helps noticeably even
at the same model size.

**16GB caveat:** macOS takes 3–5GB. An 8B at 4-bit needs ~5GB plus context.
Fine for 8B + Quintacle + a browser; 14B on 16GB gets tight and swaps. **If
the box is meant to be the brain and not just the host, 24GB is the
comfortable floor** — worth the extra ~$200.

**Tooling:** Ollama (one command, uses Metal automatically) or LM Studio.
Both expose an OpenAI-compatible HTTP endpoint — and `nodes/kb/chat.py`
already has an OpenAI code path, so pointing Quintacle at the mini's Ollama
over the tailnet is a base-URL change, not a rewrite.

**What a 7–8B local model is actually good for here:**
- The narration edge ("what was I doing on the 13th" → prose). Easy job;
  `architecture.md` already says a small local model is enough, and it's
  right.
- Simple structured extraction ("food: had a burrito" → schema).
- Driving a local MCP client for read queries against the store.

**Where it falls short of Haiku/Sonnet:** messy multi-entry journal dumps
with implied dates, ambiguous classification, multi-step tool chains that
need real reasoning. The four-tier routing already anticipates this: local
first, cloud when the task exceeds it.

**Verdict:** the only option consistent with *all* of the deployment doc —
data host, vision (via CPU/GPU, no Coral needed), *and* the offline LLM
tier on one always-on box. Costs 3–5× the others.

### Summary

| | Pi 5 + Coral | N100 | Mac mini 16GB | Mac mini 24GB |
|---|---|---|---|---|
| Hosts Quintacle core | yes | yes | yes | yes |
| Local vision (YOLO/faces) | yes, via Coral | CPU only, slow | yes, GPU | yes, GPU |
| Local 8B LLM | no | no | yes | yes |
| Local 14B+ LLM | no | no | tight | yes |
| Linux friction | ARM, Coral stack pain | none | macOS, not Linux | macOS |
| Cost | ~$200 | ~$170 | ~$600 | ~$800 |
| Power | ~5W | ~8W | ~5–10W | ~5–10W |

**Decision heuristic:** if the LLM tier stays cloud + laptop-GPU, the Pi (if
vision matters) or N100 (if not) is the answer and the Mac mini is wasted
money. If "fully offline including the brain" is a real goal rather than a
nice phrase, only the Mac mini delivers it, and 24GB is the one to buy.
And the existing Arch desktop is still the free way to test whether the
always-on pattern gets used before buying anything.

## The hybrid that actually uses S3 sensibly

Home server as the source of truth + **encrypted** nightly backup of
`~/.quintacle/` to S3 (or B2, which is cheaper). S3 never sees plaintext,
costs cents, and covers the "house burns down" case that home hosting
otherwise doesn't. This is the one role where a bucket fits the privacy
thesis.

## LLM token costs and the Bedrock question (2026-10-06)

Hosting and tokens are two unrelated bills. Hosting (Option A above) is
small and fixed. Tokens depend entirely on how the KB chat is grounded —
and today that's the whole story.

### What Quintacle actually spends

Defaults: Haiku 4.5 for routine parsing (`DEFAULT_MODEL`), Sonnet 5 for
chat (`RESEARCH_MODEL`). First-party rates at time of writing:

| Model | Input $/1M | Output $/1M |
|---|---|---|
| Haiku 4.5 | $1 | $5 |
| Sonnet 5 | $2 | $10 |

Estimated from the call patterns in the code:

| Workload | Assumption | Monthly |
|---|---|---|
| Nightly journal parse | one Haiku call + two small resolution calls/day | ~$0.50 |
| Drops | ~10/day, some with images, Haiku | ~$1 |
| KB chat **as built today** | 10 msgs/day on Sonnet 5, whole KB stuffed | **~$60** |
| KB chat **with top-k retrieval** | same volume, ~5K tokens context/msg | ~$3 |

The chat row is the only one that matters. `_kb_context()` concatenates the
entire KB into every message — at 44 files that's ~100K tokens, ~$0.20 per
message. At thousands of entries it stops being expensive and becomes
impossible (see the `architecture.md` 2026-09-30 amendment — same
conclusion from the other direction). Everything else is pocket change.

**Realistic all-in:** ~$12–20/mo (hosting + tokens) once retrieval exists;
$70+/mo if the chat stays as-is and gets daily use. Prompt caching on the
stable system prefix shaves more. Provider choice is a rounding error next
to fixing the grounding.

### Bedrock: not cheaper, and it costs features

Question asked: does routing both Anthropic *and* OpenAI models through
Bedrock beat separate API billing? **No.**

- Bedrock is a reseller. For Claude it has historically charged Anthropic's
  list price — no undercut, no personal-account volume bundle. Two
  providers on one bill is the same money as two providers on two bills.
  Where AWS differs it's upward (cross-region inference profiles,
  provisioned throughput), not downward.
- Confirmed 2026-10-06 from the Bedrock model catalog: proprietary OpenAI
  models *are* on Bedrock now (GPT-5.4, 5.5, 5.6 variants, GPT-6 variants,
  plus gpt-oss). But the models in Quintacle's chat picker today —
  `gpt-4o-mini`, `gpt-5-nano`, `gpt-5-mini` — are **not** in that list. A
  switch means picking different OpenAI models, not repointing.
- Could not pull per-token Bedrock prices for the GPT models (the AWS
  pricing page renders dynamically; fetch returned only legacy rows). Check
  https://aws.amazon.com/bedrock/pricing/ directly before deciding.

**What Bedrock would give:** one invoice, IAM creds instead of API keys, no
Anthropic/OpenAI accounts, data stays inside the AWS account/region, one
request shape across providers.

**What it would take away, specific to this codebase:**

- **Web search in the chat.** Both the Anthropic and OpenAI paths in
  `nodes/kb/chat.py` use the provider's server-side web search tool.
  Bedrock doesn't offer Anthropic's web search; the OpenAI Responses API
  tools aren't the Bedrock surface either. Feature goes away or gets
  rebuilt on a third-party search.
- **Batch pricing.** Anthropic's direct API runs batches at 50% off.
  Bedrock has no batch mode for Claude. Unused today; it's the obvious
  lever for nightly re-embedding / bulk reprocessing later.
- **A refactor.** 35 direct `anthropic.Anthropic()` constructions across the
  nodes plus 2 OpenAI ones. All need to go through a factory in
  `llm_config.py` (Bedrock Mantle client, `anthropic.`-prefixed model IDs)
  before any of this works.

**Middle option worth knowing:** *Claude Platform on AWS* is
Anthropic-operated, bills through AWS, full first-party feature parity
including web search. If the goal is "pay through AWS" rather than "use
Bedrock specifically," that avoids the feature gaps.

**Verdict:** if the appeal is one bill and AWS-resident data, Bedrock is
fine and roughly cost-neutral. If the appeal is saving money, it won't —
the chat's grounding is where the money is. Hosting location and model
provider are separate decisions; the token bill is identical on a Mac mini
or an EC2 instance.

## Open questions

- Is "reachable from anywhere" actually needed, or is the phone-local +
  LAN-sync plan in `deployment-and-privacy.md` enough once built? Tailscale
  makes the difference nearly free, so probably just do it, but it's a
  choice.
- Existing desktop as the server for now (free, tests the whole idea) vs.
  buying hardware before knowing if the always-on pattern sticks?
- Does the remote-MCP transport need any auth of its own on the tailnet, or
  is "only my devices are on the mesh" sufficient? Lean: sufficient for v1.
- Backup encryption: `age` / `restic` (built-in encryption, dedup, S3/B2
  backends) — restic is the obvious fit.

## Next step

None scheduled. If/when this gets picked up: start with Tailscale on the
existing desktop + phone, point the phone's frontend at the tailnet address,
and see whether "from anywhere" is used enough to justify dedicated hardware.
Decide hardware after, not before.
