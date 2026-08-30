"""Root Agent - the orchestrator (Phase 6: Structure + Vision routing).

run_agent:
    STRUCTURE (DOM/ARIA only)
        |
        confidence >= 0.85 and not needs_vision  -->  ACTION
        else, if a screenshot is available       -->  VISION  -->  ACTION
        else                                     -->  ACTION (structure only)
        |
    gemini._normalize  (allowed action + no invented selector + confidence)

run_verification: unchanged (Phase 3).

ADK owns the agents and their session state; this module owns the routing,
the logging, and the timing/vision-usage metrics.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from typing import Any, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import gemini as _g
from models import AgentResponse

from .action_agent import action_agent
from .config import APP_NAME, USER_ID, ensure_project
from .reconciliation_agent import reconciliation_agent
from .structure_agent import structure_agent
from .verification_agent import verification_agent
from .vision_agent import vision_agent

log = logging.getLogger("reach.adk")

VISION_CONFIDENCE_THRESHOLD = 0.85

_session_service = InMemorySessionService()


async def _run(
    agent,
    state: dict[str, Any],
    user_text: str,
    tag: str,
    image_bytes: Optional[bytes] = None,
) -> dict[str, Any]:
    """Run an ADK agent once with the given initial state; return final state."""
    ensure_project()
    session_id = uuid.uuid4().hex
    await _session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id, state=state
    )
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=_session_service)

    parts = [types.Part(text=user_text)]
    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
    message = types.Content(role="user", parts=parts)

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


async def run_llm(agent, state: dict, user_text: str, tag: str = "LLM") -> dict:
    return await _run(agent, state, user_text, tag)


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


def _decode_screenshot(screenshot: Optional[str]) -> Optional[bytes]:
    if not screenshot:
        return None
    try:
        b64 = screenshot.split(",", 1)[1] if screenshot.startswith("data:") else screenshot
        return base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        return None


def _candidates_from_dom(dom: str, limit: int = 20) -> list[dict]:
    """Buttons + links as {selector, name} for the Vision Agent."""
    try:
        page = json.loads(dom)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(page, dict):
        return []
    out, seen = [], set()
    for key in ("buttons", "links"):
        for el in page.get(key, []) or []:
            if not isinstance(el, dict):
                continue
            sel = el.get("selector") or (f"#{el['id']}" if el.get("id") else None)
            # Prefer visible text (an icon glyph is more telling than a generic
            # accessibleName like "button").
            name = (el.get("text") or el.get("accessibleName") or el.get("ariaLabel") or "").strip()
            if sel and sel not in seen:
                seen.add(sel)
                out.append({"selector": sel, "name": name or "(no label)"})
    return out[:limit]


def _match_selector(picked: Optional[str], known: set[str]) -> Optional[str]:
    """Tolerantly map the Vision Agent's answer to a real selector, or None."""
    if not picked:
        return None
    picked = picked.strip()
    if picked in known:
        return picked
    # Vision sometimes echoes surrounding text; recover an embedded known selector.
    hits = [s for s in known if s and s in picked]
    return hits[0] if len(hits) == 1 else None


async def run_agent(
    goal: str,
    url: str,
    dom: str,
    screenshot: Optional[str] = None,
    history_text: str = "",
) -> AgentResponse:
    page_summary, known_selectors = _g._summarize_dom(dom)
    log.info("[ROOT] goal=%r url=%r (%d known selectors, screenshot=%s)",
             goal, url, len(known_selectors), bool(screenshot))

    base_state = {
        "goal": goal,
        "url": url,
        "page_summary": page_summary,
        "history": history_text or "(none)",
    }
    timings: dict[str, float] = {}
    perception_mode = "structure"
    vision_used = False
    reconciliation: Optional[dict[str, Any]] = None

    try:
        # -- STRUCTURE (fast path) --------------------------------------- #
        t0 = time.perf_counter()
        s_final = await _run(structure_agent, dict(base_state), goal, "STRUCTURE")
        timings["structure_ms"] = round((time.perf_counter() - t0) * 1000)
        structure = _as_dict(s_final.get("structure")) or {}
        s_conf = float(structure.get("confidence", 0.0) or 0.0)
        needs_vision = bool(structure.get("needs_vision", False))
        log.info("[STRUCTURE] confidence=%.2f needs_vision=%s reason=%s",
                 s_conf, needs_vision, structure.get("reason"))

        route_vision = bool(screenshot) and (s_conf < VISION_CONFIDENCE_THRESHOLD or needs_vision)
        log.info("[ROUTER] vision=%s", route_vision)

        perception: dict[str, Any] = {
            "mode": "structure",
            "page_type": structure.get("page_type"),
            "relevant_elements": structure.get("relevant_elements", []),
            "structure_confidence": s_conf,
        }

        # -- VISION (fallback) ---------------------------------------- #
        if route_vision:
            image = _decode_screenshot(screenshot)
            candidates = _candidates_from_dom(dom)
            cand_text = "\n".join(
                f'{c["selector"]}   (label: "{c["name"]}")' for c in candidates
            ) or "(none)"
            v_state = dict(base_state)
            v_state["candidates_text"] = cand_text
            v_state["structure_reason"] = structure.get("reason") or ""

            t1 = time.perf_counter()
            v_final = await _run(vision_agent, v_state, goal, "VISION", image_bytes=image)
            timings["vision_ms"] = round((time.perf_counter() - t1) * 1000)
            vision = _as_dict(v_final.get("vision")) or {}
            v_sel = _match_selector(vision.get("selected_selector"), known_selectors)
            v_conf = float(vision.get("confidence", 0.0) or 0.0)
            log.info("[VISION] selected=%s -> %s meaning=%s confidence=%.2f",
                     vision.get("selected_selector"), v_sel, vision.get("meaning"), v_conf)

            raw_pick = vision.get("selected_selector")
            if v_sel:
                vision_used = True
                perception_mode = "vision"
                perception = {
                    "mode": "vision",
                    "page_type": structure.get("page_type"),
                    "vision_target": {"selector": v_sel, "meaning": vision.get("meaning")},
                    "vision_confidence": v_conf,
                    "vision_reason": vision.get("reason"),
                    "relevant_elements": structure.get("relevant_elements", []),
                }
            elif raw_pick:
                log.warning("[VISION] rejected selector %r (not on page - hallucination guard)", raw_pick)
                perception["vision_note"] = (
                    f"Vision suggested {raw_pick!r} but it is not a real element; ignored."
                )
            else:
                perception["vision_note"] = "Vision could not visually match any candidate."

            # -- RECONCILIATION (Phase 7) ------------------------------ #
            r_state = dict(base_state)
            r_state["structure_json"] = json.dumps(structure, default=str)
            r_state["vision_json"] = json.dumps(vision, default=str)
            r_state["candidates_text"] = cand_text
            t_r = time.perf_counter()
            r_final = await _run(reconciliation_agent, r_state, goal, "RECONCILIATION")
            timings["reconciliation_ms"] = round((time.perf_counter() - t_r) * 1000)
            reconciliation = _as_dict(r_final.get("reconciliation")) or {
                "status": "UNKNOWN", "confidence": 0.0,
                "reason": "Reconciliation Agent produced no usable output.",
            }
            log.info("[RECONCILIATION] %s  structure=%r vision=%r  reason=%s",
                     reconciliation.get("status"),
                     reconciliation.get("structure_interpretation"),
                     reconciliation.get("vision_interpretation"),
                     reconciliation.get("reason"))

            # Deterministic safety gate: anything but AGREE -> do NOT act.
            if reconciliation.get("status") != "AGREE":
                log.warning("[SAFETY] action blocked by reconciliation (%s)", reconciliation.get("status"))
                msg = (
                    "I found conflicting information about this element, so I won't activate it."
                    if reconciliation.get("status") == "CONFLICT"
                    else "I couldn't confidently determine which element matches your request, so I won't act."
                )
                blocked = _g._normalize(
                    {"action": "none", "confidence": 0.0,
                     "reasoning": f"{msg} ({reconciliation.get('reason', '')})"},
                    known_selectors,
                )
                blocked.perception_mode = "reconciliation"
                blocked.vision_used = True
                blocked.timings = timings
                blocked.reconciliation = reconciliation
                return blocked

        # -- ACTION -------------------------------------------------- #
        a_state = dict(base_state)
        a_state["perception"] = perception
        t2 = time.perf_counter()
        a_final = await _run(action_agent, a_state, goal, "ACT")
        timings["action_ms"] = round((time.perf_counter() - t2) * 1000)
        action = _as_dict(a_final.get("action")) or {
            "action": "none", "confidence": 0.0,
            "reasoning": "Action Agent produced no usable output.",
        }
        log.info("[ACTION] raw %s", action)

    except RuntimeError:
        raise
    except Exception:
        log.exception("[ROOT] ADK pipeline failed - falling back to direct Gemini")
        return _g.ask_gemini(goal=goal, url=url, dom=dom, screenshot=screenshot)

    response = _g._normalize(action, known_selectors)
    response.perception_mode = perception_mode
    response.vision_used = vision_used
    response.timings = timings
    response.reconciliation = reconciliation
    log.info("[ROOT] -> action=%s target=%s confidence=%.2f (%s%s%s)",
             response.action, response.target, response.confidence,
             perception_mode, ", vision" if vision_used else "",
             ", reconciled AGREE" if reconciliation else "")
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
