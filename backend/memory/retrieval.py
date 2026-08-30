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

    def retrieve(self, url: str, goal: str, user_id: str = "demo-user") -> dict[str, Any]:
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

        raw_corr = self._store.query("correction_memory", {"user_id": user_id, "domain": domain})
        raw_corr.sort(key=lambda r: float(r.get("created_at", 0)), reverse=True)
        corrections = _aggregate_corrections(raw_corr, page)

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
            "corrections": corrections,
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


def _aggregate_corrections(rows: list[dict], page: str) -> list[dict]:
    """Group by selector; flag conflicting labels; boost repeats. (Steps 10.8, 10.35)"""
    by_sel: dict[str, list[dict]] = {}
    for r in rows:
        by_sel.setdefault(r.get("selector") or r.get("correct_element") or "?", []).append(r)

    out: list[dict] = []
    for sel, group in by_sel.items():
        group.sort(key=lambda r: float(r.get("created_at", 0)), reverse=True)
        labels = {(g.get("correct_label") or "").lower() for g in group if g.get("correct_label")}
        newest = group[0]
        conflicting = len(labels) > 1
        out.append({
            "selector": sel,
            "correct_label": newest.get("correct_label", ""),
            "previous_label": newest.get("agent_prediction", ""),
            "role": newest.get("role", ""),
            "accessible_name": newest.get("accessible_name", ""),
            "element_text": newest.get("element_text", ""),
            "confidence": round(max(float(g.get("confidence", 0.7)) for g in group), 2),
            "count": len(group),
            "verified": any(g.get("verified") for g in group),
            "conflicting": conflicting,
            "same_page": newest.get("page") == page,
        })
    out.sort(key=lambda c: (c["same_page"], not c["conflicting"], c["confidence"]), reverse=True)
    return out[:MAX_CORRECTIONS]


def match_corrections_to_candidates(corrections: list[dict], candidates: list[dict]) -> dict[str, dict]:
    """selector -> correction, matched by exact selector or by (role + name + text) signature."""
    cand_by_sel = {c.get("selector"): c for c in candidates if c.get("selector")}
    matched: dict[str, dict] = {}
    for corr in corrections or []:
        if corr.get("conflicting"):
            continue  # contradictory user feedback -> don't rank on it (Step 10.8)
        sel = corr.get("selector")
        if sel in cand_by_sel:
            matched[sel] = corr
            continue
        sig = (corr.get("role", ""), corr.get("accessible_name", "").lower(), corr.get("element_text", "").lower())
        if not any(sig):
            continue
        for c in candidates:
            csig = (c.get("role", ""), (c.get("name") or "").lower(), (c.get("text") or "").lower())
            if csig == sig and c.get("selector"):
                matched[c["selector"]] = {**corr, "selector": c["selector"], "rematched": True}
                break
    return matched


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
        lines.append("Past USER CORRECTIONS on this site (the user explicitly said REACH "
                     "was wrong - weight these heavily when the goal matches the label):")
        for c in mem["corrections"]:
            if c.get("conflicting"):
                lines.append(f"  - {c['selector']}: the user has given CONFLICTING labels "
                             f"here - do NOT rely on memory, verify visually.")
            else:
                lines.append(
                    f"  - {c['selector']} = '{c['correct_label']}'"
                    f" (was thought to be '{c['previous_label'] or '?'}';"
                    f" {'verified, ' if c.get('verified') else ''}conf {c['confidence']}, seen {c['count']}x)"
                )
    if mem.get("preferences"):
        lines.append("User preferences:")
        for p in mem["preferences"]:
            lines.append(f"  - {p['preference']} = {p['value']}")
    if mem.get("recent_tasks"):
        lines.append("Recent tasks here: " + "; ".join(
            f"{t['goal']} -> {t['result']}" for t in mem["recent_tasks"]))
    return "\n".join(lines) if lines else "(no memory of this site)"
