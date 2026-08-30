"""REACH ADK agent package (Phase 3).

Public surface used by main.py:
    run_agent(goal, url, dom, screenshot=None) -> models.AgentResponse
    run_verification(goal, before_dom, action, after_dom, after_url=None) -> dict
"""

from .root_agent import run_agent, run_verification

__all__ = ["run_agent", "run_verification"]
