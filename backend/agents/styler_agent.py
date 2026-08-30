"""Reply styler - applies the user's verbosity + language preference (Phase 11).

Only called when verbosity != "normal" or language != "en", so a default user
pays no extra latency. Never touches the structured action - only the
user-facing text (Step 11.16).
"""

from __future__ import annotations

import logging

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from pydantic import BaseModel

from .config import MODEL
from .root_agent import run_llm

log = logging.getLogger("reach.adk")

_LANG_NAME = {"en": "English", "kn": "Kannada", "hi": "Hindi", "ta": "Tamil", "te": "Telugu"}


class StyledReply(BaseModel):
    text: str


def _instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
    v = s.get("verbosity", "normal")
    lang = _LANG_NAME.get(s.get("language", "en"), "English")
    v_rule = {
        "concise": "Rewrite it as ONE short sentence or phrase. Drop context and pleasantries.",
        "detailed": "Rewrite it with brief helpful context (where the user is, what was found, "
                    "what will happen next). 2-3 sentences max.",
        "normal": "Keep it a natural, single sentence.",
    }.get(v, "Keep it natural.")
    return f"""Rewrite the assistant message below to match the user's style.

STYLE: verbosity = {v}. {v_rule}
LANGUAGE: reply in {lang}. Do NOT translate selectors like #view-bill.
Keep the meaning identical. Do not add new facts.

MESSAGE:
{s.get("base_reply", "")}

Return JSON: {{ "text": "<rewritten>" }}
"""


styler_agent = LlmAgent(
    name="styler_agent",
    model=MODEL,
    description="Rewrites a reply to the user's verbosity + language preference.",
    instruction=_instruction,
    output_schema=StyledReply,
    output_key="styled",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)


async def style_reply(text: str, verbosity: str = "normal", language: str = "en") -> str:
    if not text or (verbosity == "normal" and language == "en"):
        return text
    try:
        final = await run_llm(
            styler_agent,
            {"base_reply": text, "verbosity": verbosity, "language": language},
            text, tag="STYLE",
        )
        styled = final.get("styled")
        if isinstance(styled, dict) and styled.get("text"):
            return str(styled["text"]).strip()
        if isinstance(styled, str):
            import json
            try:
                return str(json.loads(styled).get("text") or text)
            except (json.JSONDecodeError, ValueError):
                return text
    except Exception:  # noqa: BLE001
        log.exception("[STYLE] failed - returning unstyled reply")
    return text
