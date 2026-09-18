from __future__ import annotations

from fastapi import APIRouter

from ..logs.api import get_repo as get_logs_repo
from .models import Profile
from .store import ProfileStore
from .targets import LB_TO_KG, compute_targets

router = APIRouter(prefix="/profile", tags=["profile"])
_store: ProfileStore | None = None


def init_store(path) -> ProfileStore:
    global _store
    _store = ProfileStore(path)
    return _store


def get_store() -> ProfileStore:
    if _store is None:
        raise RuntimeError("profile store not initialized — call init_store() first")
    return _store


@router.get("")
def get_profile() -> Profile:
    return get_store().load()


@router.put("")
def update_profile(body: Profile) -> Profile:
    get_store().save(body)
    return body


@router.get("/targets")
def get_targets() -> dict:
    """Personalized kcal/protein targets from height/sex/age + your most
    recently logged weight — never a fixed guess, always the real math."""
    weight_row = get_logs_repo().latest_body_stat("weight")
    if weight_row is None:
        return {"error": "no weight logged yet — log a body_stat entry first"}

    weight = weight_row["value"]
    unit = weight_row["unit"] or "lb"
    weight_kg = weight * LB_TO_KG if unit == "lb" else weight

    targets = compute_targets(get_store().load(), weight_kg)
    if targets is None:
        return {"error": "profile incomplete — set height, sex, and birthdate first"}
    return targets
