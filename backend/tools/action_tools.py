"""Action tools: each returns a structured action request for the extension.

    ADK agent -> action tool -> structured action -> Cloud Run response
              -> Chrome extension -> real browser action

Nothing here touches the browser; the extension's Phase 1 engine does.
"""

from typing import Any, Optional

from google.adk.tools import FunctionTool

ALLOWED_ACTIONS = ("click", "type", "select", "scroll", "back", "none")


def click_element(target: str) -> dict[str, Any]:
    """Request a CLICK.

    Args:
        target: CSS selector of a button/link that exists on the current page.
    """
    return {"action": "click", "target": target, "value": None}


def type_text(target: str, value: str) -> dict[str, Any]:
    """Request TYPE into an input.

    Args:
        target: CSS selector of the input/textarea.
        value: text to enter.
    """
    return {"action": "type", "target": target, "value": value}


def select_option(target: str, value: str) -> dict[str, Any]:
    """Request SELECT of a <select> option.

    Args:
        target: CSS selector of the <select>.
        value: option value or visible label.
    """
    return {"action": "select", "target": target, "value": value}


def scroll_page(amount: Optional[int] = 600) -> dict[str, Any]:
    """Request a page SCROLL.

    Args:
        amount: pixels to scroll down (default 600).
    """
    return {"action": "scroll", "target": None, "value": str(amount)}


def go_back() -> dict[str, Any]:
    """Request browser BACK navigation."""
    return {"action": "back", "target": None, "value": None}


ACTION_TOOLS = [
    FunctionTool(click_element),
    FunctionTool(type_text),
    FunctionTool(select_option),
    FunctionTool(scroll_page),
    FunctionTool(go_back),
]
