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
import re
import json
import logging
import time
import uuid
from typing import Any, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import gemini as _g
import memory as _mem
from models import AgentResponse
from policy import retry_allowed as _retry_allowed
from policy import risk_level as _risk_level
from tools.verification_tools import compare_page_states as _compare_page_states

from .action_agent import action_agent
from .config import APP_NAME, USER_ID, ensure_project
from .gemma_classifier import GemmaClassificationResult, filter_candidates
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
    for key, default_role in (("buttons", "button"), ("links", "link")):
        for el in page.get(key, []) or []:
            if not isinstance(el, dict):
                continue
            sel = el.get("selector") or (f"#{el['id']}" if el.get("id") else None)
            # Prefer visible text (an icon glyph is more telling than a generic
            # accessibleName like "button").
            name = (el.get("text") or el.get("accessibleName") or el.get("ariaLabel") or "").strip()
            if sel and sel not in seen:
                seen.add(sel)
                out.append({
                    "selector": sel,
                    "name": name or "(no label)",
                    "role": el.get("role") or default_role,
                    "text": (el.get("text") or "").strip(),
                })
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
    memory: Optional[dict] = None,
) -> AgentResponse:
    page_summary, known_selectors = _g._summarize_dom(dom)
    log.info("[ROOT] goal=%r url=%r (%d known selectors, screenshot=%s)",
             goal, url, len(known_selectors), bool(screenshot))

    # -- MEMORY RETRIEVAL (Phase 9 - the RAG step, before perception) ----- #
    if memory is None:
        try:
            memory = _mem.retriever().retrieve(url, goal)
        except Exception:  # noqa: BLE001
            log.exception("[MEMORY] retrieval failed")
            memory = {}
    retrieved = memory or {}
    memory_text = _mem.render_memory(retrieved)

    base_state = {
        "goal": goal,
        "url": url,
        "page_summary": page_summary,
        "history": history_text or "(none)",
        "memory": memory_text,
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

        # -- GEMMA FAST-FILTER (Phase 14: REACH's second Google model) --- #
        # Structure/Gemini has understood the page; Gemma now pre-screens the
        # raw on-page candidates so the downstream Gemini agents (Vision,
        # Reconciliation, Action) reason over a short, ranked shortlist instead
        # of every element. Pure narrowing + ranking - Gemma never acts, cannot
        # veto a Structure-relevant element, and any failure keeps every
        # candidate (see gemma_classifier).
        all_candidates = _candidates_from_dom(dom, limit=40)
        structure_floor = {
            e.get("selector") for e in (structure.get("relevant_elements") or [])
            if isinstance(e, dict) and e.get("selector") in known_selectors
        }
        t_g = time.perf_counter()
        try:
            gemma_result = await filter_candidates(
                goal, all_candidates, page_context=url, floor=structure_floor)
        except Exception:  # noqa: BLE001 - never let the fast-filter break the pipeline
            log.exception("[GEMMA] classifier raised - passthrough")
            _sels = [c["selector"] for c in all_candidates]
            gemma_result = GemmaClassificationResult(
                used=False, model="unavailable", candidates_in=len(_sels),
                candidates_out=len(_sels), kept=_sels, fallback_reason="classifier error")
        timings["gemma_ms"] = round((time.perf_counter() - t_g) * 1000)

        if gemma_result.used:
            _order = {s: i for i, s in enumerate(gemma_result.kept)}
            filtered_candidates = sorted(
                (c for c in all_candidates if c["selector"] in gemma_result.kept_set),
                key=lambda c: _order.get(c["selector"], 999),
            )
            perception["gemma_shortlist"] = [
                {"selector": c["selector"], "name": c["name"]} for c in filtered_candidates
            ]
        else:
            filtered_candidates = all_candidates
        perception["gemma"] = gemma_result.summary()

        # -- VISION (fallback) ---------------------------------------- #
        if route_vision:
            image = _decode_screenshot(screenshot)
            candidates = filtered_candidates
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

            # -- RECONCILIATION (Phase 7 + 10: correction as evidence) --- #
            r_state = dict(base_state)
            r_state["structure_json"] = json.dumps(structure, default=str)
            r_state["vision_json"] = json.dumps(vision, default=str)
            r_state["candidates_text"] = cand_text
            r_state["corrections_text"] = memory_text
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
                blocked.gemma = gemma_result.summary()
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

        # -- CORRECTION-AWARE RANKING (Phase 10, Steps 10.12-10.14) ----- #
        # Uses the FULL candidate set (not the Gemma shortlist): a persisted
        # user correction is ground truth and must never be filtered away.
        ranking = _apply_correction_ranking(
            action, retrieved.get("corrections", []),
            all_candidates, known_selectors, goal,
        )

    except RuntimeError:
        raise
    except Exception:
        log.exception("[ROOT] ADK pipeline failed - falling back to direct Gemini")
        return _g.ask_gemini(goal=goal, url=url, dom=dom, screenshot=screenshot)

    response = _g._normalize(action, known_selectors)
    response.perception_mode = perception_mode
    response.vision_used = vision_used
    response.timings = timings
    response.gemma = gemma_result.summary()
    response.reconciliation = reconciliation
    response.memory = retrieved
    response.memory_used = bool(retrieved.get("page_memory") or retrieved.get("corrections"))
    response.ranking = ranking
    response.correction_applied = bool(ranking and ranking.get("correction_applied"))
    log.info("[ROOT] -> action=%s target=%s confidence=%.2f (%s%s%s%s%s)",
             response.action, response.target, response.confidence,
             perception_mode, ", vision" if vision_used else "",
             ", reconciled AGREE" if reconciliation else "",
             ", memory" if response.memory_used else "",
             ", correction" if response.correction_applied else "")
    return response


def _label_matches_goal(label: str, goal: str) -> bool:
    if not label:
        return False
    lt = {w for w in re.split(r"[^a-z0-9]+", label.lower()) if len(w) > 2}
    gt = {w for w in re.split(r"[^a-z0-9]+", goal.lower()) if len(w) > 2}
    return bool(lt & gt) or label.lower() in goal.lower()


def _apply_correction_ranking(action: dict, corrections: list[dict], candidates: list[dict],
                              known: set[str], goal: str) -> Optional[dict]:
    """Boost / override the Action Agent's target using persisted user corrections.
    Deterministic and explainable; result still passes _normalize + verification."""
    matched = _mem.match_corrections_to_candidates(corrections, candidates)
    if not matched:
        return None

    # corrected elements whose label is relevant to the goal and that exist now
    hits = [
        (sel, c) for sel, c in matched.items()
        if sel in known and _label_matches_goal(c.get("correct_label", ""), goal)
    ]
    if not hits:
        return {"correction_applied": False, "candidates_considered": list(matched)}
    hits.sort(key=lambda x: float(x[1].get("confidence", 0)), reverse=True)
    corrected_sel, corr = hits[0]

    base_target = action.get("target")
    base_conf = float(action.get("confidence", 0) or 0)
    explain: dict[str, Any] = {
        "correction_applied": False,
        "corrected_selector": corrected_sel,
        "correct_label": corr.get("correct_label"),
        "base_target": base_target,
        "base_confidence": round(base_conf, 2),
    }

    if base_target == corrected_sel:
        action["confidence"] = max(base_conf, 0.95)
        action["reasoning"] = (action.get("reasoning") or "") + \
            f" [correction boost: user previously identified {corrected_sel} as '{corr.get('correct_label')}']"
        explain.update(correction_applied=True, effect="boost", final_confidence=action["confidence"])
        log.info("[RANKING] %s boosted -> conf %.2f (matches user correction '%s')",
                 corrected_sel, action["confidence"], corr.get("correct_label"))
    elif action.get("action") in ("click", "none") and (base_conf < 0.9 or not base_target):
        action["action"] = "click"
        action["target"] = corrected_sel
        action["value"] = None
        action["confidence"] = 0.92
        action["reasoning"] = (
            f"User previously corrected {corrected_sel} to mean '{corr.get('correct_label')}', "
            f"which matches the goal; choosing it over the model's pick {base_target!r}."
        )
        explain.update(correction_applied=True, effect="override", final_confidence=0.92)
        log.info("[RANKING] override: %s -> %s (user correction '%s' beats model pick, base conf %.2f)",
                 base_target, corrected_sel, corr.get("correct_label"), base_conf)
    else:
        explain["effect"] = "none (model already confident on a different element)"
    return explain


_VALID_VERIFY_STATUS = {"VERIFIED", "FAILED", "AMBIGUOUS", "BLOCKED", "NEEDS_CONFIRMATION"}


def _page_text_url(dom: str) -> tuple[str, str]:
    try:
        page = json.loads(dom)
        if isinstance(page, dict):
            return str(page.get("visibleText") or ""), str(page.get("url") or "")
    except (json.JSONDecodeError, TypeError):
        pass
    return "", ""


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
    act = _as_dict(action) or {}

    # -- deterministic evidence extraction (Step 8.15) --------------------- #
    b_text, b_url = _page_text_url(before_dom)
    a_text, a_url = _page_text_url(after_dom)
    diff = _compare_page_states(b_url, after_url or a_url, b_text, a_text)
    evidence_text = json.dumps(diff, default=str)[:2000]

    log.info("[VERIFY] goal=%r  [BEFORE] url=%r  [ACTION] %s  [AFTER] url=%r  url_changed=%s",
             goal, b_url, action_taken, after_url or a_url, diff.get("url_changed"))

    state = {
        "goal": goal,
        "action_taken": action_taken,
        "evidence_text": evidence_text,
        "before_summary": before_summary,
        "after_summary": (f"URL: {after_url}\n" if after_url else "") + after_summary,
    }

    try:
        final = await _run(verification_agent, state, goal, "VERIFY")
        result = _as_dict(final.get("verification")) or {}
    except RuntimeError:
        raise
    except Exception:
        log.exception("[VERIFICATION] agent failed")
        result = {}

    status = str(result.get("status", "")).upper()
    if status not in _VALID_VERIFY_STATUS:
        status = "AMBIGUOUS"
    reason = str(result.get("reason") or "Could not establish whether the goal succeeded.")
    evidence = [str(e) for e in (result.get("evidence") or []) if e]
    if not evidence:
        evidence = _summarize_diff(diff)

    # -- deterministic overrides (Steps 8.19, 8.20, 8.23, 8.39) ---------- #
    success = status == "VERIFIED"                      # false-success prevention
    level = _risk_level(act.get("action", ""), act.get("target"), act.get("value"))
    retry_ok = _retry_allowed(status, level)            # policy, not the model

    out = {
        "status": status,
        "success": success,
        "reason": reason,
        "evidence": evidence,
        "retry_allowed": retry_ok,
        "risk_level": level,
    }
    log.info("[VERIFICATION] -> %s  success=%s  retry_allowed=%s  risk=%s",
             status, success, retry_ok, level)
    if status == "AMBIGUOUS":
        log.warning("[SAFETY] verification AMBIGUOUS - retry blocked, success NOT claimed")
    return out


def _summarize_diff(diff: dict) -> list[str]:
    ev = []
    ev.append("URL changed" if diff.get("url_changed") else "URL unchanged")
    for ln in (diff.get("new_lines") or [])[:4]:
        ev.append(f"new: {ln}")
    if not diff.get("new_lines"):
        ev.append("no new page content")
    return ev
