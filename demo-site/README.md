# REACH Energy — demo portal (Phase 13)

A polished, deliberately-inaccessible electricity portal + Razorpay **Test Mode**.
It merges into the existing REACH stack with **zero agent changes** — the agents
just see a page; Phase 8 verification just reads the receipt off `success.html`.

## Pages

| File | Purpose |
| --- | --- |
| `index.html` | dashboard — hero bill card + a **bare `💳` action** (`aria-label="button"`) + a 4-icon quick-actions row, all `aria-label="button"` |
| `bill.html` | bill detail (consumer no, due date, usage, previous bill) + Pay / History / an unlabelled ⬇︎ |
| `payment.html` | payment summary; the pay control is **injected per scenario** |
| `success.html` | receipt — **Transaction ID + Order ID + Receipt no.** → the evidence the Verification Agent reads |
| `styles.css` / `app.js` | shared design system + logic (backend URL, scenarios, Razorpay checkout, activity panel) |

## Why it's "inaccessible on purpose"

The human sees a credit-card icon; the DOM says `<button aria-label="button">💳`.
Structure gets almost nothing → **Vision** resolves it → **Reconciliation**
confirms → action. That's the whole point of Phases 6–7.

## Demo scenarios (top-right panel, or `?scenario=`)

| Scenario | payment.html exposes | REACH result |
| --- | --- | --- |
| `normal` | a clearly-labelled `💳 Pay ₹1,240` button | Structure confident → click → Razorpay |
| `vision` | icon-only `<button aria-label="button">💳` | Structure unsure → Vision → AGREE → click |
| `conflict` | `<button aria-label="Cancel">Pay Now` (looks like pay, named Cancel) | Structure "Cancel" vs Vision "Pay Now" → **CONFLICT → blocked** |
| `ambiguous` | `💳` → "Processing payment…" forever, no receipt | Verification → **AMBIGUOUS → no retry, no false success** |
| `success` | `💳` → instant receipt (skips checkout) | Verification → **VERIFIED** |

The **REACH activity** panel on every page shows the pipeline
(observe → memory → structure → vision → reconcile → action → execute → verify).
It is driven by real `reach:activity` CustomEvents from the content script when
REACH observes/acts, and by a labelled *demo-mode* simulation for the scenario.

## Razorpay — Test Mode, via the backend

Secrets never touch the browser. `payment.html` loads
`checkout.razorpay.com/v1/checkout.js` and:

```
Pay  ->  POST {backend}/payments/create-order {amount, consumer}
     ->  { order_id, amount(paise), currency, key_id, mock }      # key_id is the ONLY key the page sees
     ->  Razorpay Checkout (order_id)      [skipped if mock or checkout.js blocked]
     ->  handler(res)  ->  POST {backend}/payments/verify {order_id, payment_id, signature}
     ->  backend verifies the HMAC signature (real) / synthetic id (mock)
     ->  success.html?order_id=…   (receipt from sessionStorage)
```

Backend env (see `backend/.env.example`): `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`. **Unset → MOCK mode**, the demo still works fully
offline. `/` reports `payments_mode: real | mock`.
`POST /payments/webhook` verifies `X-Razorpay-Signature` and updates the
`payment_transactions` Firestore collection.

> The pasted keys are secrets — rotate them in the Razorpay dashboard and put
> only the **Key ID** anywhere near the frontend.

## Run

```powershell
# backend (mock payments is fine)
cd K:\projects\reach\backend ; ..\.venv\Scripts\Activate.ps1
$env:GOOGLE_CLOUD_PROJECT = "reach-agent-507107"
# optional real payments:
# $env:RAZORPAY_KEY_ID = "rzp_test_..." ; $env:RAZORPAY_KEY_SECRET = "..."
python -m uvicorn main:app --reload --port 8080
```

Open `demo-site/index.html` (a `file://` URL works). In the demo panel set
**Backend** to your local or Cloud Run URL. Load the REACH extension and drive it
by voice or chat.
