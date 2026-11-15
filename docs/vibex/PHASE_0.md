# ContextIQ V2 baseline review

Audited on 15 November 2026 against commit `c2e6b1c633cb39ab88d2759d060e1e80c2372ed2`.

The baseline regression suite passed all 42 tests with 13 dependency deprecation warnings in 19.02 seconds after rerunning outside the Windows sandbox. The model/configuration hash comparison matched all 19 files. Full results, limitations and a targeted identity/accounting reproduction are in `../../VERIFICATION.md`.

## Project conditions

| Condition | Current evidence |
| --- | --- |
| Reuse permission | User confirmed organizer approval in this chat |
| Deadline and available time | User will supply the deadline |
| Implementation location | Separate local copy at `[workspace]`, branch `vibex-redesign` |
| Developer responsibilities | Codex performs the authorized engineering work. User reviews the application and approves final deployment |
| External credentials | Credential availability has not been confirmed. Baseline tests force mock payments and disable external LLM calls |
| Preview environment | Local Windows, Python 3.14.6, SQLite and mock provider |
| Final hosting | To be selected after local review. Existing source contains a Render configuration |
| Visual reference | Written black, white and apple-green specification supplied. Separate approved screenshot has not been supplied |
| Phase approval | Phase 0 baseline review precedes implementation under section 37 |

## Existing architecture

The application serves plain HTML, CSS and JavaScript through FastAPI. SQLAlchemy provides SQLite support and PostgreSQL URL normalization. `app/main.py` contains HTTP contracts, profile setup, payments, demo controls and static mounts. `app/orchestrator.py` uses LangGraph and existing specialist agents. `app/conversation.py` adds conversational routing. Memory retrieval, knowledge graphs, decision scoring, caching and adaptive presentation are implemented in `app/intelligence/`.

Checkout constructs a case, participant records, an agreement, a signed mandate and a provider order. Capture checks provider state, the mandate and the deterministic gateway before invoking reconciliation. A successful capture inserts a ledger expense and policy obligations. Briefcase views filter evidence by participant role. The existing mock transport exercises the PayPal-shaped adapter without external money movement.

```text
Browser app / store / extension
    -> FastAPI routes and current demo identity
    -> Specialists and LangGraph / permission-scoped retrieval
    -> SQLAlchemy cases, agreements, evidence, obligations and ledger
    -> Gateway and signed mandate -> PayPal adapter -> mock or sandbox
    -> Provider read / webhook -> case state -> ledger and briefcase
```

## Feature reuse map

| Area | Existing implementation | V2 extension required |
| --- | --- | --- |
| Checkout and cart | `app/agents/commerce.py`, `/api/cart/analyze`, `/api/checkout` | Server-owned invoices, item IDs, validated amounts, explicit review |
| Payments | `app/paypal/adapter.py`, `payments.py`, `mock.py` | Durable incidents, pending outcome handling, atomic ledger settlement |
| Authorization | `app/security/gateway.py`, `mandate.py`, `crypto.py` | Bind to server sessions and enforce exact currency, recipient and item snapshot |
| QR | `merchant_create_qr`, `buyer_scan_qr`, `app/agents/qr.py` | Separate payment and itemized QR records, immutable invoice versions, cancellation and regeneration |
| Briefcase | `app/briefcase.py`, case events, agreement and evidence tables | Product-level ownership, incident links and dedicated detail screens |
| Refund/dispute | Commerce resolution and dispute specialist modules | Item-level quantities and refund reconciliation, replacement workflow |
| Budget | `app/agents/budget.py`, ledger, budgets and obligations | Currency-aware authoritative balance, allocations, goals and EMI schedules |
| Onboarding | `User`, `/api/profile`, `/api/profile/setup` | Occupation, four configurations, locale, consent and feature preferences |
| Context | `app/agents/context.py`, `app/context.py`, payee memory | Explicit override precedence, transaction locks and unified account behavior |
| Connections | `app/a2a.py`, signed agent keys and message records | Tenant-scoped buyer/seller identities and shared invoice workflow |
| Ask and intelligence | LangGraph, specialists, memory, reasoning, adaptive layer | Shared observations, supervisor, three-language answers and exact action links |
| Notices | `OutboundNotice`, `/api/notices` | Drafts, inbox, explicit approval, accurate channel status and record links |
| Notifications | Insights plus browser-local read state | Persisted events, deduplication, scheduling and tenant-scoped state |
| Store | `demo_store/index.html` | BrightMart catalog and server-backed cart, invoices and seller order management |
| Optional integrations | Passkeys, extension, voice, MCP, market adapter | Preserve existing paths and surface only verified capabilities |
| Models | Committed joblib and policy artifacts | Preserve artifacts and inference configuration |

## Findings that affect the implementation

1. **Demo identity is caller-controlled.** `user_dep` defaults to `alex` and trusts `X-User-Id`. The voice endpoint reads that header independently. Existing participant filtering assumes an authentic user ID. Server-generated sessions and workspace scoping must cover every entry point.

2. **Reset and operational endpoints have shared scope.** In mock mode, `/api/reset` deletes records across users. `/api/users`, `/api/metrics`, cache controls and technical surfaces need appropriate authorization or scoped replacements. Reset also omits several related tables, so its consistency needs regression tests.

3. **Accounting has multiple representations.** `User.available_balance` is read directly by budget logic, while `_after_capture` adds a ledger expense without updating that field. The audit probe confirmed a USD 12.50 capture added exactly one expense while available balance stayed at USD 1450.00. `LedgerEntry.amount` is a Float and has no currency column. Existing balances and amounts require a provenance-aware migration before INR examples or cross-workspace totals can reconcile.

4. **QR scanning currently starts checkout.** The signed payload embeds items and policy text. `buyer_scan_qr` consumes the nonce and calls `start_checkout`, which records an approved agreement and issues a mandate. V2 needs a reviewable invoice snapshot before the explicit authorization step, with clear lifecycle and replay semantics.

5. **Payment recovery handles a specific interruption path.** It uses a stable capture request ID and reads provider state after a timeout. Recovery currently lives in case events rather than a separate incident table. A second transport failure during the status lookup can escape the handler. A pending capture must be tested so it cannot create a settled ledger entry or success message prematurely.

6. **Concurrency and partial refunds need additional coverage.** `_after_capture` uses a query-before-insert guard without a unique settlement key. Approval consumption is not a row-locked operation. Refund idempotency keys are derived from case and amount, so two legitimate equal-valued partial refunds need separate operation identities. These are source findings pending targeted reproductions.

7. **Notice status overstates delivery.** Creation and automatic sweeps write `status="delivered"` directly. Sweep text claims reserved cash or verified delivery without corresponding confirmation in that path. V2 should use persisted drafts and accurate in-app/channel states tied to evidence.

8. **Product and invoice data are incomplete for V2.** Agreement items are JSON records without stable item IDs. `Invoice` has an items list and provider reference but no immutable version model. There are no dedicated financing, installment, savings-goal, payment-incident or demo-workspace tables.

9. **The current store is Apex Marketplace.** Its checkout sends an encoded cart through the app URL. It has no backend invoice creation or seller management workflow. Existing BrightMart seed identities and QR demonstrations provide reusable foundations.

10. **Localization and proactive persistence require implementation.** The profile schema has no selected language or occupation. Notifications store seen state in localStorage and refresh insights on a browser interval. This does not establish persistent background scheduling.

11. **Model loading can trigger training if an artifact is missing.** `app/ml/runtime.py::_load` calls the training entry point on a missing joblib file. All seven named runtime model artifacts are present. Phase 1 should make missing frozen artifacts an explicit unavailable state. Baseline verification must compare artifact hashes before and after tests.

12. **Schema creation is not migration management.** `init_db` calls `Base.metadata.create_all`. V2 needs versioned, reversible migrations with existing-data checks for both supported databases.

## Implementation sequence and acceptance gates

| Phase | Reviewable result | Required evidence |
| --- | --- | --- |
| 1 | Server sessions, isolated personas/reset, onboarding/locales, workspace context and currency-aware ledger | Cross-session/header/record denial, reset scope, persistence, override precedence, unified-account totals and legacy migration |
| 2 | Apple-green desktop/mobile shell, Home chart, nested Budget, bills, goals and basic EMI | Ledger reconciliation, allocation arithmetic, context filtering and functional record links |
| 3 | Connected BrightMart catalog/cart/invoices and both QR workflows | Exact invoice totals, signature/expiry/replay tests, renewed review on changes, buyer/seller authorization |
| 4 | Before/During/After journey, exact approval, capture/recovery, History, incidents, ownership and replacement | One capture and one settlement under retry/concurrency, pending state, refund reconciliation and evidence continuity |
| 5 | Supervisor, persistent observations, Daily Focus, Ask, notices and voice fallback | At least 10 questions each in English/Hindi/Kannada, financial-fact preservation, scoped retrieval and correct destinations |
| 6 | Expanded EMI, partial fulfillment/refunds, business records and optional configured research | Targeted tests for each completed feature and regression of the main story |
| 7 | Review build and readiness evidence | Desktop/375px browser checks, keyboard and reduced motion, slow/offline behavior, restart persistence and final regression |

Planning estimate for one experienced engineer is approximately 12–22 working days for the essential integrated demo and verification, with another 7–15 days for the broader Phase 6 scope. These are provisional engineering estimates, not a delivery commitment. The confirmed deadline will determine prioritization within the supplied tiers.

The first complete acceptance journey uses Priya's seeded ₹6,000, ₹3,500 hostel commitment, ₹3,499 premium headphones and ₹1,999 alternative. All amounts, affordability decisions, invoice details, payment evidence and resulting balances must come from stored records. The same transaction must flow through interruption recovery, seller delivery simulation and a policy-supported replacement request.

## Preview and delivery plan

After implementation and verification, run the V2 application and connected store locally and provide their actual working URLs. User testing and requested revisions precede final deployment and submission. Public hosting, PayPal sandbox credentials, optional providers and submission materials require their corresponding later scope and verification.

The full original source remains attributable through Git history. `CHANGES_VIBEX.md` will record each implemented phase, `VERIFICATION.md` will link actual test output, and API/data-flow documentation will evolve with migrations and endpoints.
