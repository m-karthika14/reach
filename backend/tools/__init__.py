"""REACH agent tools (Phase 3).

The ADK agents do not touch Chrome directly. A tool either analyses the page
context the extension already sent, or returns a *structured action request*
that Cloud Run passes back to the extension, which performs the real browser
action. This keeps execution on the client and out of the model.
"""

from .action_tools import ACTION_TOOLS
from .page_context import PAGE_CONTEXT_TOOLS
from .verification_tools import VERIFICATION_TOOLS

__all__ = ["ACTION_TOOLS", "PAGE_CONTEXT_TOOLS", "VERIFICATION_TOOLS"]
