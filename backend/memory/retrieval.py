"""Memory retrieval - the RAG step (Phase 9, Steps 9.10-9.13).

Simple Firestore-filter retrieval (no vector DB yet): match the domain, then the
page, rank page knowledge by verified + confidence + recency, cap hard.
Returns a small dict that gets rendered into the agents' prompts.
"""

from __future__ import annotations

import logging
from typing import Any

from .store import get_store
from .util import domain_of, page_of

log = logging.getLogger("reach.memory")

MAX_PAGE = 6
MAX_CORRECTIONS = 4
MAX_TASKS = 3


class MemoryRetriever:
    def __init__(self) -> None:
        self._store = get_store()

    def retrieve(self, url: str, goal: str) -> dict[str, Any]:
        domain, page = domain_of(url), page_of(url)

        page_rows = self._store.query("page_memory", {"domain": domain})
        # prefer same page, then verified, then confidence, then recency
        page_rows.sort(
            key=lambda r: (
                r.get("page") == page,
                bool(r.get("verified")),
                float(r.get("confidence", 0)),
                float(r.get("updated_at", 0)),
            ),
            reverse=True,
        )
        page_rows = [r for r in page_rows if float(r.get("confidence", 0)) >= 0.4][:MAX_PAGE]

        corrections = self._store.query("correction_memory", {"domain": domain})
        corrections.sort(key=lambda r: float(r.get("created_at", 0)), reverse=True)
        corrections = corrections[:MAX_CORRECTIONS]

        preferences = self._store.query("preference_memory")

        tasks = self._store.query("task_history", {"domain": domain})
        tasks.sort(key=lambda r: float(r.get("created_at", 0)), reverse=True)
        tasks = tasks[:MAX_TASKS]

        out = {
            "domain": domain,
            "page": page,
            "page_memory": [
                {"selector": r.get("selector"), "element": r.get("element"),
                 "description": r.get("description", ""), "verified": r.get("verified", False),
                 "confidence": round(float(r.get("confidence", 0)), 2)}
                for r in page_rows
            ],
            "corrections": [
                {"agent_assumed": r.get("agent_assumed"), "correct_element": r.get("correct_element"),
                 "user_said": r.get("user_said")}
                for r in corrections
            ],
            "preferences": [
                {"preference": r.get("preference"), "value": r.get("value")} for r in preferences
            ],
            "recent_tasks": [
                {"goal": r.get("goal"), "result": r.get("result")} for r in tasks
            ],
        }
        n = len(out["page_memory"]) + len(out["corrections"]) + len(out["preferences"])
        log.info("[MEMORY] retrieved %d memories for domain=%s page=%s "
                 "(page:%d corrections:%d prefs:%d)",
                 n, domain, page, len(out["page_memory"]), len(out["corrections"]),
                 len(out["preferences"]))
        return out


def render_memory(mem: dict[str, Any]) -> str:
    """Compact text block for an agent prompt. 'hint, not authority.'"""
    if not mem:
        return "(no memory of this site)"
    lines: list[str] = []
    if mem.get("page_memory"):
        lines.append("Learned elements on this site (verify they still exist on THIS page):")
        for r in mem["page_memory"]:
            lines.append(
                f"  - {r['element']} = {r['selector']}"
                f"  ({'verified' if r['verified'] else 'unverified'}, conf {r['confidence']})"
                + (f" - {r['description']}" if r.get("description") else "")
            )
    if mem.get("corrections"):
        lines.append("Past user corrections on this site:")
        for c in mem["corrections"]:
            lines.append(f"  - user said {c['user_said']!r}: use {c['correct_element']} not {c['agent_assumed']}")
    if mem.get("preferences"):
        lines.append("User preferences:")
        for p in mem["preferences"]:
            lines.append(f"  - {p['preference']} = {p['value']}")
    if mem.get("recent_tasks"):
        lines.append("Recent tasks here: " + "; ".join(
            f"{t['goal']} -> {t['result']}" for t in mem["recent_tasks"]))
    return "\n".join(lines) if lines else "(no memory of this site)"
