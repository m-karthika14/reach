"""User preference profile - "how does THIS user want REACH to behave?" (Phase 11).

One document per user in the `preference_memory` collection, id `pref_<user_id>`.
Distinct from correction_memory ("what does this element mean") and from session
state ("what are we doing right now").
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from .store import get_store

log = logging.getLogger("reach.memory")

VERBOSITY = ("concise", "normal", "detailed")
CONFIRMATION = ("always", "risky_only", "minimal")
NAVIGATION = ("direct", "menu_first", "search_first")
LANGUAGE = ("en", "kn", "hi", "ta", "te")

DEFAULT_USER = "demo-user"


class PreferenceProfile(BaseModel):
    user_id: str = DEFAULT_USER
    language: str = "en"
    verbosity: str = "normal"
    confirmation_style: str = "risky_only"
    preferred_navigation: str = "direct"
    # kept from Phase 9/10 - an explicit "always confirm payments" toggle.
    confirmation_before_payment: bool = True
    frequently_used_sites: list[dict] = []
    updated_at: float = Field(default_factory=time.time)


_ALLOWED = {
    "language": LANGUAGE,
    "verbosity": VERBOSITY,
    "confirmation_style": CONFIRMATION,
    "preferred_navigation": NAVIGATION,
}

_LANG_ALIASES = {
    "english": "en", "kannada": "kn", "hindi": "hi", "tamil": "ta", "telugu": "te",
    "en": "en", "kn": "kn", "hi": "hi", "ta": "ta", "te": "te",
}


def _normalize(field: str, value: Any) -> Optional[Any]:
    """Reject / map arbitrary values (Step 11.11). Returns None if unusable."""
    if field == "confirmation_before_payment":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "yes", "on", "1")
    if field == "language":
        return _LANG_ALIASES.get(str(value).strip().lower())
    if field in _ALLOWED:
        v = str(value).strip().lower().replace(" ", "_")
        aliases = {"short": "concise", "brief": "concise", "long": "detailed",
                   "verbose": "detailed", "medium": "normal",
                   "menu": "menu_first", "search": "search_first"}
        v = aliases.get(v, v)
        return v if v in _ALLOWED[field] else None
    return None


class PreferenceStore:
    def __init__(self) -> None:
        self._store = get_store()

    def _doc_id(self, user_id: str) -> str:
        return "pref_" + "".join(c if c.isalnum() else "-" for c in user_id.lower())[:120]

    def get(self, user_id: str = DEFAULT_USER) -> PreferenceProfile:
        rows = self._store.query("preference_memory", {"user_id": user_id})
        if rows:
            try:
                return PreferenceProfile.model_validate({k: v for k, v in rows[0].items() if k != "_id"})
            except Exception:  # noqa: BLE001
                pass
        return PreferenceProfile(user_id=user_id)

    def patch(self, user_id: str, updates: dict[str, Any]) -> tuple[PreferenceProfile, dict]:
        prof = self.get(user_id)
        applied: dict[str, Any] = {}
        for field, raw in (updates or {}).items():
            if field not in PreferenceProfile.model_fields or field in ("user_id", "updated_at", "frequently_used_sites"):
                continue
            norm = _normalize(field, raw)
            if norm is None:
                log.warning("[PREFERENCES] rejected %s=%r (invalid)", field, raw)
                continue
            setattr(prof, field, norm)
            applied[field] = norm
        if applied:
            prof.updated_at = time.time()
            self._store.set("preference_memory", self._doc_id(user_id), prof.model_dump())
            log.info("[PREFERENCES] user=%s updated %s", user_id, applied)
        return prof, applied

    def note_site_visit(self, user_id: str, domain: str) -> None:
        if not domain or domain in ("local", "unknown"):
            return
        prof = self.get(user_id)
        sites = {s["site"]: s for s in prof.frequently_used_sites if "site" in s}
        entry = sites.get(domain, {"site": domain, "visit_count": 0})
        entry["visit_count"] += 1
        entry["last_used"] = time.time()
        sites[domain] = entry
        prof.frequently_used_sites = sorted(
            sites.values(), key=lambda s: s.get("visit_count", 0), reverse=True)[:10]
        prof.updated_at = time.time()
        self._store.set("preference_memory", self._doc_id(user_id), prof.model_dump())


_pref_store: PreferenceStore | None = None


def preference_store() -> PreferenceStore:
    global _pref_store
    if _pref_store is None:
        _pref_store = PreferenceStore()
    return _pref_store
