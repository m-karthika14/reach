"""Persistent memory schemas (Phase 9). Stored in Firestore db 'reach-memory'."""

from __future__ import annotations

import time
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class PageMemory(BaseModel):
    """What REACH learned about an element on a site (Step 9.1.1)."""

    domain: str
    page: str
    element: str                 # semantic label, e.g. "payment", "bill"
    selector: str
    description: str = ""         # e.g. "credit card icon"
    verified: bool = False        # only true after the Phase 8 pipeline confirmed it
    confidence: float = 0.5
    hits: int = 0                 # times it worked
    misses: int = 0              # times it failed after being trusted
    updated_at: float = Field(default_factory=time.time)


class CorrectionMemory(BaseModel):
    """A time REACH was wrong and the user corrected it (Steps 9.1.2, 10.2, 10.3)."""

    user_id: str = "demo-user"
    domain: str
    page: str = ""
    selector: str = ""           # element REACH was wrong about
    # extra signals so the same element is recognisable if the selector changes
    role: str = ""
    accessible_name: str = ""
    element_text: str = ""
    agent_prediction: str = ""   # what REACH thought it was ("account settings")
    correct_label: str = ""      # what the user says it is ("payment")
    user_said: str = ""          # the raw correction message
    strength: str = "normal"     # weak | normal | strong
    confidence: float = 0.75
    verified: bool = False       # a later action on it VERIFIED
    reason: str = "user correction"
    created_at: float = Field(default_factory=time.time)

    # kept for backwards compatibility with Phase 9 readers
    @property
    def agent_assumed(self) -> str:  # noqa: D401
        return self.agent_prediction

    @property
    def correct_element(self) -> str:
        return self.selector or self.correct_label


class PreferenceMemory(BaseModel):
    """A stable user preference (Step 9.1.3)."""

    preference: str               # e.g. "confirmation_before_payment"
    value: Any
    updated_at: float = Field(default_factory=time.time)


class TaskHistory(BaseModel):
    """A completed / failed task (Step 9.1.4)."""

    session_id: str = ""
    goal: str
    domain: str = ""
    page: str = ""
    actions: List[dict] = []
    result: str = ""             # VERIFIED | FAILED | AMBIGUOUS | BLOCKED | ...
    created_at: float = Field(default_factory=time.time)
