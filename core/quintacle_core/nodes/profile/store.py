from __future__ import annotations

from pathlib import Path

from .models import Profile


class ProfileStore:
    """A single small JSON file — height/sex/birthdate/activity level rarely
    change, so this doesn't need the per-entry log_store machinery. Weight
    itself is NOT stored here — it's logged over time via body_stats, same
    as everything else that changes day to day."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Profile:
        if not self.path.exists():
            return Profile()
        return Profile.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, profile: Profile) -> None:
        self.path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
