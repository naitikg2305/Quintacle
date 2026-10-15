# The Vault — encrypted secrets store

Derived from code at commit `884d057` on 2026-10-15.

Code: [core/quintacle_core/nodes/vault/store.py](../../core/quintacle_core/nodes/vault/store.py)
(crypto + lock lifecycle) and
[nodes/vault/api.py](../../core/quintacle_core/nodes/vault/api.py) (REST).
Frontend: `frontend/app/vault/page.tsx`.

One scope note up front: this is a **secrets** store — passwords, API keys
(`{name, username, secret, url, notes}`). It is *not* the encrypted
document vault `docs/vault.md` originally planned (passports/licenses):
those live in the Documents node under `kb/`, unencrypted and
model-visible — a known, explicitly-flagged gap (`docs/mcp-angle.md`,
"documents that are vault-shaped — held back").

## Crypto, exactly as implemented

- **Key derivation**: scrypt over the passphrase — `n=2**15` (32768),
  `r=8`, `p=1`, 32-byte output — with a random 16-byte salt
  (`os.urandom(16)`) generated once at `init()`. The derived key is
  urlsafe-base64 encoded to make a Fernet key
  (`cryptography==50.0.2`'s `Scrypt` + `Fernet`).
- **`vault/meta.json`** holds exactly: `salt` (base64), `verifier` — the
  Fernet encryption of the constant `b"quintacle-vault-check"` — and
  `created_at`. On unlock, the key is re-derived and the verifier
  decrypted: an `InvalidToken` (or wrong plaintext) raises
  `WrongPassphrase`, so a bad passphrase fails cleanly instead of
  garbage-decrypting entries later.
- **Per-entry encryption**: each entry is its own Fernet token at
  `vault/entries/<slugified-slug>.enc`. Plaintext is one JSON object:
  `{name, username, secret, url, notes, updated_at}` (updated_at = Eastern
  `clock.now()`). File-per-entry matches the repo's file-per-thing pattern
  and lets LAN sync move entries as opaque bytes with per-entry
  last-writer-wins (the `vault/` tree is NOT in sync's exclusion list, so
  ciphertext syncs like any other file).

There is no re-keying/passphrase-change mechanism, and no key file on disk
— losing the passphrase loses the entries.

## Lock lifecycle

- The derived key lives **only in process memory**
  (`VaultStore._key`), with an expiry timestamp.
- **Auto-lock**: `AUTO_LOCK_SECONDS = 300`. `_touch()` resets
  `_expires_at = now + 300 s`; `_expire_if_due()` drops the key the first
  time any operation runs past expiry.
- **Refresh-on-op**: every successful operation goes through
  `_require_key()` — expiry check first, then refresh — so active use keeps
  the vault open and 5 idle minutes close it. `locked()` and
  `seconds_remaining()` also trigger the expiry check (so even a status
  poll enforces it).
- `init()` leaves the vault unlocked (the key was just derived from the
  passphrase the user typed); `lock()` zeroes key + expiry immediately.
- Plaintext never touches disk: no temp files, no caching, no logging.

## API surface

Eight routes under `/vault` (full table in [endpoints.md](endpoints.md)):
`status`, `init` (409 if already initialized), `unlock` (403 wrong
passphrase), `lock`, list entries, get one entry, put entry, delete entry.
Error mapping: `VaultLocked` → 401 on every entry operation.

Secret-exposure discipline, enforced per endpoint:
- `GET /vault/entries` returns summaries only — slug/name/username/url/
  updated_at, never `secret` (`VaultStore.list()` builds rows without it).
- `PUT /vault/entries/{slug}`'s response strips `secret` too.
- **`GET /vault/entries/{slug}` is the single place a secret leaves the
  backend**, and only while unlocked.

## Why every model-facing surface structurally cannot see the vault

The security posture rests on one structural fact, stated in both
`store.py`'s docstring and `api.py`'s wiring comment: the vault root is
`<data_dir>/vault/`, a **sibling** of `<data_dir>/kb/`
(`init_vault_store(DATA_DIR / "vault")` in `create_app()`), and every
surface a model can reach only ever walks `kb/` (plus `graph/edges/` and
`journal/`). Per surface:

| Surface | Why it can't reach vault/ |
|---|---|
| KB search (`/kb/search`, MCP `kb_search_entries`) | `KBStore.search()` iterates `list_folders()` = `list_folder_tree(self.root)` where root is `kb/` — a directory walk that never leaves it |
| KB chat (`/kb/chat`) | `_kb_context`/`_kb_context_for_folder` read entries through the same KBStore; the prompt is built exclusively from `kb/` contents |
| KB asset reads | `KBStore._clamped_asset_path` resolves and **requires the result to stay under the KB root** — a crafted `../../vault/...` path 404s (`a3f34c2` fixed exactly this) |
| Graph (`/graph`, `/kb/graph`, edge engine) | Nodes come from KBStore/JournalStore/ExperienceStore/SQLite; edges from `graph/edges/`. Nothing enumerates `vault/`, and vault entries have no node id scheme |
| Drop (`/drop`, `/kb/drop`, `/kb/batch-drop`) | Classification sees only the uploaded bytes + text; commits write into `kb/`, journal, or SQLite |
| MCP server | `server.init()` constructs KBStore/JournalStore/TodoStore/LogFileStore/LogsRepository — no vault store exists in that process at all, and no tool takes a raw filesystem path |
| LLM prompts generally | No call site reads `DATA_DIR` directly for content; all content flows through the stores above |

Within the backend process, vault plaintext exists only transiently inside
`VaultStore` methods while unlocked, and it is never passed to any LLM
helper, never written into `kb/`, the edges folder, SQLite, or the ledger.

What this does NOT defend against (honest limits, same trust model as the
rest of the app): anything on the same machine can call
`GET /vault/entries/{slug}` while the vault is unlocked — there is no auth
on the REST API; and ciphertext-at-rest is only as strong as the
passphrase (scrypt 2^15 slows brute force, doesn't prevent it).
