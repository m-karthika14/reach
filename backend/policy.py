"""Deterministic safety policy - risk classification and retry rules.

Top-level module (no package imports) so both agents/ and loop/ can use it
without an import cycle.
"""

import re
from typing import Optional

# Whole-token markers of a consequential / hard-to-undo action. Matched against
# the tokens of the action's target selector and value ONLY - never the goal
# text (so "show payment details" is not treated as a payment), and as exact
# tokens (so "#pay-button" matches but "#payment-details" does not).
CONSEQUENTIAL = {
    "pay", "buy", "purchase", "checkout", "order", "confirm",
    "delete", "remove", "transfer", "withdraw",
}

# Medium-risk markers - worth verifying carefully but not a hard confirm gate.
MEDIUM = {"download", "submit", "send", "upload", "apply", "save"}


def _tokens(text: Optional[str]) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t}


def classify_risk(goal: str, action: str, target: Optional[str], value: Optional[str]) -> Optional[str]:
    """Human-readable reason if this action needs explicit confirmation, else None."""
    if action in ("scroll", "back", "none"):
        return None
    hits = (_tokens(target) | _tokens(value)) & CONSEQUENTIAL
    if hits:
        return f"consequential action detected ({sorted(hits)[0]!r})"
    return None


def risk_level(action: str, target: Optional[str], value: Optional[str]) -> str:
    """low | medium | high  (Step 8.24)."""
    if action in ("scroll", "back", "none"):
        return "low"
    tokens = _tokens(target) | _tokens(value)
    if tokens & CONSEQUENTIAL:
        return "high"
    if tokens & MEDIUM:
        return "medium"
    return "low"


def retry_allowed(status: str, level: str) -> bool:
    """Deterministic retry policy (Step 8.23): only a non-high-risk FAILED may retry.
    VERIFIED / AMBIGUOUS / BLOCKED / NEEDS_CONFIRMATION -> never."""
    if status != "FAILED":
        return False
    return level != "high"
