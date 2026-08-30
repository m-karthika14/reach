"""Reconciliation Agent - do Structure and Vision agree? (Phase 7)

Runs ONLY when the Vision Agent was invoked (i.e. Structure was unsure). Compares
the two independent interpretations of the same page and returns AGREE / CONFLICT
/ UNKNOWN. It does NOT act.

The Root Agent then applies a deterministic gate: anything other than AGREE means
action = none. The Action Agent is never reached on a CONFLICT/UNKNOWN.
"""

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .schemas import ReconciliationResult


def _instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
    return f"""You are REACH's Reconciliation Agent.

Two independent systems looked at the SAME page for the SAME goal:
  - Structure Agent: read the DOM / ARIA / accessible names only
  - Vision Agent: read a screenshot

Decide whether they agree about which element the goal maps to and what it means.

USER GOAL:
{s.get("goal", "")}

STRUCTURE AGENT SAID (JSON):
{s.get("structure_json", "{{}}")}

VISION AGENT SAID (JSON):
{s.get("vision_json", "{{}}")}

ON-PAGE ELEMENTS (real selectors):
{s.get("candidates_text", "(none)")}

Return one status:

- "AGREE": they point to the same element with compatible meaning, OR Structure
  was merely UNSURE / had no clear label (e.g. an icon button with aria-label
  "button") and Vision gives a confident meaning that nothing structural
  contradicts. Low structural information is NOT a conflict.

- "CONFLICT": Structure and Vision both assign a SPECIFIC meaning to the target
  and those meanings contradict each other (e.g. Structure "Cancel" vs Vision
  "Pay Now"), or they name different elements as the goal's target. When in
  doubt between AGREE and CONFLICT for a contradiction, choose CONFLICT.

- "UNKNOWN": neither system is confident enough to establish what the target is.

Also fill:
- target: the selector both refer to (or the Vision one), or null
- structure_interpretation / vision_interpretation: each side's meaning in a few words
- confidence: 0..1 in this status
- reason: one sentence.
"""


reconciliation_agent = LlmAgent(
    name="reconciliation_agent",
    model=MODEL,
    description="Compares Structure vs Vision; returns AGREE / CONFLICT / UNKNOWN.",
    instruction=_instruction,
    output_schema=ReconciliationResult,
    output_key="reconciliation",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
