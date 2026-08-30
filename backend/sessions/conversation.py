"""One conversational turn (Phase 5, Steps 5.19-5.31).

    load session (Firestore) -> reconcile page -> record prior execution + verify
    -> interpret message (dialogue agent) -> handle command / correction / reference
    -> reason next action (ADK Root Agent, with session context) -> risk gate
    -> update + persist session -> reply
"""

from __future__ import annotations

import json
import logging
import re

import memory as _mem
from agents import resolve_message, run_agent, run_verification
from models import AgentResponse, ChatRequest, ChatResponse
from policy import classify_risk

from .manager import SessionManager, new_session_id

log = logging.getLogger("reach.chat")

# A confident action returns ~0.95-1.0; ~0.8 is the model guessing at the
# closest element. Don't auto-run guesses (matches the autonomous-loop gate).
CONFIDENCE_GATE = 0.85

_VERB = {
    "click": "clicking", "type": "entering that", "select": "choosing that",
    "scroll": "scrolling", "back": "going back", "none": "",
}


def _phrase(a: AgentResponse) -> str:
    bit = _VERB.get(a.action, a.action)
    return f"{bit} {a.target}".strip() if a.target else bit


_AMOUNT_RE = re.compile(r"(?:₹|\bRs\.?\s?|\$)\s?[\d,]+(?:\.\d{1,2})?")


def _extract_amount(dom: str) -> str | None:
    try:
        text = json.loads(dom).get("visibleText", "") if dom else ""
    except (json.JSONDecodeError, TypeError, AttributeError):
        text = dom or ""
    m = _AMOUNT_RE.search(text)
    return m.group(0).strip() if m else None


_PREF_CONFIRM_ON = re.compile(
    r"\b(always ask|ask me|confirm|check with me)\b.{0,30}\b(pay|paying|payment|purchase|buy)", re.I)
_PREF_CONFIRM_OFF = re.compile(
    r"\b(don'?t|do not|never|stop) (ask|confirm|check).{0,30}\b(pay|payment|purchase)", re.I)
_PREF_LANG = re.compile(r"\b(?:prefer|use|set|switch to)\b.{0,20}\b(english|kannada|hindi|tamil|telugu)\b", re.I)


def _referenced_selector(state) -> str:
    """Which element was REACH just talking about? (for attaching a correction)"""
    if state.pending_confirmation and state.pending_confirmation.get("target"):
        return state.pending_confirmation["target"]
    if state.last_reconciliation and state.last_reconciliation.get("target"):
        return state.last_reconciliation["target"]
    if state.previous_actions:
        return state.previous_actions[-1].get("target", "") or ""
    # last assistant message may name a #selector
    for turn in reversed(state.conversation_history):
        if turn.role == "assistant":
            m = re.search(r"#[\w-]+", turn.content or "")
            if m:
                return m.group(0)
            break
    return ""


def _candidate_meta(state, selector: str) -> dict:
    for c in state.current_candidates or []:
        if c.get("selector") == selector:
            return {"role": c.get("kind", "button"), "name": c.get("name", ""), "text": c.get("name", ""),
                    "agent_prediction": ""}
    return {"role": "", "name": "", "text": "", "agent_prediction": ""}


def _maybe_preference(message: str) -> tuple[str, object] | None:
    """Detect a durable preference statement (Step 9.8), else None."""
    if _PREF_CONFIRM_OFF.search(message):
        return ("confirmation_before_payment", False)
    if _PREF_CONFIRM_ON.search(message):
        return ("confirmation_before_payment", True)
    m = _PREF_LANG.search(message)
    if m:
        return ("preferred_language", m.group(1).lower())
    return None


async def run_chat_turn(manager: SessionManager, req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or new_session_id()

    async with manager.lock(session_id):
        state = await manager.load(session_id)
        state.session_id = session_id

        # 1. fresh browser observation wins over stored page state
        manager.reconcile_page(state, req.url, req.dom)

        # 1b. RAG: retrieve what REACH knows about this site (Phase 9)
        try:
            turn_memory = _mem.retriever().retrieve(req.url, state.user_goal or req.message)
        except Exception:  # noqa: BLE001
            log.exception("[chat] memory retrieval failed")
            turn_memory = {}
        memory_used = False

        # 2. fold in what the extension executed since last turn, and verify it
        if req.last_executed:
            manager.record_execution(state, req.last_executed)
            if req.prev_dom:
                try:
                    v = await run_verification(
                        goal=state.user_goal or req.message,
                        before_dom=req.prev_dom,
                        action=req.last_executed,
                        after_dom=req.dom,
                        after_url=req.url,
                    )
                    state.verification_status = v
                    state.last_verification = v
                    try:
                        _mem.writer().apply_verification_outcome(
                            session_id=session_id, goal=state.user_goal or req.message,
                            url=req.url, action=req.last_executed, verification=v,
                            element_label=(state.user_goal or "")[:40],
                        )
                        # Phase 10: a VERIFIED action on a corrected element confirms it.
                        if v.get("status") == "VERIFIED" and req.last_executed.get("target"):
                            _mem.writer().mark_correction_verified(
                                req.url, req.last_executed["target"])
                    except Exception:  # noqa: BLE001
                        log.exception("[chat] memory write failed")
                except Exception:  # noqa: BLE001
                    log.exception("[chat] verification failed")

        manager.append_turn(state, "user", req.message)
        log.info("[CHAT] %s  status=%s  msg=%r", session_id, state.status, req.message)

        # 2b. durable preference statement (Phase 9, Step 9.8) -> store & ack
        pref = _maybe_preference(req.message)
        if pref:
            try:
                _mem.writer().set_preference(pref[0], pref[1])
            except Exception:  # noqa: BLE001
                log.exception("[chat] preference write failed")
            reply = f"Got it - I'll remember that ({pref[0]} = {pref[1]})."
            manager.append_turn(state, "assistant", reply)
            await manager.save(state)
            return ChatResponse(
                session_id=session_id, message=reply, status=state.status,
                candidates=state.current_candidates, memory=turn_memory,
                current_step=state.current_step,
            )

        # 3. interpret the message against the session
        ctx = {
            "user_goal": state.user_goal,
            "current_task": state.current_task,
            "actions_text": manager.actions_text(state),
            "candidates_text": manager.candidates_text(state),
            "history_text": manager.history_text(state),
            "pending_confirmation": state.pending_confirmation,
            "last_reconciliation": state.last_reconciliation,
            "last_verification": state.last_verification,
        }
        interp = await resolve_message(ctx, req.message)
        log.info("[CHAT] intent=%s command=%s goal=%r request=%r",
                 interp.intent, interp.command, interp.resolved_goal, interp.resolved_request)

        action: AgentResponse | None = None
        requires_confirmation = False
        reply = interp.reply or "Okay."
        memory_updated = False
        correction_out: dict | None = None
        ranking_out: dict | None = None

        lv = state.last_verification or {}

        # Phase 10: an explicit "you were wrong about X" correction -> persist it.
        if interp.intent == "correction" and interp.correction:
            cd = interp.correction
            selector = cd.selector or _referenced_selector(state)
            cand = _candidate_meta(state, selector)
            if selector:
                try:
                    correction_out = _mem.writer().record_correction(
                        url=req.url, selector=selector,
                        correct_label=cd.correct_label or (interp.resolved_request or "").strip(),
                        agent_prediction=cd.previous_label or cand.get("agent_prediction", ""),
                        user_said=req.message, strength=cd.strength or "normal",
                        role=cand.get("role", ""), accessible_name=cand.get("name", ""),
                        element_text=cand.get("text", ""),
                    )
                    memory_updated = True
                    reply = (
                        f"Got it - I'll remember that {selector} is "
                        f"\"{correction_out['correct_label']}\" (not "
                        f"\"{correction_out.get('previous_label') or 'what I said'}\")."
                    )
                    # re-retrieve so THIS turn already benefits from the correction
                    turn_memory = _mem.retriever().retrieve(req.url, state.user_goal or req.message)
                except Exception:  # noqa: BLE001
                    log.exception("[chat] correction write failed")

        # 4. explicit commands (Steps 5.24-5.26, 5.40)
        if interp.intent == "status_query":
            # Answer from stored evidence (Step 8.42) - never guess.
            if lv:
                ev = "; ".join(lv.get("evidence", [])[:4])
                reply = (
                    f"Last action: {lv.get('status')}. {lv.get('reason', '')}"
                    + (f" Evidence: {ev}." if ev else "")
                )
            else:
                reply = "I haven't taken an action to check yet."
        elif interp.command == "retry":
            # Deterministic no-retry rule (Steps 8.19, 8.23, 8.38).
            if lv.get("status") == "AMBIGUOUS":
                state.status = "blocked"
                reply = (
                    "I can't safely retry that. The previous attempt's result "
                    f"couldn't be confirmed ({lv.get('reason', '')}), and retrying a "
                    "consequential step could duplicate it."
                )
            elif lv.get("status") == "FAILED" and lv.get("retry_allowed"):
                state.status = "running"
                resp = await run_agent(
                    goal=state.user_goal or req.message, url=req.url, dom=req.dom,
                    screenshot=req.screenshot, history_text=manager.actions_text(state),
                )
                if resp.action != "none" and resp.confidence >= CONFIDENCE_GATE and not resp.reconciliation:
                    action = resp
                    reply = interp.reply or f"Retrying: {_phrase(resp)}."
                else:
                    state.status = "blocked"
                    reply = resp.reasoning or "I couldn't find a safe way to retry."
            else:
                reply = "There's nothing pending that I should retry."
        elif interp.command == "stop":
            state.status = "cancelled"
            state.pending_confirmation = None
            reply = "Okay, I've stopped."
        elif interp.command == "pause":
            state.status = "paused"
            reply = "Paused. Say \"continue\" when you want me to resume."
        elif interp.command == "no" and state.pending_confirmation:
            state.pending_confirmation = None
            state.status = "paused"
            reply = "Okay, I won't do that."
        elif interp.command == "yes" and state.pending_confirmation:
            action = AgentResponse.model_validate(state.pending_confirmation)
            state.pending_confirmation = None
            state.status = "running"
            reply = f"Okay, {_phrase(action)}."
        else:
            # 5. correction / new goal / reference / continue
            #    (an explicit element correction was already persisted above)
            if interp.resolved_goal and interp.intent in ("correction", "new_goal"):
                # the sub-task changed: drop stale task context, keep the dialogue
                state.pending_confirmation = None
                state.previous_actions = []
                state.current_step = 0
                state.verification_status = None
                state.user_goal = interp.resolved_goal
                state.current_task = interp.resolved_goal
            elif interp.resolved_goal and not state.user_goal:
                state.user_goal = interp.resolved_goal
                state.current_task = interp.resolved_goal
            goal_for_reasoning = interp.resolved_request or state.user_goal or req.message

            if interp.intent == "smalltalk" and not state.user_goal:
                state.status = "idle"
            else:
                state.status = "running"
                resp = await run_agent(
                    goal=goal_for_reasoning,
                    url=req.url,
                    dom=req.dom,
                    screenshot=req.screenshot,
                    history_text=manager.actions_text(state),
                    memory=turn_memory,
                )
                memory_used = resp.memory_used
                ranking_out = resp.ranking
                state.perception_mode = resp.perception_mode
                state.last_reconciliation = resp.reconciliation
                log.info("[CHAT] reason -> %s %s conf=%.2f perception=%s%s%s%s",
                         resp.action, resp.target, resp.confidence,
                         resp.perception_mode, " +vision" if resp.vision_used else "",
                         f" reconcile={resp.reconciliation['status']}" if resp.reconciliation else "",
                         " +correction" if resp.correction_applied else "")

                rec = resp.reconciliation
                if rec and rec.get("status") in ("CONFLICT", "UNKNOWN"):
                    # Phase 7: Structure and Vision disagree -> stop and ask.
                    state.status = "waiting_clarification"
                    reply = resp.reasoning or (
                        "I found conflicting information about that element, so I won't activate it. "
                        "Which one did you mean?"
                    )
                elif resp.action == "none":
                    state.status = "completed" if resp.done else "blocked"
                    reply = resp.reasoning or (
                        "That looks done." if resp.done
                        else "I couldn't find a safe way to do that here."
                    )
                elif resp.confidence < CONFIDENCE_GATE:
                    state.status = "blocked"
                    reply = (
                        f"I'm not confident enough to do that here "
                        f"({resp.confidence:.0%})."
                    )
                else:
                    risk = classify_risk(state.user_goal, resp.action, resp.target, resp.value)
                    if risk:
                        state.pending_confirmation = resp.model_dump()
                        state.status = "waiting_confirmation"
                        action = resp
                        requires_confirmation = True
                        amount = _extract_amount(req.dom)
                        amount_bit = f" This will pay {amount}." if amount else ""
                        reply = (
                            f"That's a consequential action ({risk}).{amount_bit} "
                            f"Say \"yes\" to go ahead."
                        )
                    else:
                        action = resp
                        reply = interp.reply or f"Okay, {_phrase(resp)}."

        manager.append_turn(state, "assistant", reply)
        await manager.save(state)

        return ChatResponse(
            session_id=session_id,
            message=reply,
            status=state.status,
            action=action,
            requires_confirmation=requires_confirmation,
            candidates=state.current_candidates,
            pending_confirmation=state.pending_confirmation,
            verification_status=state.verification_status,
            reconciliation=state.last_reconciliation,
            memory=turn_memory,
            memory_used=memory_used,
            memory_updated=memory_updated,
            correction=correction_out,
            ranking=ranking_out,
            current_step=state.current_step,
        )
