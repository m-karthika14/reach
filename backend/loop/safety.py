"""Loop safety gates - thin re-export of the shared policy module.

The real logic lives in `policy.py` (top-level, import-cycle-free). Kept here so
existing `from loop.safety import classify_risk` imports still work.
"""

from policy import CONSEQUENTIAL, MEDIUM, classify_risk, retry_allowed, risk_level

__all__ = ["classify_risk", "risk_level", "retry_allowed", "CONSEQUENTIAL", "MEDIUM"]
