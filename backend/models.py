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


class VerifyRequest(BaseModel):
    """Sent after the extension executes an action and re-inspects the page."""

    goal: str
    action: Union[dict, str]
    before_dom: str
    after_dom: str
    after_url: Optional[str] = None


class VerifyResponse(BaseModel):
    success: bool
    reason: str


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
