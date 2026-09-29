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
