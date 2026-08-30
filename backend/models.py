"""Request / response contract between the REACH extension and the backend."""

from typing import Literal, Optional

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
