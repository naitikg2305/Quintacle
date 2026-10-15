# Quintacle — Vault (Node)

> **Status update 2026-10-15 — a Vault exists, but it is not this doc's
> vault.** What got built (2026-10-13, `core/quintacle_core/nodes/vault/`,
> page at `/vault`) is a **passphrase-encrypted secrets store** — scrypt KDF
> + Fernet, one `.enc` file per entry at `~/.quintacle/vault/`, a sibling of
> `kb/` so search/graph/MCP/chat/drop structurally never see it, 5-minute
> auto-lock, no recovery flow by design. See `reference/vault.md`. That
> answers this doc's "credentials/passwords" cousin (quintacle-ideas.md
> Pillar 5's digital sub-vault), **not** the encrypted-*documents* vision
> below. Passport, license, visas, lease docs etc. still live **unencrypted
> in the ordinary Documents node** — the security-first document storage this
> doc describes remains unbuilt, and whether those documents move into (or
> get a store like) the new Vault is still an open decision. They are also
> deliberately held back from MCP exposure (`mcp-angle.md`, exclusions).

## What it covers

Secure storage for critical personal documents:

- Driver's license
- Passport
- Visa documents — multiple countries
- OPT (US F-1 work authorization)
- Lease documents
- Other important docs (category open-ended)

## Why this node is different from the others

Every other node (outfits, diet, schemes, etc.) is low-stakes if leaked or lost.
This one isn't — it's identity and legal documentation. Security has to be a
first-class design constraint here, not an afterthought bolted on later:

- Encryption at rest, at minimum
- Access control matters even on a personal single-user system (e.g. what happens
  if the laptop itself is lost/stolen)
- This node should probably NOT be included if/when other nodes' folders ever get
  pushed to a git repo (echoes the same caution already noted for Grubhub work
  credentials in the separate computer-setup/knowledge-repo planning)

## Natural connection to other nodes

Documents like passports, visas, and OPT all have **expiration dates** — this is a
natural fit for the cadence/reminder machinery already being designed in
`routines.md` / `habits-and-checkin.md` (e.g. "passport expires in 6 months,
renew"), even though the document storage itself is a separate, higher-security
concern from those nodes.

## Open questions (not decided yet)

- Security model specifics (local encryption? Never leaves the device? Backup
  strategy that doesn't compromise security?)
- Whether expiration tracking/reminders live inside this node or get surfaced
  through `routines.md`'s cadence system
- Scope of "other docs" — how far this extends beyond the identity/legal documents listed
