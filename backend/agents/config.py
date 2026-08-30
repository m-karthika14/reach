"""Shared ADK / Gemini configuration for REACH agents.

Every agent uses the SAME model that was proven working in test_gemini.py:
    gemini-3.5-flash  on Vertex AI  in  asia-south1
"""

import os

# ADK reads these env vars to route Gemini calls through Vertex AI (not the
# public Gemini API). GOOGLE_CLOUD_PROJECT is supplied by the shell locally and
# by --set-env-vars on Cloud Run.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "asia-south1")

MODEL = "gemini-3.5-flash"

APP_NAME = "reach"
USER_ID = "reach-user"


def ensure_project() -> str:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set. "
            "Run:  $env:GOOGLE_CLOUD_PROJECT = 'reach-agent-507107'"
        )
    return project
