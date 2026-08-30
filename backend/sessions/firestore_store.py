"""Session persistence (Phase 5, Step 5.15-5.16).

Firestore is the real backend (database "reach-memory", collection "sessions").
If Firestore is unreachable (no creds locally, missing IAM on Cloud Run) the
store falls back to an in-process dict so development still works - with a log
line so the downgrade is never silent.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

log = logging.getLogger("reach.sessions")

DATABASE = os.environ.get("REACH_FIRESTORE_DB", "reach-memory")
COLLECTION = "sessions"


class InMemorySessionStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.kind = "memory"

    def get(self, session_id: str) -> Optional[dict]:
        with self._lock:
            doc = self._data.get(session_id)
            return dict(doc) if doc else None

    def put(self, session_id: str, doc: dict) -> None:
        with self._lock:
            self._data[session_id] = dict(doc)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)


class FirestoreSessionStore:
    def __init__(self) -> None:
        from google.cloud import firestore  # imported lazily

        self._db = firestore.Client(database=DATABASE)
        self._col = self._db.collection(COLLECTION)
        self.kind = "firestore"

    def get(self, session_id: str) -> Optional[dict]:
        snap = self._col.document(session_id).get()
        return snap.to_dict() if snap.exists else None

    def put(self, session_id: str, doc: dict) -> None:
        self._col.document(session_id).set(doc)

    def delete(self, session_id: str) -> None:
        self._col.document(session_id).delete()


_store = None


def get_store():
    """Singleton store. Tries Firestore once, falls back to memory on failure."""
    global _store
    if _store is not None:
        return _store

    backend = os.environ.get("REACH_SESSION_BACKEND", "firestore").lower()
    if backend == "memory":
        log.info("[sessions] using in-memory store (REACH_SESSION_BACKEND=memory)")
        _store = InMemorySessionStore()
        return _store

    try:
        _store = FirestoreSessionStore()
        # touch the collection so credential/permission errors surface now
        _store._col.limit(1).get()
        log.info("[sessions] using Firestore store (db=%s, collection=%s)", DATABASE, COLLECTION)
    except Exception as exc:  # noqa: BLE001
        log.warning("[sessions] Firestore unavailable (%s) - falling back to in-memory store", exc)
        _store = InMemorySessionStore()
    return _store
