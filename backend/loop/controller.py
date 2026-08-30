"""One reasoning step of the browser action loop (Steps 4.5, 4.13-4.17, 4.22-4.23)."""

from __future__ import annotations

import logging

from agents import run_agent, run_verification
from models import LoopStepRequest, LoopStepResponse

from .history import format_history, is_repeated
from .safety import classify_risk
from .state import CONFIDENCE_GATE, REPEAT_LIMIT, LoopStatus

log = logging.getLogger("reach.loop")


def _step(status: LoopStatus, step: int, *, action="none", target=None, value=None,
          confidence=0.0, done=False, requires_confirmation=False, reason=None,
          verification=None, perception_mode=None, vision_used=False,
          reconciliation=None) -> LoopStepResponse:
    return LoopStepResponse(
        status=status.value,
        done=done,
        step=step,
        action=action,
        target=target,
        value=value,
        confidence=confidence,
        requires_confirmation=requires_confirmation,
        reason=reason,
        verification=verification,
        perception_mode=perception_mode,
        vision_used=vision_used,
        reconciliation=reconciliation,
    )


async def run_loop_step(req: LoopStepRequest) -> LoopStepResponse:
    step = len(req.history) + 1
    log.info("[LOOP] Step %d  goal=%r  url=%r  (%d prior actions)",
             step, req.goal, req.url, len(req.history))

    # --- max-steps guard (Step 4.15) --------------------------------------- #
    if len(req.history) >= req.max_steps:
        log.info("[LOOP] stop: max_steps=%d reached", req.max_steps)
        return _step(LoopStatus.MAX_STEPS_REACHED, step,
                     reason=f"Reached max_steps={req.max_steps} without achieving the goal.")

    # --- verify the previous action (Steps 4.12-4.14) --------------------- #
    verification = None
    if req.last_action and req.prev_dom:
        verification = await run_verification(
            goal=req.goal,
            before_dom=req.prev_dom,
            action=req.last_action,
            after_dom=req.dom,
            after_url=req.url,
        )
        log.info("[VERIFY] success=%s reason=%s",
                 verification.get("success"), verification.get("reason"))
        if verification.get("success"):
            return _step(LoopStatus.COMPLETED, step, done=True, confidence=1.0,
                         reason=verification.get("reason"), verification=verification)

    # --- reason the next action via the ADK Root Agent (Step 4.1.2) ------- #
    decision = await run_agent(
        goal=req.goal,
        url=req.url,
        dom=req.dom,
        screenshot=req.screenshot,
        history_text=format_history(req.history),
    )
    pm = {
        "perception_mode": decision.perception_mode,
        "vision_used": decision.vision_used,
        "reconciliation": decision.reconciliation,
    }
    log.info("[REASON] action=%s target=%s confidence=%.2f done=%s perception=%s%s%s",
             decision.action, decision.target, decision.confidence, decision.done,
             decision.perception_mode, " +vision" if decision.vision_used else "",
             f" reconcile={decision.reconciliation['status']}" if decision.reconciliation else "")

    # --- no safe next action (includes a reconciliation CONFLICT/UNKNOWN) -- #
    if decision.action == "none":
        return _step(LoopStatus.BLOCKED, step, confidence=decision.confidence,
                     reason=decision.reasoning or "No safe next action found.",
                     verification=verification, **pm)

    # --- repeated-action detection (Step 4.16) --------------------------- #
    if is_repeated(req.history, decision.action, decision.target, REPEAT_LIMIT):
        log.info("[LOOP] stop: %s %s proposed %d+ times",
                 decision.action, decision.target, REPEAT_LIMIT)
        return _step(LoopStatus.REPEATED_ACTION, step, confidence=decision.confidence,
                     reason=f"'{decision.action} {decision.target}' was proposed "
                            f"{REPEAT_LIMIT} times in a row - stopping to avoid a loop.",
                     verification=verification, **pm)

    # --- confidence gate (Step 4.17) ----------------------------------- #
    if decision.confidence < CONFIDENCE_GATE:
        best = f"{decision.action} {decision.target or ''}".strip()
        return _step(
            LoopStatus.LOW_CONFIDENCE, step, confidence=decision.confidence,
            reason=(
                f'Stopping: the best next step ("{best}") is only '
                f"{decision.confidence:.0%} confident - below the "
                f"{CONFIDENCE_GATE:.0%} bar for autonomous actions. "
                f"This goal may not be achievable on this page."
            ),
            verification=verification, **pm,
        )

    # --- consequential-action confirmation (Step 4.18) ---------------- #
    risk = classify_risk(req.goal, decision.action, decision.target, decision.value)
    if risk:
        log.info("[LOOP] pause for confirmation: %s", risk)
        return _step(LoopStatus.NEEDS_CONFIRMATION, step, action=decision.action,
                     target=decision.target, value=decision.value,
                     confidence=decision.confidence, requires_confirmation=True,
                     reason=f"{risk}. Approve to continue.", verification=verification, **pm)

    # --- normal: execute this action, then the extension observes again -- #
    return _step(LoopStatus.RUNNING, step, action=decision.action, target=decision.target,
                 value=decision.value, confidence=decision.confidence,
                 reason=decision.reasoning, verification=verification, **pm)
