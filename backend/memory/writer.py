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

    # -- corrections -------------------------------------------------- #

    def record_correction(self, url: str, user_said: str, agent_assumed: str,
                          correct_element: str, reason: str = "user correction") -> None:
        c = CorrectionMemory(
            domain=domain_of(url), page=page_of(url), user_said=user_said,
            agent_assumed=agent_assumed or "", correct_element=correct_element, reason=reason,
        )
        self._store.add("correction_memory", c.model_dump())
        log.info("[MEMORY] recorded correction on %s: assumed %r -> correct %r",
                 c.domain, agent_assumed, correct_element)

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
