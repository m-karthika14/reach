"""Action history helpers (Steps 4.4, 4.16)."""

from typing import Any, Iterable

from .state import REPEAT_LIMIT


def _key(action: str, target: Any) -> tuple[str, str]:
    return (str(action or "").lower(), str(target or ""))


def format_history(items: Iterable[Any]) -> str:
    """Compact, model-friendly rendering of what has been done this task."""
    lines = []
    for it in items:
        step = getattr(it, "step", None) if not isinstance(it, dict) else it.get("step")
        action = getattr(it, "action", None) if not isinstance(it, dict) else it.get("action")
        target = getattr(it, "target", None) if not isinstance(it, dict) else it.get("target")
        value = getattr(it, "value", None) if not isinstance(it, dict) else it.get("value")
        piece = f"{step}. {action} {target or ''}".strip()
        if value:
            piece += f" = {value!r}"
        lines.append(piece)
    return "\n".join(lines) if lines else "(none)"


def is_repeated(history: Iterable[Any], action: str, target: Any, limit: int = REPEAT_LIMIT) -> bool:
    """True if proposing (action, target) now would make it the `limit`-th in a row."""
    proposed = _key(action, target)
    run = 0
    for it in history:
        it_action = getattr(it, "action", None) if not isinstance(it, dict) else it.get("action")
        it_target = getattr(it, "target", None) if not isinstance(it, dict) else it.get("target")
        run = run + 1 if _key(it_action, it_target) == proposed else 0
    return run >= (limit - 1)
