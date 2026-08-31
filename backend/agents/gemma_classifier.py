"""Gemma fast-filter - REACH's second Google model (Phase 14).

Pipeline position:

    STRUCTURE (Gemini 3.5 Flash, DOM/ARIA)
        -> candidate generation (every button/link on the page)
        -> **GEMMA relevance filter**  (this module)
        -> focused, ranked shortlist
        -> VISION / RECONCILIATION / ACTION (Gemini 3.5 Flash)

Gemma never acts on the page. It only scores how useful each on-page element is
for the user's goal, so the Gemini reasoning agents work over a small ranked
shortlist instead of every element. Gemma cannot *remove* an element that the
Structure Agent already flagged as relevant (that set is a floor), and any
failure - timeout, malformed JSON, model unavailable, missing credentials -
falls back to "keep every candidate". The pipeline is never worse off than it
was before Gemma existed.

Auth: Application Default Credentials via Vertex AI (`google-genai`,
`vertexai=True`). No API key, no credential file in the repo or image. The model
is served as MaaS on the Vertex AI "global" endpoint.

Config (all non-secret env vars, safe to pass via --set-env-vars):
    GEMMA_ENABLED         "1" (default) / "0" to bypass entirely
    GEMMA_MODEL           default "gemma-4-26b-a4b-it-maas"
    GEMMA_LOCATION        default "global"  (MaaS Gemma is global-only)
    GEMMA_TIMEOUT_S       default "8"
    GEMMA_MIN_CANDIDATES  default "6"  - below this, filtering is skipped
    GEMMA_KEEP_SCORE      default "0.3" - keep candidates scored >= this
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Optional

from pydantic import BaseModel

log = logging.getLogger("reach.gemma")

# google-genai emits a noisy INFO line on every generate_content call; keep our
# logs readable without hiding real errors.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

_FENCE = re.compile(r"```(?:json)?|```", re.IGNORECASE)
_ARRAY = re.compile(r"\[.*\]", re.DOTALL)

DEFAULT_MODEL = "gemma-4-26b-a4b-it-maas"
DEFAULT_LOCATION = "global"


class GemmaJudgement(BaseModel):
    selector: str
    score: float = 0.0
    reason: Optional[str] = None


class GemmaClassificationResult(BaseModel):
    """What Gemma decided about the candidate set for one page + goal."""

    used: bool                       # True only when Gemma actually shaped the shortlist
    model: str
    location: str = ""
    latency_ms: int = 0
    candidates_in: int = 0
    candidates_out: int = 0
    kept: list[str] = []             # selectors passed forward, most relevant first
    judgements: list[GemmaJudgement] = []
    fallback_reason: Optional[str] = None

    @property
    def kept_set(self) -> set[str]:
        return set(self.kept)

    def summary(self) -> dict[str, Any]:
        """Compact form for API responses / logs (no full judgement list)."""
        return {
            "used": self.used,
            "model": self.model,
            "location": self.location,
            "latency_ms": self.latency_ms,
            "candidates_in": self.candidates_in,
            "candidates_out": self.candidates_out,
            "kept": self.kept,
            "fallback_reason": self.fallback_reason,
        }


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def _short(value: Any, n: int = 48) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:n]


class GemmaClassifier:
    """Lazy, dependency-light wrapper around one Gemma MaaS call."""

    def __init__(self) -> None:
        self.enabled = _flag("GEMMA_ENABLED")
        self.model = os.environ.get("GEMMA_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.location = os.environ.get("GEMMA_LOCATION", DEFAULT_LOCATION).strip() or DEFAULT_LOCATION
        self.timeout_s = float(os.environ.get("GEMMA_TIMEOUT_S", "10") or 10)
        self.min_candidates = int(os.environ.get("GEMMA_MIN_CANDIDATES", "6") or 6)
        self.keep_score = float(os.environ.get("GEMMA_KEEP_SCORE", "0.3") or 0.3)
        self._client = None

    # -- infra ---------------------------------------------------------- #
    def _get_client(self):
        if self._client is None:
            from google import genai  # imported lazily so import of this module is cheap

            project = os.environ.get("GOOGLE_CLOUD_PROJECT")
            if not project:
                raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set (Gemma needs ADC + a project)")
            # vertexai=True -> Application Default Credentials, no API key.
            self._client = genai.Client(vertexai=True, project=project, location=self.location)
        return self._client

    def _passthrough(self, selectors: list[str], reason: str, *,
                     latency_ms: int = 0,
                     judgements: Optional[list[GemmaJudgement]] = None) -> GemmaClassificationResult:
        return GemmaClassificationResult(
            used=False, model=self.model, location=self.location, latency_ms=latency_ms,
            candidates_in=len(selectors), candidates_out=len(selectors),
            kept=list(selectors), judgements=judgements or [], fallback_reason=reason,
        )

    # -- the model call (runs in a worker thread) --------------------- #
    def _call(self, goal: str, candidates: list[dict], page_context: Optional[str]) -> str:
        from google.genai import types

        lines = "\n".join(
            f'{i + 1}. selector={c["selector"]!r} | role={c.get("role") or "?"} | '
            f'label={_short(c.get("name"))!r} | text={_short(c.get("text"))!r}'
            for i, c in enumerate(candidates)
        )
        valid_list = ", ".join(repr(c["selector"]) for c in candidates)
        ctx = f"\nPAGE CONTEXT: {_short(page_context, 160)}\n" if page_context else ""
        prompt = f"""You are a fast RELEVANCE FILTER for a web-automation agent that helps blind users.
You do NOT act on the page and you do NOT choose the final element. You only score
how useful each candidate element is as a step toward the goal.
{ctx}
GOAL: {goal}

CANDIDATE ELEMENTS (one per line):
{lines}

The ONLY valid values for the "selector" field are exactly these tokens:
{valid_list}

Return a JSON array. Include one object for every element that is PLAUSIBLY a step
toward the goal (when unsure, include it). Exclude only clearly unrelated items
(logout, cookie/consent banners, language pickers, unrelated marketing links).
Each object: {{"selector": <one token copied verbatim from the list above>, "score": <0.0-1.0>, "reason": "<= 8 words"}}
score 1.0 = directly achieves the goal; lower = a supporting step.
Output ONLY the JSON array - no prose, no markdown, no code fence."""

        resp = self._get_client().models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=1024),
        )
        return getattr(resp, "text", "") or ""

    @staticmethod
    def _parse(raw: str, valid: set[str]) -> list[GemmaJudgement]:
        text = _FENCE.sub("", raw or "").strip()
        match = _ARRAY.search(text)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out: list[GemmaJudgement] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            sel = str(item.get("selector") or "").strip()
            if sel not in valid:
                # Salvage the common case where the model echoed the whole
                # candidate line - recover an embedded known selector if exactly
                # one matches. Anything else is a model-invented selector and is
                # dropped so it can never reach the browser.
                embedded = [v for v in valid if v and re.search(rf"(^|[\s'\"=]){re.escape(v)}($|[\s'\"|,])", sel)]
                if len(embedded) == 1:
                    sel = embedded[0]
                else:
                    if sel:
                        log.info("[GEMMA] dropped selector not in candidate set: %r", sel)
                    continue
            if sel in seen:
                continue
            seen.add(sel)
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            reason = item.get("reason")
            out.append(GemmaJudgement(
                selector=sel, score=max(0.0, min(1.0, score)),
                reason=(str(reason)[:80] if reason else None),
            ))
        return out

    # -- public API -------------------------------------------------- #
    async def classify_candidates(
        self,
        goal: str,
        candidates: list[dict],
        page_context: Optional[str] = None,
        *,
        floor: Optional[set[str]] = None,
    ) -> GemmaClassificationResult:
        """Score `candidates` for `goal`; return a ranked, filtered shortlist.

        `candidates` are {selector, name, role, text} dicts (from the DOM).
        `floor` is a set of selectors that MUST survive (the Structure Agent's
        relevant_elements) - Gemma can rank/narrow but not veto them.
        Never raises: every failure path yields a passthrough result.
        """
        floor = {s for s in (floor or set()) if s}
        by_selector = {c["selector"]: c for c in candidates if c.get("selector")}
        selectors = list(by_selector)

        if not self.enabled:
            return self._passthrough(selectors, "disabled (GEMMA_ENABLED=0)")
        if len(selectors) < self.min_candidates:
            return self._passthrough(
                selectors, f"only {len(selectors)} candidates (< {self.min_candidates}); nothing to gain")

        try:
            t0 = time.perf_counter()
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._call, goal, list(by_selector.values()), page_context),
                timeout=self.timeout_s,
            )
            latency = round((time.perf_counter() - t0) * 1000)
        except asyncio.TimeoutError:
            log.warning("[GEMMA] fallback: timed out after %.1fs (model=%s)", self.timeout_s, self.model)
            return self._passthrough(selectors, f"timeout after {self.timeout_s}s")
        except Exception as exc:  # noqa: BLE001 - any SDK/auth/network error -> safe fallback
            log.warning("[GEMMA] fallback: %s: %s", type(exc).__name__, str(exc)[:200])
            return self._passthrough(selectors, f"{type(exc).__name__}: {str(exc)[:120]}")

        judgements = self._parse(raw, valid=set(selectors))
        if not judgements:
            log.warning("[GEMMA] fallback: no parseable judgements in model output")
            return self._passthrough(selectors, "unparseable model output", latency_ms=latency)

        ranked = sorted(judgements, key=lambda j: j.score, reverse=True)
        kept = [j.selector for j in ranked if j.score >= self.keep_score]

        # Structure-relevant elements are a floor: append any that Gemma scored
        # low or omitted, preserving page order for them.
        for sel in selectors:
            if sel in floor and sel not in kept:
                kept.append(sel)

        # Safety net: never starve the downstream Gemini agents.
        if len(kept) < 2 or len(kept) >= len(selectors):
            reason = "model kept too few" if len(kept) < 2 else "model kept everything"
            log.warning("[GEMMA] %s - widening to all %d candidates", reason, len(selectors))
            return self._passthrough(selectors, f"{reason}; widened", latency_ms=latency, judgements=ranked)

        log.info("[GEMMA] goal=%r  candidates %d -> %d  kept=%s  (%dms, model=%s @ %s)",
                 goal, len(selectors), len(kept), kept, latency, self.model, self.location)
        return GemmaClassificationResult(
            used=True, model=self.model, location=self.location, latency_ms=latency,
            candidates_in=len(selectors), candidates_out=len(kept),
            kept=kept, judgements=ranked,
        )


# Module singleton + functional helper -------------------------------- #
gemma_classifier = GemmaClassifier()


async def filter_candidates(
    goal: str,
    candidates: list[dict],
    page_context: Optional[str] = None,
    floor: Optional[set[str]] = None,
) -> GemmaClassificationResult:
    return await gemma_classifier.classify_candidates(goal, candidates, page_context, floor=floor)
