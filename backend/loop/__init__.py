"""Phase 4 - browser action loop (reasoning/orchestration half).

The loop *iteration* lives in the extension (it owns Chrome). The backend
exposes ONE reasoning step:

    run_loop_step(LoopStepRequest) -> LoopStepResponse

Given the goal, the current observation, and the history so far, it:
  1. verifies whether the previous action already achieved the goal,
  2. otherwise asks the ADK Root Agent for the next action,
  3. applies the safety gates (confidence, invented-selector, repeated-action,
     max-steps, consequential-action confirmation),
  4. returns a typed step with a status the extension loop reacts to.
"""

from .controller import run_loop_step

__all__ = ["run_loop_step"]
