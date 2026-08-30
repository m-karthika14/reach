"""Verification Agent - "Did the user's GOAL succeed?" (Phase 8)

Judges the GOAL, not the click. Reasons over extracted before/after evidence and
returns one of five states. It is deliberately conservative: no confirmation
either way -> AMBIGUOUS, never VERIFIED.

The Root Agent then applies deterministic rules on top:
  - success is forced False unless status == VERIFIED
  - retry_allowed is set by policy (AMBIGUOUS/BLOCKED/VERIFIED -> never)
"""

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .schemas import VerificationResult


def _instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    return f"""You are REACH's Verification Agent.

Decide whether the user's GOAL was achieved by the executed action. A click
"working" is NOT the goal succeeding - judge the goal.

USER GOAL:
{state.get("goal", "")}

ACTION THAT WAS EXECUTED:
{state.get("action_taken", "")}

EXTRACTED EVIDENCE (before -> after diff):
{state.get("evidence_text", "(none)")}

PAGE BEFORE:
{state.get("before_summary", "")}

PAGE AFTER:
{state.get("after_summary", "")}

Choose ONE status:

- "VERIFIED": concrete evidence the GOAL is done - the expected content/receipt/
  confirmation/URL is present. For a payment or purchase this REQUIRES a success
  message AND a transaction id / receipt; a "processing..." state is NOT enough.
- "FAILED": clear evidence it did not work - an error message, "unable to...",
  404/permission-denied, or the page is unchanged and the target still sits there
  with nothing having happened.
- "AMBIGUOUS": the page changed but there is NO confirmation of success and NO
  clear error - a spinner, "processing", a blank transition, missing receipt.
  When unsure between VERIFIED and AMBIGUOUS, choose AMBIGUOUS.

Fill:
- success: true ONLY if status is VERIFIED
- reason: one sentence
- evidence: 2-5 short bullet strings of what you actually observed (present AND
  notably absent, e.g. "no transaction id", "no success message")
- retry_allowed: your suggestion (a transient FAILED like a network error may be
  retried; a payment AMBIGUOUS must NOT). The backend enforces the final rule.
"""


verification_agent = LlmAgent(
    name="verification_agent",
    model=MODEL,
    description="Goal-level, evidence-based verification -> VERIFIED / FAILED / AMBIGUOUS.",
    instruction=_instruction,
    output_schema=VerificationResult,
    output_key="verification",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
