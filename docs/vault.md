# Quintacle — Vault (Node)

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
