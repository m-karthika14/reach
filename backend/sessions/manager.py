"""Session manager: load / reconcile / update / persist (Phase 5)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from .firestore_store import get_store
from .models import SessionState, Turn

log = logging.getLogger("reach.sessions")

HISTORY_KEEP = 12          # turns kept verbatim (Step 5.29)
CANDIDATE_LIMIT = 12
PAGE_TEXT_CAP = 1200


def new_session_id() -> str:
    return "sess_" + uuid.uuid4().hex[:12]


class SessionManager:
    def __init__(self) -> None:
        self._store = get_store()
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def backend_kind(self) -> str:
        return getattr(self._store, "kind", "unknown")

    def lock(self, session_id: str) -> asyncio.Lock:
        # Per-session serialization (Step 5.32). In-process only; a multi-instance
        # Cloud Run deployment would need Firestore transactions for strict safety.
        return self._locks.setdefault(session_id, asyncio.Lock())

    # -- load / save ----------------------------------------------------- #

    async def load(self, session_id: str | None) -> SessionState:
        if not session_id:
            return SessionState(session_id=new_session_id())
        doc = await asyncio.to_thread(self._store.get, session_id)
        if not doc:
            log.info("[sessions] %s not found - creating", session_id)
            return SessionState(session_id=session_id)
        try:
            return SessionState.from_doc(doc)
        except Exception as exc:  # noqa: BLE001
            log.warning("[sessions] %s corrupt (%s) - recreating", session_id, exc)
            return SessionState(session_id=session_id)

    async def save(self, state: SessionState) -> None:
        state.touch()
        await asyncio.to_thread(self._store.put, state.session_id, state.to_doc())

    async def delete(self, session_id: str) -> None:
        await asyncio.to_thread(self._store.delete, session_id)

    # -- state updates ------------------------------------------------- #

    def append_turn(self, state: SessionState, role: str, content: str) -> None:
        state.conversation_history.append(Turn(role=role, content=content))
        if len(state.conversation_history) > HISTORY_KEEP:
            state.conversation_history = state.conversation_history[-HISTORY_KEEP:]

    def reconcile_page(self, state: SessionState, url: str, dom: str) -> None:
        """Fresh browser observation wins over stored page state (Steps 5.49-5.50)."""
        page: dict[str, Any]
        try:
            page = json.loads(dom)
            if not isinstance(page, dict):
                page = {}
        except (json.JSONDecodeError, TypeError):
            page = {}

        text = page.get("visibleText") or ""
        state.current_page = {
            "url": url or page.get("url"),
            "title": page.get("title"),
            "visible_text": text[:PAGE_TEXT_CAP] if isinstance(text, str) else "",
        }
        state.current_candidates = self._extract_candidates(page)

    def _extract_candidates(self, page: dict) -> list[dict]:
        out: list[dict] = []
        for kind, key in (("button", "buttons"), ("link", "links")):
            for el in page.get(key, []) or []:
                if not isinstance(el, dict):
                    continue
                name = (el.get("accessibleName") or el.get("text") or el.get("ariaLabel") or "").strip()
                sel = el.get("selector") or (f"#{el['id']}" if el.get("id") else None)
                if name and sel:
                    out.append({"name": name, "selector": sel, "kind": kind})
        # de-dup by selector, keep order
        seen, deduped = set(), []
        for c in out:
            if c["selector"] in seen:
                continue
            seen.add(c["selector"])
            deduped.append(c)
        return deduped[:CANDIDATE_LIMIT]

    def record_execution(self, state: SessionState, last_executed: dict | None) -> None:
        if not last_executed:
            return
        state.previous_actions.append(last_executed)
        state.current_step += 1

    # -- prompt context ---------------------------------------------- #

    def history_text(self, state: SessionState) -> str:
        lines = [f"{t.role}: {t.content}" for t in state.conversation_history[-HISTORY_KEEP:]]
        return "\n".join(lines) if lines else "(no prior turns)"

    def actions_text(self, state: SessionState) -> str:
        if not state.previous_actions:
            return "(none)"
        return "\n".join(
            f"{i + 1}. {a.get('action')} {a.get('target') or ''}".strip()
            for i, a in enumerate(state.previous_actions[-10:])
        )

    def candidates_text(self, state: SessionState) -> str:
        if not state.current_candidates:
            return "(none)"
        return "\n".join(
            f"{i + 1}. {c['name']}  ->  {c['selector']}"
            for i, c in enumerate(state.current_candidates)
        )
