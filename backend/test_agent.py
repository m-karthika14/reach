"""Manual local test for /agent (Phase 2, Steps 2.9-2.10).

Start the server first:
    $env:GOOGLE_CLOUD_PROJECT = "reach-agent-507107"
    uvicorn main:app --reload --port 8080

Then, in another shell:
    python test_agent.py
"""

import json
import urllib.request

BASE = "http://127.0.0.1:8080"

DEMO_URL = "file:///K:/projects/reach/demo-site/index.html"

# A trimmed version of what the extension's getPageContext() produces.
DEMO_DOM = json.dumps(
    {
        "title": "REACH Demo Portal - Page A",
        "buttons": [
            {"text": "Pay Bill", "accessibleName": "Pay Bill", "id": "pay-button", "selector": "#pay-button"},
            {"text": "View Bill", "accessibleName": "View Bill", "id": "view-bill", "selector": "#view-bill"},
            {"text": "Submit", "accessibleName": "Submit", "id": "submit-btn", "selector": "#submit-btn"},
        ],
        "links": [{"text": "Go to Page B", "href": "page-b.html", "selector": "#to-page-b"}],
        "inputs": [
            {"tag": "input", "type": "email", "accessibleName": "Email", "id": "email", "selector": "#email"},
            {
                "tag": "select",
                "accessibleName": "Language",
                "id": "language",
                "selector": "#language",
                "options": [
                    {"value": "english", "label": "English"},
                    {"value": "kannada", "label": "Kannada"},
                    {"value": "hindi", "label": "Hindi"},
                ],
            },
        ],
        "visibleText": "Electricity Account  Bill: 1,240  Pay Bill  View Bill  Email  Language  Submit",
    }
)

CASES = [
    {"goal": "Open my electricity bill", "url": DEMO_URL, "dom": DEMO_DOM, "screenshot": None},
    {"goal": "Enter my email demo@example.com", "url": DEMO_URL, "dom": DEMO_DOM, "screenshot": None},
    {"goal": "Set the language to Kannada", "url": DEMO_URL, "dom": DEMO_DOM, "screenshot": None},
    {"goal": "Delete my account permanently", "url": DEMO_URL, "dom": DEMO_DOM, "screenshot": None},
]


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path) as resp:
        return json.loads(resp.read())


if __name__ == "__main__":
    print("GET /health ->", get("/health"))
    for case in CASES:
        print(f"\nGOAL: {case['goal']}")
        try:
            print("  ->", json.dumps(post("/agent", case), indent=2))
        except Exception as exc:  # noqa: BLE001
            print("  ERROR:", exc)
