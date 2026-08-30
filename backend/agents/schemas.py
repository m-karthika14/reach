"""Structured outputs for the REACH ADK agents (internal to the backend).

These are the agent-to-agent contracts. The HTTP contract lives in models.py.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel


class RelevantElement(BaseModel):
    selector: str
    role: Optional[str] = None
    name: Optional[str] = None
    why: Optional[str] = None


class PerceptionResult(BaseModel):
    page_type: str
    summary: str
    relevant_elements: List[RelevantElement] = []


class ActionDecision(BaseModel):
    action: Literal["click", "type", "select", "scroll", "back", "none"]
    target: Optional[str] = None
    value: Optional[str] = None
    confidence: float
    done: bool = False  # goal already fully achieved on the current page
    reasoning: Optional[str] = None


class VerificationResult(BaseModel):
    success: bool
    reason: str


class DialogueInterpretation(BaseModel):
    """How the new user message relates to the ongoing session (Phase 5)."""

    intent: Literal["command", "new_goal", "reference", "correction", "smalltalk"]
    command: Optional[
        Literal["stop", "continue", "pause", "yes", "no"]
    ] = None
    # Overall objective with pronouns/ordinals expanded (e.g. "it" -> "the electricity bill").
    resolved_goal: Optional[str] = None
    # What to do right now, references expanded (e.g. "click the 'Download Bill' button").
    resolved_request: Optional[str] = None
    # A short, natural assistant reply for this turn.
    reply: Optional[str] = None
