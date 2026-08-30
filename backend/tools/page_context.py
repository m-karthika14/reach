"""Perception tool: expose the extension-captured page context to an agent.

The backend cannot read Chrome's DOM. The extension sends it; this tool turns
that raw JSON into a compact, model-friendly summary plus the set of valid
selectors on the page.
"""

from typing import Any

from google.adk.tools import FunctionTool


def summarize_page_context(dom: str) -> dict[str, Any]:
    """Summarize the current browser page.

    Args:
        dom: JSON string produced by the extension's getPageContext()
            (or a plain text description).

    Returns:
        dict with:
          summary:   compact text listing buttons/links/inputs + visible text
          selectors: sorted list of every valid selector found on the page
    """
    from gemini import _summarize_dom  # local import avoids a cycle at import time

    summary, selectors = _summarize_dom(dom)
    return {"summary": summary, "selectors": sorted(selectors)}


PAGE_CONTEXT_TOOLS = [FunctionTool(summarize_page_context)]
