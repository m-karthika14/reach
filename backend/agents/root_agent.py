"""Root Agent - the orchestrator.

/agent   ->  SequentialAgent[ perception_agent -> action_agent ]  ->  AgentResponse
/verify  ->  verification_agent                                   ->  {success, reason}

The Root Agent coordinates; it does not reason about the page itself. ADK owns
the agents, their shared session state, and the execution. The Phase 2 safety
layer (gemini._normalize: allowed-action + no-invented-selector + confidence)
is re-applied to the Action Agent's output.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from google.adk.agents import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import gemini as _g
from models import AgentResponse

from .action_agent import action_agent
from .config import APP_NAME, USER_ID, ensure_project
from .perception_agent import perception_agent
from .verification_agent import verification_agent

log = logging.getLogger("reach.adk")

# ROOT AGENT: perception -> action, sharing one session state.
root_agent = SequentialAgent(
    name="reach_root_agent",
    description="REACH root orchestrator: perceive the page, then choose one action.",
    sub_agents=[perception_agent, action_agent],
)

_session_service = InMemorySessionService()


async def _run(agent, state: dict[str, Any], user_text: str, tag: str) -> dict[str, Any]:
    """Run an ADK agent once with the given initial session state; return final state."""
    ensure_project()
    session_id = uuid.uuid4().hex
    await _session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id, state=state
    )
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=_session_service)
    message = types.Content(role="user", parts=[types.Part(text=user_text)])

    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=message
    ):
        author = getattr(event, "author", None)
        if author and getattr(event, "content", None):
            log.info("[%s] %s emitted output", tag, author)

    session = await _session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    return dict(session.state) if session else {}


def _as_dict(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


async def run_agent(
    goal: str, url: str, dom: str, screenshot: Optional[str] = None
) -> AgentResponse:
    page_summary, known_selectors = _g._summarize_dom(dom)
    log.info("[ROOT] goal=%r url=%r (%d known selectors)", goal, url, len(known_selectors))

    state = {"goal": goal, "url": url, "page_summary": page_summary}

    try:
        final = await _run(root_agent, state, goal, "ACT")
    except RuntimeError:
        raise
    except Exception:
        log.exception("[ROOT] ADK pipeline failed - falling back to direct Gemini")
        return _g.ask_gemini(goal=goal, url=url, dom=dom, screenshot=screenshot)

    log.info("[PERCEPTION] %s", final.get("perception"))
    log.info("[ACTION] raw %s", final.get("action"))

    action = _as_dict(final.get("action")) or {
        "action": "none",
        "confidence": 0.0,
        "reasoning": "Action Agent produced no usable output.",
    }

    response = _g._normalize(action, known_selectors)
    log.info(
        "[ROOT] -> action=%s target=%s confidence=%.2f",
        response.action,
        response.target,
        response.confidence,
    )
    return response


async def run_verification(
    goal: str,
    before_dom: str,
    action: Any,
    after_dom: str,
    after_url: Optional[str] = None,
) -> dict[str, Any]:
    before_summary, _ = _g._summarize_dom(before_dom)
    after_summary, _ = _g._summarize_dom(after_dom)
    action_taken = action if isinstance(action, str) else json.dumps(action, default=str)

    log.info("[ROOT] verifying goal=%r after_url=%r", goal, after_url)
    state = {
        "goal": goal,
        "action_taken": action_taken,
        "before_summary": before_summary,
        "after_summary": (f"URL: {after_url}\n" if after_url else "") + after_summary,
    }

    try:
        final = await _run(verification_agent, state, goal, "VERIFY")
    except RuntimeError:
        raise
    except Exception:
        log.exception("[VERIFICATION] agent failed")
        return {"success": False, "reason": "Verification agent error."}

    result = _as_dict(final.get("verification")) or {
        "success": False,
        "reason": "Verification Agent produced no usable output.",
    }
    log.info("[VERIFICATION] -> %s", result)
    return result
