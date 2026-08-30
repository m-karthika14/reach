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
