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
- "command": stop / cancel / pause / continue / resume / yes / ok / no / don't /
  try again / retry / do it again. Set "command" to one of
  stop|continue|pause|yes|no|retry.
- "status_query": the user is asking whether the last action worked
  ("did it work?", "did it go through?", "what happened?"). Set a reply that
  answers from LAST VERIFICATION.
- "correction": the user is changing the plan ("actually...", "no, do X instead").
  Put the new objective in resolved_goal and the immediate ask in resolved_request.
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

Return JSON: intent, command, resolved_goal, resolved_request, reply.
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
