"""Gemini service for REACH (Phase 2).

Reuses the exact configuration proven to work in test_gemini.py:
    vertexai + GenerativeModel("gemini-3.5-flash"), location asia-south1,
    project from the GOOGLE_CLOUD_PROJECT env var.

Given a goal + current page, returns a single structured browser action.
No ADK / memory / RAG / vision yet - that is Phase 3+.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from models import AgentResponse

LOCATION = "asia-south1"
MODEL_NAME = "gemini-3.5-flash"

CONFIDENCE_FLOOR = 0.0

SYSTEM_INSTRUCTION = """You are the REACH browser agent.

Your job is to determine the safest next browser action that helps achieve the
user's goal.

You receive:
- the user's goal
- the current URL
- a summary of the current webpage (buttons, links, inputs with their selectors
  and accessible names, plus visible text)
- optionally a screenshot

Return ONLY structured action data. Do not chat.

Allowed actions:
  click   - activate a button or link (set "target" to its selector)
  type    - enter text into an input (set "target" to its selector, "value" to the text)
  select  - choose an option in a <select> (set "target" to its selector, "value" to the option)
  scroll  - scroll the page (no target needed)
  back    - go back to the previous page (no target needed)
  none    - do nothing (use when uncertain or when no action is safe/possible)

Rules:
- Never invent an element that is not present in the supplied page summary.
- "target" MUST be one of the selectors listed in the page summary.
- Prefer stable id selectors (e.g. "#view-bill") and accessible names.
- Pick the single best next step, not the whole plan.
- If you are not confident, return {"action": "none"} with a low confidence.
- confidence is your probability (0..1) that this action is correct and safe.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["click", "type", "select", "scroll", "back", "none"],
        },
        "target": {"type": "string", "nullable": True},
        "value": {"type": "string", "nullable": True},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["action", "confidence"],
}

_model: Optional[GenerativeModel] = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT is not set. "
                "Run:  $env:GOOGLE_CLOUD_PROJECT = 'reach-agent-507107'"
            )
        vertexai.init(project=project, location=LOCATION)
        _model = GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_INSTRUCTION)
    return _model


# --------------------------------------------------------------------------- #
# Page summarisation
# --------------------------------------------------------------------------- #

MAX_ELEMENTS = 40
MAX_TEXT_CHARS = 4000


def _summarize_dom(dom: str) -> tuple[str, set[str]]:
    """Turn the extension's page JSON into a compact text summary.

    Returns (summary_text, known_selectors). If `dom` is not JSON it is passed
    through (truncated) and known_selectors is empty (target check is skipped).
    """
    try:
        page = json.loads(dom)
    except (json.JSONDecodeError, TypeError):
        return dom[:MAX_TEXT_CHARS], set()

    if not isinstance(page, dict):
        return str(page)[:MAX_TEXT_CHARS], set()

    known: set[str] = set()
    lines: list[str] = []

    title = page.get("title")
    if title:
        lines.append(f"Title: {title}")

    def add(prefix: str, items: Any, fields: tuple[str, ...]) -> None:
        if not isinstance(items, list):
            return
        lines.append(f"\n{prefix} ({len(items)}):")
        for el in items[:MAX_ELEMENTS]:
            if not isinstance(el, dict):
                continue
            sel = el.get("selector") or (f"#{el['id']}" if el.get("id") else None)
            if sel:
                known.add(sel)
            if el.get("id"):
                known.add(f"#{el['id']}")
            parts = []
            for f in fields:
                v = el.get(f)
                if v not in (None, "", [], {}):
                    parts.append(f"{f}={v!r}")
            if sel:
                parts.append(f"selector={sel!r}")
            lines.append("  - " + ", ".join(parts))

    add("Buttons", page.get("buttons"), ("text", "accessibleName", "ariaLabel", "disabled"))
    add("Links", page.get("links"), ("text", "accessibleName", "href"))
    add(
        "Inputs",
        page.get("inputs"),
        ("tag", "type", "name", "placeholder", "accessibleName", "value", "options"),
    )

    text = page.get("visibleText")
    if isinstance(text, str) and text.strip():
        lines.append("\nVisible text:\n" + text.strip()[:MAX_TEXT_CHARS])

    return "\n".join(lines), known


def _build_prompt(goal: str, url: str, dom_summary: str) -> str:
    return (
        f"USER GOAL:\n{goal}\n\n"
        f"CURRENT URL:\n{url}\n\n"
        f"PAGE SUMMARY:\n{dom_summary}\n\n"
        "Respond with the single best next action as JSON."
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

_ELEMENT_ACTIONS = {"click", "type", "select"}


def ask_gemini(
    goal: str,
    url: str,
    dom: str,
    screenshot: Optional[str] = None,  # accepted, not used yet (Phase 6)
) -> AgentResponse:
    dom_summary, known_selectors = _summarize_dom(dom)
    prompt = _build_prompt(goal, url, dom_summary)

    model = _get_model()
    response = model.generate_content(
        prompt,
        generation_config=GenerationConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )

    try:
        data = json.loads(response.text)
    except (json.JSONDecodeError, ValueError, AttributeError):
        return AgentResponse(
            action="none",
            confidence=0.0,
            reasoning="Model did not return valid JSON.",
        )

    return _normalize(data, known_selectors)


def _normalize(data: dict[str, Any], known_selectors: set[str]) -> AgentResponse:
    action = str(data.get("action", "none")).lower()
    if action not in {"click", "type", "select", "scroll", "back", "none"}:
        action = "none"

    target = data.get("target") or None
    value = data.get("value")
    value = str(value) if value is not None else None

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reasoning = data.get("reasoning")
    reasoning = str(reasoning) if reasoning is not None else None

    done = bool(data.get("done", False))

    # Guardrail: element actions need a target that actually exists on the page.
    if action in _ELEMENT_ACTIONS:
        if not target:
            return AgentResponse(
                action="none",
                confidence=0.0,
                reasoning=f"Model chose '{action}' without a target.",
            )
        if known_selectors and target not in known_selectors:
            return AgentResponse(
                action="none",
                confidence=0.0,
                target=target,
                reasoning=(
                    f"Model targeted '{target}', which is not present on the page. "
                    "Refusing to act on an invented element."
                ),
            )

    return AgentResponse(
        action=action,
        target=target,
        value=value,
        confidence=confidence,
        done=done,
        reasoning=reasoning,
    )
