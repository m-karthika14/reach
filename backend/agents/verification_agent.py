"""Verification Agent - "Did the action actually achieve the goal?"

Compares the page BEFORE and AFTER the executed action and returns
{success, reason}. Runs as its own turn (after the extension re-inspects).
"""

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .schemas import VerificationResult


def _instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    return f"""You are REACH's Verification Agent.

Decide whether the executed action achieved (or clearly progressed) the user's goal.

USER GOAL:
{state.get("goal", "")}

ACTION THAT WAS EXECUTED:
{state.get("action_taken", "")}

PAGE BEFORE THE ACTION:
{state.get("before_summary", "")}

PAGE AFTER THE ACTION:
{state.get("after_summary", "")}

Judge from concrete evidence that the GOAL's outcome is now present: a URL
change, new content that belongs to the goal (e.g. for "open the bill" -> an
actual bill with amount due / due date / line items), a real confirmation
(receipt, transaction id), or the relevant control/section now being shown.

Do NOT count as success:
- a status line, toast, or log echoing that a button was clicked
  (e.g. "View Bill clicked", "Pay Bill clicked at 10:31")
- the same page with only that kind of acknowledgement text added
- the action merely having executed without the goal's content appearing

Return JSON:
- success: true only if the after-state actually shows the goal's outcome
- reason: one sentence citing the specific evidence (or what is missing)

Be conservative: if the evidence is only an "X clicked" acknowledgement or is
otherwise ambiguous, success = false.
"""


verification_agent = LlmAgent(
    name="verification_agent",
    model=MODEL,
    description="Checks whether the executed action achieved the user's goal.",
    instruction=_instruction,
    output_schema=VerificationResult,
    output_key="verification",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
