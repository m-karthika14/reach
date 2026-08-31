"""REACH ADK agent package (Phase 3).

Public surface used by main.py:
    run_agent(goal, url, dom, screenshot=None) -> models.AgentResponse
    run_verification(goal, before_dom, action, after_dom, after_url=None) -> dict
"""

from .dialogue_agent import resolve_message
from .gemma_classifier import filter_candidates as gemma_filter_candidates
from .root_agent import _candidates_from_dom as candidates_from_dom
from .root_agent import run_agent, run_llm, run_verification
from .styler_agent import style_reply

__all__ = [
    "run_agent", "run_verification", "run_llm", "resolve_message", "style_reply",
    "gemma_filter_candidates", "candidates_from_dom",
]
