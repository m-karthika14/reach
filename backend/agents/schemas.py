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


class StructureResult(BaseModel):
    """DOM/ARIA-only understanding of the page (Phase 6, fast path)."""

    page_type: str
    summary: str
    relevant_elements: List[RelevantElement] = []
    # 0..1: how confident the DOM/ARIA alone identifies the right target.
    confidence: float
    # True when an element's meaning depends on an icon/image not in the text.
    needs_vision: bool = False
    reason: Optional[str] = None


class VisionResult(BaseModel):
    """Screenshot-based disambiguation (Phase 6, fallback path)."""

    # MUST be one of the candidate selectors handed to the Vision Agent.
    selected_selector: Optional[str] = None
    meaning: Optional[str] = None
    confidence: float
    reason: Optional[str] = None


class ReconciliationResult(BaseModel):
    """Do Structure and Vision agree about the target? (Phase 7)"""

    status: Literal["AGREE", "CONFLICT", "UNKNOWN"]
    target: Optional[str] = None
    structure_interpretation: Optional[str] = None
    vision_interpretation: Optional[str] = None
    confidence: float
    reason: Optional[str] = None


class ActionDecision(BaseModel):
    action: Literal["click", "type", "select", "scroll", "back", "none"]
    target: Optional[str] = None
    value: Optional[str] = None
    confidence: float
    done: bool = False  # goal already fully achieved on the current page
    reasoning: Optional[str] = None


class VerificationResult(BaseModel):
    """Did the user's GOAL succeed - judged from evidence (Phase 8)."""

    status: Literal[
        "VERIFIED",           # enough evidence the goal was achieved
        "FAILED",             # clear evidence it did not
        "AMBIGUOUS",          # cannot tell - no confirmation either way
        "BLOCKED",            # refused before/at execution (conflict, policy)
        "NEEDS_CONFIRMATION", # valid but consequential - awaiting approval
    ]
    success: bool             # true ONLY when status == VERIFIED
    reason: str
    evidence: List[str] = []  # concrete observations that drove the verdict
    retry_allowed: bool = False


class CorrectionDetail(BaseModel):
    """The structured content of an explicit user correction (Phase 10)."""

    selector: Optional[str] = None       # which element REACH was wrong about
    previous_label: Optional[str] = None # what REACH thought it was
    correct_label: Optional[str] = None  # what the user says it is
    strength: Literal["weak", "normal", "strong"] = "normal"


class DialogueInterpretation(BaseModel):
    """How the new user message relates to the ongoing session (Phase 5/10)."""

    intent: Literal["command", "new_goal", "reference", "correction", "smalltalk", "status_query"]
    command: Optional[
        Literal["stop", "continue", "pause", "yes", "no", "retry"]
    ] = None
    # Overall objective with pronouns/ordinals expanded (e.g. "it" -> "the electricity bill").
    resolved_goal: Optional[str] = None
    # What to do right now, references expanded (e.g. "click the 'Download Bill' button").
    resolved_request: Optional[str] = None
    # Set ONLY when intent == "correction" and the user explicitly says REACH was
    # wrong about an element ("no, that's the payment button").
    correction: Optional[CorrectionDetail] = None
    # A short, natural assistant reply for this turn.
    reply: Optional[str] = None
