"""Encrypted secrets store (passwords, API keys) — the one node whose
contents must be structurally invisible to every model-facing surface.

The whole security posture rests on one structural fact: this store's root
is `<data_dir>/vault/`, a SIBLING of `<data_dir>/kb/` — and the KB store,
the KB chat, the MCP server, full-text search, and the graph only ever walk
`kb/` (plus `graph/edges/` for the graph). Nothing here writes into kb/, the
edges folder, SQLite, or any LLM prompt; entry plaintext exists only inside
this process while the vault is unlocked, and only ever leaves through the
single GET-one-entry REST endpoint.

Crypto:
- Key derivation: scrypt (n=2**15, r=8, p=1, 32-byte key) from the user's
  passphrase + a random 16-byte salt generated once at vault creation.
- meta.json holds the salt and a verifier — the Fernet-encrypted constant
  b"quintacle-vault-check" — so a wrong passphrase fails cleanly at unlock
  instead of garbage-decrypting entries later.
- Each entry is its own Fernet-encrypted file, entries/<slug>.enc (matches
  the repo's file-per-thing pattern; lets LAN sync move entries as opaque
  bytes with per-entry last-writer-wins). Plaintext is a JSON object:
  {name, username, secret, url, notes, updated_at}.

Lock state: the derived key lives ONLY in process memory, with an expiry
timestamp refreshed on every successful vault operation (default 5 minutes).
Every operation checks expiry first and drops the key when past it.
Plaintext never touches disk — no temp files, no caching, no logging.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ... import clock
from ...markdown_paths import slugify

VERIFIER_PLAINTEXT = b"quintacle-vault-check"
AUTO_LOCK_SECONDS = 300
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LENGTH = 32


class VaultNotInitialized(Exception):
    pass


class VaultAlreadyInitialized(Exception):
    pass


class VaultLocked(Exception):
    pass


class WrongPassphrase(Exception):
    pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_LENGTH, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


class VaultStore:
    def __init__(self, root: Path, auto_lock_seconds: int = AUTO_LOCK_SECONDS):
        self.root = Path(root)
        self.entries_dir = self.root / "entries"
        self.meta_path = self.root / "meta.json"
        self.auto_lock_seconds = auto_lock_seconds
        self._key: bytes | None = None
        self._expires_at: datetime | None = None

    # --- lifecycle ---

    def initialized(self) -> bool:
        return self.meta_path.exists()

    def init(self, passphrase: str) -> None:
        """Creates salt + verifier and leaves the vault unlocked (the key was
        just derived from the passphrase the user typed — making them retype
        it immediately would be pure ceremony)."""
        if self.initialized():
            raise VaultAlreadyInitialized()
        salt = os.urandom(16)
        key = _derive_key(passphrase, salt)
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "verifier": Fernet(key).encrypt(VERIFIER_PLAINTEXT).decode("ascii"),
            "created_at": clock.now().isoformat(),
        }
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self._key = key
        self._touch()

    def unlock(self, passphrase: str) -> None:
        if not self.initialized():
            raise VaultNotInitialized()
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        key = _derive_key(passphrase, base64.b64decode(meta["salt"]))
        try:
            check = Fernet(key).decrypt(meta["verifier"].encode("ascii"))
        except InvalidToken:
            raise WrongPassphrase()
        if check != VERIFIER_PLAINTEXT:
            raise WrongPassphrase()
        self._key = key
        self._touch()

    def lock(self) -> None:
        self._key = None
        self._expires_at = None

    def locked(self) -> bool:
        self._expire_if_due()
        return self._key is None

    def seconds_remaining(self) -> int | None:
        """Whole seconds until auto-lock, or None when locked."""
        self._expire_if_due()
        if self._key is None or self._expires_at is None:
            return None
        return max(0, int((self._expires_at - clock.now()).total_seconds()))

    def _touch(self) -> None:
        self._expires_at = clock.now() + timedelta(seconds=self.auto_lock_seconds)

    def _expire_if_due(self) -> None:
        if self._key is not None and (self._expires_at is None or clock.now() >= self._expires_at):
            self.lock()

    def _require_key(self) -> bytes:
        """Expiry check first, then refresh the auto-lock window — every
        successful vault operation goes through here."""
        self._expire_if_due()
        if self._key is None:
            raise VaultLocked()
        self._touch()
        return self._key

    # --- entries ---

    def put(self, slug: str, name: str, username: str, secret: str, url: str, notes: str) -> dict:
        key = self._require_key()
        entry_slug = slugify(slug)
        payload = {
            "name": name,
            "username": username,
            "secret": secret,
            "url": url,
            "notes": notes,
            "updated_at": clock.now().isoformat(),
        }
        token = Fernet(key).encrypt(json.dumps(payload).encode("utf-8"))
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        (self.entries_dir / f"{entry_slug}.enc").write_bytes(token)
        return {"slug": entry_slug, **payload}

    def get(self, slug: str) -> dict | None:
        key = self._require_key()
        path = self.entries_dir / f"{slugify(slug)}.enc"
        if not path.exists():
            return None
        payload = json.loads(Fernet(key).decrypt(path.read_bytes()).decode("utf-8"))
        return {"slug": slugify(slug), **payload}

    def delete(self, slug: str) -> bool:
        self._require_key()
        path = self.entries_dir / f"{slugify(slug)}.enc"
        existed = path.exists()
        if existed:
            path.unlink()
        return existed

    def list(self) -> list[dict]:
        """Every entry WITHOUT its secret — names/usernames/urls only, for
        the list view. The secret only ever leaves through get()."""
        key = self._require_key()
        rows = []
        if self.entries_dir.exists():
            for path in sorted(self.entries_dir.glob("*.enc")):
                payload = json.loads(Fernet(key).decrypt(path.read_bytes()).decode("utf-8"))
                rows.append(
                    {
                        "slug": path.stem,
                        "name": payload.get("name", ""),
                        "username": payload.get("username", ""),
                        "url": payload.get("url", ""),
                        "updated_at": payload.get("updated_at", ""),
                    }
                )
        return rows
