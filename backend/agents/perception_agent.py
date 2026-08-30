"""Perception Agent - "What is currently on the web page?"

Does NOT choose or perform actions. Reads the page context the extension
captured and returns a typed PerceptionResult (page_type + relevant_elements).
"""

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .schemas import PerceptionResult


def _instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    return f"""You are REACH's Perception Agent.

Your ONLY job is to describe what is on the current web page and which elements
matter for the user's goal. You do NOT click, type, or decide actions.

USER GOAL (for relevance ranking only):
{state.get("goal", "")}

CURRENT URL:
{state.get("url", "")}

PAGE SUMMARY (buttons / links / inputs with selectors + accessible names, then visible text):
{state.get("page_summary", "")}

Return JSON with:
- page_type: short label, e.g. "billing", "login", "form", "dashboard", "unknown"
- summary: one sentence describing the page
- relevant_elements: up to 6 elements most relevant to the goal. Each has
  selector, role, name, why. Use ONLY selectors that appear in the page summary.
  If nothing is relevant, return an empty list.
"""


perception_agent = LlmAgent(
    name="perception_agent",
    model=MODEL,
    description="Analyzes the current page and extracts goal-relevant elements.",
    instruction=_instruction,
    output_schema=PerceptionResult,
    output_key="perception",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
