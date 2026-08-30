"""Structure Agent - DOM/ARIA-only page understanding (Phase 6, fast path).

Replaces the old single Perception Agent. Same job (find goal-relevant
elements) PLUS a self-assessed `confidence` and a `needs_vision` flag that the
Root Agent uses to decide whether to fall back to the Vision Agent.
"""

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .schemas import StructureResult


def _instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    return f"""You are REACH's Structure Agent.

You understand the page from its DOM / ARIA / accessible names ONLY. You never
see a screenshot. You do NOT choose or perform actions.

USER GOAL:
{state.get("goal", "")}

CURRENT URL:
{state.get("url", "")}

PAGE SUMMARY (buttons / links / inputs with selectors + accessible names, then visible text):
{state.get("page_summary", "")}

Return JSON:
- page_type: short label ("billing", "login", "form", "dashboard", "unknown", ...)
- summary: one sentence describing the page
- relevant_elements: up to 6 elements most relevant to the goal, each with
  selector, role, name, why. Use ONLY selectors that appear in the page summary.
- confidence: 0..1 - how sure you are that the DOM/ARIA text alone identifies
  the CORRECT element for the goal.
    high (>=0.85): a clear text/aria label matches the goal
      (e.g. goal "open bill", button labelled "View Bill")
    low  (<0.6):  the likely target is an icon/image button with a generic or
      missing label (e.g. aria-label="button", text is just an emoji), or
      several elements look equally plausible
- needs_vision: true when the meaning of the best candidate depends on how it
  LOOKS (an icon, an image, a color) rather than its text/ARIA.
- reason: one sentence explaining the confidence.
"""


structure_agent = LlmAgent(
    name="structure_agent",
    model=MODEL,
    description="DOM/ARIA-only page understanding with a confidence + needs_vision flag.",
    instruction=_instruction,
    output_schema=StructureResult,
    output_key="structure",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
