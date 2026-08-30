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
    """A time REACH was wrong and the user corrected it (Step 9.1.2)."""

    domain: str
    page: str = ""
    user_said: str
    agent_assumed: str = ""       # what REACH thought (label or selector)
    correct_element: str          # selector or label the user pointed to
    reason: str = "user correction"
    created_at: float = Field(default_factory=time.time)


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
