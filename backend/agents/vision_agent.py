"""Vision Agent - screenshot-based disambiguation (Phase 6, fallback path).

Only invoked when the Structure Agent is unsure. Given the goal, the screenshot
(passed as an image part in the run message) and the list of on-page candidate
elements, it picks WHICH candidate selector is the goal's target.

It must not invent a selector - the choice is validated against the real DOM in
root_agent afterwards.
"""

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .schemas import VisionResult


def _instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    return f"""You are REACH's Vision Agent.

An image of the current page is attached. Use it to decide which on-page element
the user means, when the DOM text alone was not enough (e.g. icon-only buttons).

USER GOAL:
{state.get("goal", "")}

WHY STRUCTURE WAS UNSURE:
{state.get("structure_reason", "(not given)")}

CANDIDATE ELEMENTS - one per line as `SELECTOR   (label: "...")`:
{state.get("candidates_text", "(none)")}

Look at the screenshot. Match the goal to what the elements LOOK like (icons,
symbols, position, left-to-right order, grouping). For example a credit-card
icon = payment, a house icon = home, a person icon = profile/account.

Return JSON:
- selected_selector: copy EXACTLY one SELECTOR string from the candidate list
  (e.g. "#icon-pay") - just the selector, nothing else. null if none matches.
- meaning: what that element represents (e.g. "payment")
- confidence: 0..1 that this is the right element
- reason: one sentence citing the visual evidence
"""


vision_agent = LlmAgent(
    name="vision_agent",
    model=MODEL,
    description="Uses the screenshot to disambiguate icon/image elements the Structure Agent could not read.",
    instruction=_instruction,
    output_schema=VisionResult,
    output_key="vision",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
