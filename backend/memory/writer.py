"""Memory writer - turns pipeline outcomes into stored knowledge (Phase 9).

Nothing here is called on a guess: page knowledge is only *strengthened* after a
Phase 8 VERIFIED, and *weakened* after a FAILED (Steps 9.6, 9.18, 9.19).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .models import CorrectionMemory, PageMemory, PreferenceMemory, TaskHistory
from .store import get_store
from .util import domain_of, page_of

log = logging.getLogger("reach.memory")

# id for a page-memory row is stable per (domain, page, selector) so repeats update.
def _pm_id(domain: str, page: str, selector: str) -> str:
    key = f"{domain}|{page}|{selector}".lower()
    return "pm_" + "".join(c if c.isalnum() else "-" for c in key)[:180]


class MemoryWriter:
    def __init__(self) -> None:
        self._store = get_store()

    # -- page knowledge ------------------------------------------------- #

    def _get_page(self, domain: str, page: str, selector: str) -> Optional[dict]:
        rows = self._store.query("page_memory", {"domain": domain, "page": page, "selector": selector})
        return rows[0] if rows else None

    def learn_page_element(self, url: str, selector: str, element: str,
                           description: str = "", confidence: float = 0.9) -> None:
        if not selector:
            return
        domain, page = domain_of(url), page_of(url)
        existing = self._get_page(domain, page, selector)
        hits = (existing or {}).get("hits", 0) + 1
        misses = (existing or {}).get("misses", 0)
        pm = PageMemory(
            domain=domain, page=page, element=element or "element", selector=selector,
            description=description or (existing or {}).get("description", ""),
            verified=True,
            confidence=min(0.99, max(confidence, (existing or {}).get("confidence", 0.5), 0.9)),
            hits=hits, misses=misses, updated_at=time.time(),
        )
        self._store.set("page_memory", _pm_id(domain, page, selector), pm.model_dump())
        log.info("[MEMORY] learned page_memory %s=%s (verified, conf=%.2f, hits=%d)",
                 element, selector, pm.confidence, hits)

    def weaken_page_element(self, url: str, selector: str) -> None:
        if not selector:
            return
        domain, page = domain_of(url), page_of(url)
        existing = self._get_page(domain, page, selector)
        if not existing:
            return
        misses = existing.get("misses", 0) + 1
        conf = max(0.1, existing.get("confidence", 0.5) - 0.3)
        existing.update(verified=conf >= 0.6, confidence=conf, misses=misses, updated_at=time.time())
        self._store.set("page_memory", _pm_id(domain, page, selector), existing)
        log.info("[MEMORY] weakened page_memory %s (conf=%.2f, misses=%d)", selector, conf, misses)

    # -- corrections (Phase 10) ------------------------------------- #

    _STRENGTH_CONF = {"weak": 0.6, "normal": 0.78, "strong": 0.9}

    def record_correction(
        self,
        url: str,
        *,
        selector: str,
        correct_label: str,
        agent_prediction: str = "",
        user_said: str = "",
        strength: str = "normal",
        role: str = "",
        accessible_name: str = "",
        element_text: str = "",
        user_id: str = "demo-user",
    ) -> dict:
        domain, page = domain_of(url), page_of(url)
        # repeated CONSISTENT correction -> strengthen; contradictory -> keep both
        prior = self._store.query(
            "correction_memory",
            {"user_id": user_id, "domain": domain, "page": page, "selector": selector},
        )
        same = [p for p in prior if (p.get("correct_label") or "").lower() == correct_label.lower()]
        conf = self._STRENGTH_CONF.get(strength, 0.78)
        if same:
            conf = min(0.97, conf + 0.08 * len(same))  # consistent repeats -> up

        c = CorrectionMemory(
            user_id=user_id, domain=domain, page=page, selector=selector,
            role=role, accessible_name=accessible_name, element_text=element_text,
            agent_prediction=agent_prediction, correct_label=correct_label,
            user_said=user_said, strength=strength, confidence=round(conf, 2),
        )
        doc_id = self._store.add("correction_memory", c.model_dump(exclude={"agent_assumed", "correct_element"}))
        log.info("[CORRECTION] persisted %s: %r was %r -> correct %r (strength=%s conf=%.2f%s)",
                 selector, domain, agent_prediction or "?", correct_label, strength, conf,
                 ", repeat" if same else "")
        return {"id": doc_id, "selector": selector, "correct_label": correct_label,
                "previous_label": agent_prediction, "confidence": round(conf, 2)}

    def mark_correction_verified(self, url: str, selector: str,
                                 user_id: str = "demo-user") -> None:
        """A VERIFIED action on this element confirms the user's correction (Step 10.21)."""
        domain, page = domain_of(url), page_of(url)
        rows = self._store.query(
            "correction_memory",
            {"user_id": user_id, "domain": domain, "page": page, "selector": selector},
        )
        for r in rows:
            if not r.get("_id") or r.get("verified"):
                continue
            r["verified"] = True
            r["confidence"] = min(0.98, float(r.get("confidence", 0.8)) + 0.05)
            self._store.set("correction_memory", r["_id"], {k: v for k, v in r.items() if k != "_id"})
            log.info("[CORRECTION] %s -> %r confirmed by VERIFIED action",
                     selector, r.get("correct_label"))

    # -- preferences ----------------------------------------------- #

    def set_preference(self, preference: str, value: Any) -> None:
        p = PreferenceMemory(preference=preference, value=value)
        self._store.set("preference_memory", "pref_" + preference, p.model_dump())
        log.info("[MEMORY] set preference %s=%r", preference, value)

    # -- task history -------------------------------------------- #

    def record_task(self, session_id: str, goal: str, url: str,
                    actions: list[dict], result: str) -> None:
        t = TaskHistory(
            session_id=session_id, goal=goal, domain=domain_of(url), page=page_of(url),
            actions=actions or [], result=result,
        )
        self._store.add("task_history", t.model_dump())
        log.info("[MEMORY] recorded task_history goal=%r result=%s", goal, result)

    # -- verification-driven convenience (Step 9.19) ---------- #

    def apply_verification_outcome(self, *, session_id: str, goal: str, url: str,
                                   action: dict, verification: dict,
                                   element_label: str = "") -> None:
        status = (verification or {}).get("status", "")
        target = (action or {}).get("target")
        self.record_task(session_id, goal, url,
                         actions=[action] if action else [], result=status)
        if status == "VERIFIED" and target:
            self.learn_page_element(url, target, element_label or goal[:40])
        elif status == "FAILED" and target:
            self.weaken_page_element(url, target)
        # AMBIGUOUS / BLOCKED -> task history only, no strengthening (Step 9.19)
