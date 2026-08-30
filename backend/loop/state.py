"""Loop status vocabulary (Step 4.26)."""

from enum import Enum


class LoopStatus(str, Enum):
    RUNNING = "running"                    # execute the returned action, then continue
    COMPLETED = "completed"               # verification says the goal is achieved
    BLOCKED = "blocked"                   # no safe next action found
    FAILED = "failed"                     # an error stopped the loop
    MAX_STEPS_REACHED = "max_steps_reached"
    REPEATED_ACTION = "repeated_action"   # same action+target proposed too many times
    LOW_CONFIDENCE = "low_confidence"     # below the confidence gate
    NEEDS_CONFIRMATION = "needs_confirmation"  # consequential action - ask the user
    CANCELLED = "cancelled"              # user pressed Stop (set by the extension)


# The loop stops on anything that is not RUNNING or NEEDS_CONFIRMATION.
TERMINAL = {
    LoopStatus.COMPLETED,
    LoopStatus.BLOCKED,
    LoopStatus.FAILED,
    LoopStatus.MAX_STEPS_REACHED,
    LoopStatus.REPEATED_ACTION,
    LoopStatus.LOW_CONFIDENCE,
    LoopStatus.CANCELLED,
}

MAX_STEPS_DEFAULT = 8
# The autonomous loop is stricter than the single-step /agent gate (0.80):
# a confident agent returns ~0.95-1.0; ~0.80 means it is guessing, and in a
# loop that becomes a wander. Stop instead.
CONFIDENCE_GATE = 0.85
REPEAT_LIMIT = 3  # same (action, target) proposed a 3rd time overall -> stop
