"""Loop safety gates (Steps 4.17, 4.18).

Confidence gating and invented-selector protection already run inside
gemini._normalize (Phase 2, applied by root_agent). This module adds the
loop-only concern: flag consequential actions so the autonomous loop pauses
for explicit user approval instead of just doing them.
"""

import re
from typing import Optional

# Whole-token markers of a consequential / hard-to-undo action. Matched against
# the tokens of the action's target selector and value ONLY - never the goal
# text (so "show payment details" is not treated as a payment), and as exact
# tokens (so "#pay-button" matches but "#payment-details" does not).
CONSEQUENTIAL = {
    "pay",
    "buy",
    "purchase",
    "checkout",
    "order",
    "confirm",
    "delete",
    "remove",
    "transfer",
    "withdraw",
}


def _tokens(text: Optional[str]) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t}


def classify_risk(
    goal: str,
    action: str,
    target: Optional[str],
    value: Optional[str],
) -> Optional[str]:
    """Return a human-readable reason if this action needs confirmation, else None."""
    if action in ("scroll", "back", "none"):
        return None

    hits = (_tokens(target) | _tokens(value)) & CONSEQUENTIAL
    if hits:
        return f"consequential action detected ({sorted(hits)[0]!r})"
    return None
