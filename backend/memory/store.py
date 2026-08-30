"""Firestore-backed memory store with an in-memory fallback (Phase 9).

Same DB as sessions ('reach-memory'), collections:
  page_memory  correction_memory  preference_memory  task_history
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Optional

log = logging.getLogger("reach.memory")

DATABASE = os.environ.get("REACH_FIRESTORE_DB", "reach-memory")
COLLECTIONS = ("page_memory", "correction_memory", "preference_memory", "task_history")


class _InMemory:
    kind = "memory"

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {c: {} for c in COLLECTIONS}
        self._lock = threading.Lock()

    def add(self, collection: str, doc: dict, doc_id: Optional[str] = None) -> str:
        doc_id = doc_id or uuid.uuid4().hex
        with self._lock:
            self._data[collection][doc_id] = dict(doc)
        return doc_id

    def set(self, collection: str, doc_id: str, doc: dict) -> None:
        with self._lock:
            self._data[collection][doc_id] = dict(doc)

    def query(self, collection: str, where: Optional[dict] = None) -> list[dict]:
        with self._lock:
            rows = list(self._data[collection].values())
        if where:
            rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
        return [dict(r) for r in rows]


class _Firestore:
    kind = "firestore"

    def __init__(self) -> None:
        from google.cloud import firestore

        self._db = firestore.Client(database=DATABASE)

    def add(self, collection: str, doc: dict, doc_id: Optional[str] = None) -> str:
        if doc_id:
            self._db.collection(collection).document(doc_id).set(doc)
            return doc_id
        ref = self._db.collection(collection).document()
        ref.set(doc)
        return ref.id

    def set(self, collection: str, doc_id: str, doc: dict) -> None:
        self._db.collection(collection).document(doc_id).set(doc)

    def query(self, collection: str, where: Optional[dict] = None) -> list[dict]:
        col = self._db.collection(collection)
        if where:
            for k, v in where.items():
                col = col.where(k, "==", v)
        return [d.to_dict() | {"_id": d.id} for d in col.limit(200).stream()]


_store = None


def get_store():
    global _store
    if _store is not None:
        return _store
    if os.environ.get("REACH_SESSION_BACKEND", "firestore").lower() == "memory":
        log.info("[memory] using in-memory store")
        _store = _InMemory()
        return _store
    try:
        s = _Firestore()
        s._db.collection("page_memory").limit(1).get()  # surface auth errors now
        log.info("[memory] using Firestore store (db=%s)", DATABASE)
        _store = s
    except Exception as exc:  # noqa: BLE001
        log.warning("[memory] Firestore unavailable (%s) - using in-memory store", exc)
        _store = _InMemory()
    return _store
