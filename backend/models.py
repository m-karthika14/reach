"""Request / response contract between the REACH extension and the backend."""

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field

Action = Literal["click", "type", "select", "scroll", "back", "none"]


class AgentRequest(BaseModel):
    goal: str
    url: str
    # The extension sends JSON.stringify(pageContext). A plain description string
    # (used by the manual curl tests) is also accepted.
    dom: str
    screenshot: Optional[str] = None


class AgentResponse(BaseModel):
    action: Action
    target: Optional[str] = None
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    done: bool = False
    reasoning: Optional[str] = None
    # Phase 6 perception routing / metrics
    perception_mode: Optional[str] = None   # "structure" | "vision" | "reconciliation"
    vision_used: bool = False
    timings: Optional[dict] = None          # {structure_ms, vision_ms?, reconciliation_ms?, action_ms}
    # Phase 7 - Structure vs Vision reconciliation (present only when Vision ran)
    reconciliation: Optional[dict] = None   # {status: AGREE|CONFLICT|UNKNOWN, ...}
    # Phase 9 - memory retrieved for this decision (RAG)
    memory: Optional[dict] = None
    memory_used: bool = False
    # Phase 10 - correction-aware candidate ranking
    ranking: Optional[dict] = None
    correction_applied: bool = False


class VerifyRequest(BaseModel):
    """Sent after the extension executes an action and re-inspects the page."""

    goal: str
    action: Union[dict, str]
    before_dom: str
    after_dom: str
    after_url: Optional[str] = None


class VerifyResponse(BaseModel):
    status: Literal["VERIFIED", "FAILED", "AMBIGUOUS", "BLOCKED", "NEEDS_CONFIRMATION"]
    success: bool          # true only when status == VERIFIED
    reason: str
    evidence: List[str] = []
    retry_allowed: bool = False
    risk_level: Optional[str] = None


# --------------------------------------------------------------------------- #
# Phase 4 - browser action loop
# --------------------------------------------------------------------------- #


class LoopHistoryItem(BaseModel):
    step: int
    action: str
    target: Optional[str] = None
    value: Optional[str] = None


class LoopStepRequest(BaseModel):
    goal: str
    url: str
    dom: str
    screenshot: Optional[str] = None
    history: List[LoopHistoryItem] = []
    # The observation captured just BEFORE the most recent action, plus that
    # action - used to verify whether the goal is now met.
    prev_dom: Optional[str] = None
    last_action: Optional[dict] = None
    max_steps: int = 8


class LoopStepResponse(BaseModel):
    status: Literal[
        "running",
        "completed",
        "blocked",
        "failed",
        "ambiguous",
        "max_steps_reached",
        "repeated_action",
        "low_confidence",
        "needs_confirmation",
        "cancelled",
    ]
    done: bool
    step: int
    action: Action
    target: Optional[str] = None
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    requires_confirmation: bool = False
    reason: Optional[str] = None
    verification: Optional[dict] = None
    perception_mode: Optional[str] = None
    vision_used: bool = False
    reconciliation: Optional[dict] = None
    memory_used: bool = False


# --------------------------------------------------------------------------- #
# Phase 5 - stateful multi-turn dialogue
# --------------------------------------------------------------------------- #


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    user_id: str = "demo-user"
    message: str
    url: str
    dom: str
    screenshot: Optional[str] = None
    # Report of what the extension executed since the previous turn (Step 5.31).
    last_executed: Optional[dict] = None
    # The observation captured just before last_executed - used to verify it.
    prev_dom: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    message: str                      # assistant's natural-language reply
    status: str
    action: Optional[AgentResponse] = None   # a browser action for the extension to run
    requires_confirmation: bool = False
    candidates: List[dict] = []
    pending_confirmation: Optional[dict] = None
    verification_status: Optional[dict] = None
    reconciliation: Optional[dict] = None
    memory: Optional[dict] = None       # what RAG retrieved for this turn
    memory_used: bool = False
    memory_updated: bool = False        # this turn wrote a correction/preference
    correction: Optional[dict] = None   # {selector, correct_label, previous_label, confidence}
    ranking: Optional[dict] = None      # correction-aware ranking explanation
    preferences: Optional[dict] = None  # the active per-user preference profile
    preference_updated: Optional[dict] = None  # fields changed this turn
    current_step: int = 0


class PreferencePatch(BaseModel):
    user_id: str = "demo-user"
    language: Optional[str] = None
    verbosity: Optional[str] = None
    confirmation_style: Optional[str] = None
    preferred_navigation: Optional[str] = None
    confirmation_before_payment: Optional[bool] = None


# --------------------------------------------------------------------------- #
# Phase 13 - demo portal payments (Razorpay Test Mode)
# --------------------------------------------------------------------------- #


class CreateOrderRequest(BaseModel):
    amount: float                 # rupees
    consumer: Optional[str] = None
    note: Optional[str] = None


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: Optional[str] = None
