"""Request / response contract between the REACH extension and the backend."""

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    goal: str
    url: str
    # The extension sends JSON.stringify(pageContext). A plain description string
    # (used by the manual curl tests) is also accepted.
    dom: str
    screenshot: Optional[str] = None


class AgentResponse(BaseModel):
    action: Literal[
        "click",
        "type",
        "select",
        "scroll",
        "back",
        "none",
    ]
    target: Optional[str] = None
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
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
