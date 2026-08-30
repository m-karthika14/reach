"""Verification tool: diff the BEFORE and AFTER page states for the agent."""

from typing import Any

from google.adk.tools import FunctionTool


def compare_page_states(
    before_url: str,
    after_url: str,
    before_text: str,
    after_text: str,
) -> dict[str, Any]:
    """Compare a page before vs. after an action.

    Args:
        before_url: URL before the action.
        after_url: URL after the action.
        before_text: visible text before.
        after_text: visible text after.

    Returns:
        dict with url_changed, new_lines (text present only in the after-state,
        capped), and removed_lines (text present only before, capped).
    """
    before_lines = {ln.strip() for ln in before_text.splitlines() if ln.strip()}
    after_lines = {ln.strip() for ln in after_text.splitlines() if ln.strip()}
    new_lines = sorted(after_lines - before_lines)
    removed_lines = sorted(before_lines - after_lines)
    return {
        "url_changed": before_url != after_url,
        "new_lines": new_lines[:25],
        "removed_lines": removed_lines[:25],
    }


VERIFICATION_TOOLS = [FunctionTool(compare_page_states)]
