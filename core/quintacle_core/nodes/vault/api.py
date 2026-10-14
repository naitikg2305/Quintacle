from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .store import (
    VaultAlreadyInitialized,
    VaultLocked,
    VaultNotInitialized,
    VaultStore,
    WrongPassphrase,
)

router = APIRouter(prefix="/vault", tags=["vault"])
_store: VaultStore | None = None


def init_store(path) -> VaultStore:
    global _store
    _store = VaultStore(path)
    return _store


def get_store() -> VaultStore:
    if _store is None:
        raise RuntimeError("vault store not initialized — call init_store() first")
    return _store


class Passphrase(BaseModel):
    passphrase: str


class VaultEntryBody(BaseModel):
    name: str
    username: str = ""
    secret: str = ""
    url: str = ""
    notes: str = ""


def _status(store: VaultStore) -> dict:
    return {
        "initialized": store.initialized(),
        "locked": store.locked(),
        "auto_lock_seconds_remaining": store.seconds_remaining(),
    }


@router.get("/status")
def status() -> dict:
    return _status(get_store())


@router.post("/init")
def init_vault(body: Passphrase) -> dict:
    store = get_store()
    if not body.passphrase:
        raise HTTPException(400, "passphrase must not be empty")
    try:
        store.init(body.passphrase)
    except VaultAlreadyInitialized:
        raise HTTPException(409, "vault is already initialized")
    return _status(store)


@router.post("/unlock")
def unlock(body: Passphrase) -> dict:
    store = get_store()
    try:
        store.unlock(body.passphrase)
    except VaultNotInitialized:
        raise HTTPException(409, "vault is not initialized yet")
    except WrongPassphrase:
        raise HTTPException(403, "wrong passphrase")
    return _status(store)


@router.post("/lock")
def lock() -> dict:
    store = get_store()
    store.lock()
    return _status(store)


@router.get("/entries")
def list_entries() -> list[dict]:
    """Names + usernames + urls only — never the secrets themselves."""
    try:
        return get_store().list()
    except VaultLocked:
        raise HTTPException(401, "vault is locked")


@router.get("/entries/{slug}")
def get_entry(slug: str) -> dict:
    """The one place a secret leaves the backend."""
    try:
        entry = get_store().get(slug)
    except VaultLocked:
        raise HTTPException(401, "vault is locked")
    if entry is None:
        raise HTTPException(404, "no such vault entry")
    return entry


@router.put("/entries/{slug}")
def put_entry(slug: str, body: VaultEntryBody) -> dict:
    try:
        entry = get_store().put(slug, body.name, body.username, body.secret, body.url, body.notes)
    except VaultLocked:
        raise HTTPException(401, "vault is locked")
    # The full entry (incl. secret) only comes back from GET-one; the write
    # response stays secret-free like the list view.
    return {k: v for k, v in entry.items() if k != "secret"}


@router.delete("/entries/{slug}")
def delete_entry(slug: str) -> dict:
    try:
        existed = get_store().delete(slug)
    except VaultLocked:
        raise HTTPException(401, "vault is locked")
    if not existed:
        raise HTTPException(404, "no such vault entry")
    return {"deleted": slug}
