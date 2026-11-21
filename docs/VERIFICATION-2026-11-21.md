# ContextIQ verification — 21 November 2026

This is a fictional-data hackathon prototype. Passing automated tests does not certify banking readiness or prove that every device/browser works. The original upstream repository is unchanged; this work targets the V2 repository.

## Changes in this release

- Glass navigation, cards and widgets preserve the existing routes and green identity. Mobile navigation includes safe-area spacing, with reduced-transparency and reduced-motion fallbacks.
- Tara has browser-local width (280–520 px), text (12–18 px), and maximum-height (35–85% of screen) controls. The tour remains dismissible and fits smaller screens.
- Charts use actual recorded day-end balances, stepped changes, exact-value pointer/keyboard inspection, daily source values and 7/30/90-day selection. The axis is explicitly auto-ranged. Forecasts are labelled projections. Changing the chart range does not change the monthly savings baseline.
- Home shows workspace-specific automation counts, saved explanations, commitments, planned savings, scheduled-check status, provider disclosure and privacy controls. Rules and optional LLM work are distinguished.
- Generated invoice QR images contain an HTTPS app link and compact HMAC-protected invoice reference. The link opens Scan & Pay with the code populated, even before starting a demo. It removes the code from the displayed URL. Scanning does not authorize payment, transfer a session or grant access to another workspace. Expiry, invoice status and ownership are checked server-side.

## Automated evidence

Local results: **130 checks passed**, no failures: V2 37, seller 24, operations 15, legacy 42, chart/payment-entry/tour JavaScript 12. Both website builds and Python/JavaScript syntax checks passed. The upstream LangSmith dependency emits deprecation warnings on Python 3.14; these are not test failures.

The GitHub `Test` workflow additionally runs **three PostgreSQL 17 integration checks** and a real `pg_dump`/`pg_restore` comparison of ledger totals, saved agent runs, checkpoints and schema revision. Inspect the commit's [Actions results](https://github.com/Ganeshchaithanya/ContextIQ_V2.0-/actions) for the deployment gate and exact current result. No production database access was opened for these tests.

Stress and failure cases include sixteen simultaneous attempts to consume one approval (one allow, fifteen deny); sixteen concurrent PostgreSQL consumers for sixteen distinct jobs; retry/dead-letter and crashed-lease recovery; double-capture/replay prevention; amount-bound refunds; unknown-state rejection; QR tampering, expiry, replacement, cancellation and cross-workspace access. These are bounded contention checks, not a sustained high-traffic benchmark or an independent penetration test.

The actual bundled JavaScript QR encoder is decoded with ZXing at three image sizes. Chart tests cover irregular date gaps, negative/zero/flat/single-day balances, malformed data, large amounts, exact source values and keyboard/pointer inspection. Tara tests cover persistence, invalid preferences, clamps, mobile geometry, seven-step navigation, Skip/Escape and dialogs.

## Original 18 + 1 feature matrix

“Pass” below means the stated tested scope, not every possible external integration.

| Feature | Verdict | Evidence and practical limit |
| --- | --- | --- |
| 1. Buyer–supplier connection | Pass, demo scope | Signed message exchange, ownership, tamper/replay/revoked-key checks; both parties are simulated in one deployment. |
| 2. Personal/business context | Pass | Classification, saved preferences and account scoping. Final payment approval remains human. |
| 3. Transaction briefcase | Pass | Linked agreement, purchase lifecycle and evidence tests. |
| 4. Dynamic QR | Pass automated; phone unverified | Encoder/decoder, entry-route and ownership/state/security checks. A second phone does not inherit the originating private session. |
| 5. Adaptive security/privacy | Pass tested controls; production incomplete | CSRF, session isolation/revocation, approval concurrency, step-up lockout, forged identity and metadata boundaries tested. Demo confirmation codes are not independent MFA. Real OIDC/passkey enrollment and an independent security audit are not verified. |
| 6. Cart intelligence | Pass supported handoff | Separate store cart, signed review/checkout handoff and isolation tests. No claim of unrestricted access to third-party signed-in carts. |
| 7. Price monitoring | Pass supported sources; availability limited | Tracked structured product-page checks and observed-low logic. “Low” means since tracking began; free sleeping hosting cannot monitor continuously. |
| 8. Refunds/replacements | Pass simulated | Eligibility windows, exact partial refunds, replay prevention and lifecycle checked. No live-money refund executed. |
| 9. Provider payments | Disabled per request / simulated | PayPal sandbox/live is not enabled. Its original adapter remains regression-tested with mocks. Razorpay test integration requires configured test credentials; no live payment certification. |
| 10. Online/counter payment UX | Pass simulation; native handoff unverified | Methods, user approval, QR review and external UPI URI validation tested. Actual banking app handoff and settlement need a physical device and provider verification. |
| 11. Store terms | Pass supported extraction | Terms/category confidence, injection resistance and model regression checks. Unsupported/ambiguous text remains a limitation. |
| 12. Bills/obligations | Pass | Extraction, due dates, recurring advancement and budget effects checked. Humans confirm money paid/received. |
| 13. Dispute prevention | Pass simulated | Mismatches, evidence, mandates and dispute drafts checked. Original PayPal dispute adapter is mock-tested; no current live/sandbox claim is made. |
| 14. Payment recovery | Pass simulated | Interrupted response, reconciliation and single settlement checked. External provider outage behavior is tested through controlled failures. |
| 15. Adaptive home/reminders | Pass logic; visual review unverified | Priority ordering, daily checklist persistence, deduplicated urgency, automatic tour and size controls checked. Apple-inspired rendering requires desktop/iPhone visual review. |
| 16. Proof of intent | Pass | Fingerprint/version/amount/recipient binding, signed mandate and mismatch rejection tested. |
| 17. Tara answers/guide | Pass supported intents | Financial analysis, reproducible metrics, evidence ownership, persisted runs/checkpoints, scope replies and tour checked. LLM answers remain fallible; voice/microphone permissions need device testing. |
| 18. Budgeting/planning | Pass | Receipts/purchases/bills propagate to shared balances, savings, affordability and forecasts; automatic long-term purchase plans and manual overrides tested. Estimates are not guarantees. |
| +1. Investment intelligence | Pass fixture logic; external data unverified | Research/diversification logic is tested against fixtures. Fresh market feeds require their configured provider and separate verification. Educational prototype only. |

Small-business additions also pass: client creation, itemized totals, draft/send/cancel, aging, partial/full receipts, overpayment/duplicate-reference rejection, 30/60/90-day cash scenarios, recurring bills, plain-language reminders and source-reviewed knowledge guides.

## Remaining manual checks

Browser control was unavailable in this chat. Therefore desktop/iPhone visual rendering, physical camera scanning, native UPI launch, speech permissions and assistive-technology behavior are **unverified**, not passed. Use fictional data when checking them.

Free Render hosting can sleep; durable jobs resume after waking. Demo sessions are not production identity. Payments remain simulated; real provider credentials, independent MFA, external telemetry and an always-on worker are not activated by these UI changes. Keep the existing managed PostgreSQL deployment; this release does not migrate storage.
