"""Action Agent - "What browser action should REACH perform next?"

Produces a single structured ActionDecision. Selector-invention and confidence
gating are enforced afterwards in root_agent via gemini._normalize (the Phase 2
safety layer, kept).
"""

import json

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .schemas import ActionDecision


def _instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    perception = state.get("perception")
    if not isinstance(perception, str):
        perception = json.dumps(perception, indent=2, default=str)

    return f"""You are REACH's Action Agent.

Decide the single safest next browser action that moves the user toward their goal.

USER GOAL:
{state.get("goal", "")}

CURRENT URL:
{state.get("url", "")}

PERCEPTION AGENT FINDINGS (JSON):
{perception}

FULL PAGE SUMMARY:
{state.get("page_summary", "")}

Allowed actions: click, type, select, scroll, back, none.
  click  - activate a button/link  -> set "target" to its selector
  type   - enter text into an input -> set "target" + "value"
  select - choose a <select> option -> set "target" + "value" (option value or label)
  scroll - scroll the page          -> no target
  back   - previous page            -> no target
  none   - uncertain or nothing safe/possible

Rules:
- "target" MUST be a selector that appears in the PAGE SUMMARY. Never invent one.
- Prefer id selectors and accessible names.
- Choose ONE step, not the whole plan.
- confidence in [0,1] = probability this action is correct AND safe.
  If unsure, return action "none" with low confidence.

Return JSON: action, target, value, confidence, reasoning.
"""


action_agent = LlmAgent(
    name="action_agent",
    model=MODEL,
    description="Chooses the single next browser action (click/type/select/scroll/back/none).",
    instruction=_instruction,
    output_schema=ActionDecision,
    output_key="action",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
