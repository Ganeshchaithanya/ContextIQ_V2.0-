# ContextIQ feature verification — 22 November 2026

This is a hackathon prototype verification, not a production security certification.
Automated checks use isolated fictional records and mock payment providers. A pass
means the described behavior passed those checks, not that every possible input or
external service has been verified.

## Feature results

| Feature | Automated result | Evidence and practical boundary |
| --- | --- | --- |
| Private demo session, CSRF and logout | PASS | Session isolation, missing CSRF rejection, revocation and owner-only access; demo identity is not production sign-in. |
| Personal/business scopes | PASS | Scope selection, unified totals and business-only obligations. The visible default persona remains Meera. |
| Connected cash ledger and budget | PASS | Receipts, purchases and bill payments update the same cash totals and allocation; unpaid receivables are not cash. |
| Recorded balance graph | PASS | 7/30/90-day reconciliation for every day; exact values; positive, negative, zero, flat and single-point ranges; invalid dates rejected. |
| Business cash forecast | PASS | Receipts, bills, negative dates, 30/60/90-day horizons and customer delay scenarios; stepped graph and inspectable daily figures. A projection is not a guarantee. |
| Automatic allocation and editable defaults | PASS | Bills and reserves precede affordable savings; defaults and user overrides do not post payments. |
| Planned purchase savings | PASS | Price-linked targets, shared savings capacity, fixed/automatic horizons including a year, pause/resume and reserve release after purchase. |
| Separate BrightMart/cart | PASS | Cart and checkout snapshot, watch list and purchase history remain separate from the finance application. |
| Price monitoring | PASS, provider mocked | Price extraction, low-price alert and outage retry paths. Every public store and continuous monitoring are not verified. Free hosting can sleep. |
| Bills, EMI and recurrence | PASS | Exact minor-unit rounding, scope, idempotent imports, payment recording and recurring due dates. |
| Customer/invoice management | PASS | Multi-line totals, draft/send/cancel, ownership and aging buckets. |
| Partial receipts and follow-ups | PASS | Partial/full receipts, overpayment rejection, duplicate references and UPI reminder amounts. Messages require the user to send them. |
| Human-approved checkout | PASS, simulated | Exact invoice fingerprint/version/amount, decline, method validation and step-up lockout. No live-money provider certification. |
| Duplicate/concurrent payment protection | PASS | 2, 8 and 20 simultaneous authorization submissions each settle once; retry/reconciliation and refunds retain exact amounts. |
| QR to app payment-code entry | PASS | Actual generated QR image decoded independently; HTTPS app link, escaped prefilled code, signature/version/expiry and cross-workspace denial. Client UPI QR also links to app entry. Physical phone camera testing remains unverified. |
| Post-purchase support | PASS | Delivery, return/replacement windows, warranties, partial refunds and evidence briefcase. Seller actions are simulated. |
| Tara answers and knowledge base | PASS | Recorded calculations, owned evidence, multilingual responses, reviewed source guides, model intent routing and safe fallback; external model tests use mocks. |
| Tara visual guide and to-do list | PASS | Automatic seven-step tour for first-time users only, manual Next/Back with no timer, replay and skip/Escape; minimize to a persistent message bubble and reopen the same step; drag and resize directly with the cursor; ask directly in the widget with owned evidence, cross-page conversation continuity and logout isolation; responsive spotlight, recommendation glow and anonymous code-entry cue. User pause/dismiss choices remain respected. |
| AI/privacy visibility | PASS | Collapsible impact panel retains its open/closed state when data refreshes.  Actual allocation/priorities/watch/run counts, routing provenance, heartbeat and question-text model opt-out. Opt-out persists when unrelated profile settings change. Generic predefined guide hints are separately disclosed. |

## Reliability and security checks

The suite additionally checks durable transaction/outbox atomicity, queue leases and
crash recovery, retry/dead-letter behavior, checkpoint resume without duplicate
conversations, fail-closed financial states, bounded circuit recovery, operator-only
metrics, metadata-only tracing, forged OIDC rejection, repeatable migrations and
backup/restore. PostgreSQL integration and a PostgreSQL backup/restore drill run in
CI against an isolated PostgreSQL 17 service. Hosted QR signing now derives a stable,
domain-separated key from the persistent server secret, with a regression check for
restart stability and rejection of weak secrets.

Test inventory: 35 purchase/budget checks, 24 seller checks, 15 operations checks,
42 legacy flow checks, 6 experience checks, 2 PostgreSQL integration checks and
31 JavaScript checks: **155 automated checks**, plus builds and the restore drill.
Python files run in separate processes because each owns its test database settings.

## Verification limits

- Browser rendering and physical iPhone/Android camera scans need human confirmation;
  local browser automation was unavailable in this chat. DOM/canvas checks are automated.
- Opening a signed private invoice link does not transfer an authenticated workspace
  to another phone. Another browser must already have the owning session to review it.
  External UPI requests can be reviewed in the app before opening a compatible UPI app.
- Real payment capture, external UPI confirmation, independent production MFA/OIDC,
  optional trace exporters and continuous always-on monitoring are not active end-to-end
  production integrations. Do not describe them as passed live features.
- Cloud model availability can change; deterministic financial calculations and
  record-backed assistance remain available without model classification.
- At the owner's request, the application uses local SQLite on the free Render web
  service. Its data and checkpoints can reset on a restart or redeploy; start a fresh
  demo session afterward. The previous PostgreSQL database is left untouched and is
  not used by the application. No paid disk or new database was provisioned.
- This run is not a load-capacity benchmark or penetration test. High-concurrency
  payment assertions cover correctness in the tested environment, not unlimited scale.

The expanded Linux CI stress check initially exposed pool starvation at 20 concurrent
submissions. The fix queues mutations asynchronously before connection checkout and
performs session validation outside the request event loop; the regression retains
all 20 submissions rather than reducing the test load.


## Movable inline Tara widget

The widget is available on all ContextIQ page routes, welcome, onboarding and page
errors. It pauses behind modal dialogs so their keyboard focus remains contained.
Drag the header or minimized bubble to any position or corner, and drag
the resize grip (arrow keys also work). There are no Dock or Reset settings. Only geometry is saved in browser storage.
The current conversation and draft stay in memory across page changes and clear on
session changes. Questions use the same authenticated, privacy-aware `/api/v2/ask`
endpoint and evidence renderer as the dedicated Ask page. Welcome help is local
navigation guidance and does not call the model or read private records.

The widget does not inject into the separate BrightMart website or arbitrary third-
party sites. It does not authorize payments. Browser/device interaction still needs
a physical UI check; DOM, pointer, keyboard, boundary, privacy and API paths are covered
by the automated checks described above.
