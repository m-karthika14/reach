"""Persistent multi-turn session state (Phase 5, Steps 5.3-5.13)."""

from __future__ import annotations

import time
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Turn(BaseModel):
    role: str          # "user" | "assistant"
    content: str
    ts: float = Field(default_factory=time.time)


class SessionState(BaseModel):
    session_id: str

    user_goal: str = ""                       # overall objective (references expanded)
    current_task: str = ""                    # the specific sub-task in progress
    current_step: int = 0

    current_page: Optional[dict] = None       # latest reconciled observation (trimmed)
    previous_actions: List[dict] = []         # [{action, target, value, success}]
    current_candidates: List[dict] = []       # [{name, selector, kind}]
    pending_confirmation: Optional[dict] = None   # a consequential action awaiting "yes"
    verification_status: Optional[dict] = None    # last verification (Phase 8: status/evidence/retry_allowed)
    last_verification: Optional[dict] = None       # alias kept for dialogue lookups
    perception_mode: Optional[str] = None         # "structure" | "vision" | "reconciliation"
    last_reconciliation: Optional[dict] = None     # {status, structure_interpretation, vision_interpretation, ...}

    conversation_history: List[Turn] = []

    status: str = "idle"   # idle|running|waiting_confirmation|paused|completed|cancelled|blocked

    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_doc(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "SessionState":
        return cls.model_validate(doc)
