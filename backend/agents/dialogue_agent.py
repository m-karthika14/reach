"""Dialogue Agent - interprets each new user message against the session.

Resolves pronouns ("it", "that"), ordinals ("the second one"), corrections
("actually, download it instead") and explicit commands (stop / continue /
pause / yes / no) using the conversation history, the current goal, and the
on-page candidates. Output is a typed DialogueInterpretation.
"""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import MODEL
from .root_agent import run_llm
from .schemas import DialogueInterpretation


def _instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
    return f"""You are REACH's Dialogue Agent. You do NOT act on the page. You only
interpret the user's newest message in the context of the ongoing session.

CURRENT OVERALL GOAL:
{s.get("user_goal") or "(none yet)"}

CURRENT TASK IN PROGRESS:
{s.get("current_task") or "(none)"}

ACTIONS ALREADY TAKEN:
{s.get("actions_text") or "(none)"}

ON-PAGE CANDIDATES (name -> selector), for resolving "the first/second one" etc.:
{s.get("candidates_text") or "(none)"}

PENDING CONFIRMATION (an action waiting for the user to approve):
{s.get("pending_confirmation") or "(none)"}

LAST RECONCILIATION (if a CONFLICT/UNKNOWN is pending, REACH stopped and is
waiting for the user to say which element they meant):
{s.get("last_reconciliation") or "(none)"}

LAST VERIFICATION (result of the previous action - status + evidence):
{s.get("last_verification") or "(none)"}

CONVERSATION SO FAR:
{s.get("history_text") or "(no prior turns)"}

NEW USER MESSAGE:
{s.get("message")}

Classify the new message:
- "command": stop / cancel / pause / continue / resume / no / don't. Also a BARE
  "try again" / "retry" / "do it again" / "again" with NO task named -> command
  = "retry". Also an approval of a PENDING CONFIRMATION: yes / yeah / ok / okay /
  sure / go ahead / do it / proceed / confirm / "pay" / "pay it" -> command =
  "yes". Set "command" to one of stop|continue|pause|yes|no|retry.
  A full task restatement like "pay my electricity bill" is NOT a command - it is
  "new_goal" (or "reference" if it continues the current goal), even right after
  a failure.
- "status_query": the user is asking whether the last action worked
  ("did it work?", "did it go through?", "what happened?"). Set a reply that
  answers from LAST VERIFICATION.
- "preference_update": a durable "how I want you to behave" instruction
  ("keep answers short", "be more detailed", "reply in Kannada", "always ask
  before paying", "prefer menus"). Fill "preference":
    field ∈ verbosity | language | confirmation_style | preferred_navigation | confirmation_before_payment
    value: verbosity -> concise|normal|detailed ; language -> en|kn|hi|ta|te ;
           confirmation_style -> always|risky_only|minimal ;
           preferred_navigation -> direct|menu_first|search_first ;
           confirmation_before_payment -> true|false
  This is NOT a correction and NOT a goal.
- "correction": EITHER the user is changing the plan ("actually..., do X instead"),
  OR the user says REACH was WRONG about what an element is
  ("no, that's the payment button", "that icon is profile, not settings").
  For the second kind, ALSO fill "correction":
    selector        = the element REACH was talking about. Find it from the last
                      assistant message, PENDING CONFIRMATION, the last action, or
                      the ON-PAGE CANDIDATES. null only if truly unknown.
    previous_label  = what REACH thought it was (from the conversation)
    correct_label   = the short label the user gives ("payment", "profile", ...)
    strength        = "strong" for "no, that's..." / "you're wrong" / "I already told you";
                      "weak" for "I think that might be..."; else "normal".
  Put the corrected label in resolved_request too so REACH can act on it.
- "new_goal": a fresh task unrelated to the current one.
- "reference": same goal, refers to something with a pronoun/ordinal
  ("open it", "the second one", "that button"). Expand it in resolved_request.
- "smalltalk": anything else; just set a short reply.

Rules for resolution:
- Expand "it"/"that"/"this" using the goal and recent turns. Keep the user's
  verb - "open it" means open, not download - don't invent a different action.
- If the thing the user refers to was ALREADY done per ACTIONS ALREADY TAKEN or
  the conversation, set intent="smalltalk" and a reply saying it's already done;
  leave resolved_request empty.
- Expand "the first/second/last one" using the ON-PAGE CANDIDATES list order.
- resolved_request should name a concrete thing when possible, e.g.
  "click the 'Download Bill' button (#download-bill)".
- "yes"/"ok" with a PENDING CONFIRMATION present -> command = "yes".
- If a LAST RECONCILIATION conflict is pending and the user is now naming which
  element they meant ("it's the Pay Now button", "use the green one"), set
  intent="reference" and put that element in resolved_request. REACH will still
  re-check it - naming it does not bypass the safety gate.
- Always set a short, natural "reply" (one sentence).

Return JSON: intent, command, resolved_goal, resolved_request, correction,
preference, reply.
"""


_dialogue_agent = LlmAgent(
    name="dialogue_agent",
    model=MODEL,
    description="Interprets each user message against the session (pronouns, ordinals, commands).",
    instruction=_instruction,
    output_schema=DialogueInterpretation,
    output_key="interpretation",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)


async def resolve_message(state_ctx: dict[str, Any], message: str) -> DialogueInterpretation:
    """state_ctx carries the pre-rendered session context strings."""
    state = dict(state_ctx)
    state["message"] = message
    final = await run_llm(_dialogue_agent, state, message, tag="DIALOGUE")
    raw = final.get("interpretation")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raw = None
    if isinstance(raw, dict):
        try:
            return DialogueInterpretation.model_validate(raw)
        except Exception:  # noqa: BLE001
            pass
    # Safe fallback: treat as a plain new goal.
    return DialogueInterpretation(
        intent="new_goal", resolved_goal=message, resolved_request=message,
        reply="Okay.",
    )
