# ContextIQ V2 verification

## Local review build

The V2 test suite passed **19 tests** and the original suite passed **42 tests**. Each suite reported 13 upstream LangSmith deprecation warnings. All 19 frozen files match their baseline SHA-256 hashes. Reports: [V2 test results](docs/vibex/v2-tests.xml) and [original regression results](docs/vibex/regression-tests.xml).

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2.py -o addopts= -q -p no:cacheprovider
$env:CONTEXTIQ_LEGACY_TEST_AUTH = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_flows.py -o addopts= -q -p no:cacheprovider
Remove-Item Env:CONTEXTIQ_LEGACY_TEST_AUTH
```

| Scenario | Evidence |
| --- | --- |
| Account boundaries | Tests verify header spoofing is ineffective, cross-session records and QR are denied, CSRF and cross-origin writes are rejected, and reset is isolated. |
| Financial correctness | Tests verify opening/income/outflow reconciliation, chart close, EMI rounding, business scope, single capture on concurrent requests, and explicit receivable settlement. A legacy-shaped SQLite migration preserved USD/INR amounts and reapplied idempotently. |
| QR and payment | Tests verify review before payment, tamper/expiry/version rejection, lost-response recovery, and one settlement. Browser verified catalog, ₹999 warning, ₹501 alternative, QR image and explicit mock confirmation. |
| Ownership and evidence | Browser verified delivery two days earlier, five replacement days, request and seller approval in the briefcase. API tests also cover concurrent settlement, partial delivery and two equal-value refunds. |
| Persistence and responsive UI | The same browser session showed the updated ₹4,001 after the local service restarted. All five mobile tabs were visible at 375px. [Preview screenshot](docs/vibex/local-preview.jpg). |
| Language and agent guidance | The suite checks ten questions each in English, Hindi and Kannada. Browser verified Hindi and Kannada preferences and a Kannada answer tied to the persisted ledger. |
| Separate cart and checkout | Browser verified both BrightMart handoffs and that the shop's cart survives tracking. Tests confirm that tracking creates no invoice and that a tracking snapshot cannot create a checkout. |
| Price monitoring | Fixture prices verified that ₹1,699 triggers a single new-low notification against ₹1,999 and links to the item. The browser verified BrightMart publishes its product price. A checked public retailer page did not expose a price that this parser could use. |
| Payment methods | Browser verified the method chooser. Tests verify the external UPI URL, Razorpay signature failure, mismatched amount rejection, and one settlement after a matching captured test response fixture. A real gateway account was not used. |
| Kirana checklist | Browser verified the fresh business workspace, all three tasks, exact record navigation, persistence after reload, and automatic advancement. Tests verify that completing a task leaves the bill open. [Checklist preview](docs/vibex/kirana-daily-tasks.jpg). |
| Reminder priority | Tests verify that an unresolved payment and imminent deadlines outrank price drops and savings goals. Browser checks confirmed a routine task stayed in the list, only one row was highlighted after completion, and a due-today pop-up did not repeat after reload. [Reminder preview](docs/vibex/priority-reminder.jpg). |

Real sandbox and live checkout, device speech and camera, PostgreSQL, production scale, and full accessibility conformance were not verified. The [V2 API and data flow](docs/vibex/API_V2.md) lists preview limits.

## Phase 0 baseline — 15 November 2026

Source commit `c2e6b1c633cb39ab88d2759d060e1e80c2372ed2`. Environment is Windows, Python 3.14.6, pinned `requirements-dev.txt`, SQLite and mock payments. Optional PyTorch/LoRA dependencies were not installed, so policy inference used the existing TF-IDF fallback.

### Existing regression suite

Command run from the V2 working copy with its virtual environment.

```powershell
.venv\Scripts\python.exe -m pytest -o addopts= -q -rA --junitxml=docs/vibex/baseline-tests.xml
```

Actual final output.

```text
42 passed, 13 warnings in 19.02s
```

The warnings concern LangSmith's use of deprecated `asyncio.iscoroutinefunction`. The first sandboxed run had 33 passes and 9 failures. Eight failures raised Windows named-pipe permission errors, and one voice assertion failed after the same restricted inference path. The unchanged suite passed when rerun with approved access outside the sandbox.

- [Successful complete test output](docs/vibex/baseline-tests.txt)
- [Successful JUnit results](docs/vibex/baseline-tests.xml)
- [Initial sandbox output](docs/vibex/baseline-tests-sandbox.txt)
- [Initial sandbox JUnit results](docs/vibex/baseline-tests-sandbox.xml)

### Targeted baseline reproduction

The audit probe uses a unique database and the original mock payment flow. Its source is [baseline_probe.py](docs/vibex/baseline_probe.py), with [actual JSON results](docs/vibex/baseline-probe-results.json).

```powershell
.venv\Scripts\python.exe docs\vibex\baseline_probe.py
```

| Observation | Actual result |
| --- | --- |
| Profile request without identity | HTTP 200 |
| Same client with `X-User-Id: alex` | HTTP 200, Alex Rivera |
| Same client with `X-User-Id: brightmart` | HTTP 200, BrightMart |
| Mock payment | Captured USD 12.50 |
| Ledger movement | Exactly one expense of 12.50 for the new case |
| Monthly spending | 1370.43 before, 1382.93 after |
| Available balance | 1450.00 before and after capture |
| Created notice states | `delivered`, with no external channel confirmation in the source path |
| Metrics request without identity | HTTP 200 |

The probe initially encountered the same named-pipe sandbox restriction and completed after an approved rerun outside the sandbox. The financial values above are synthetic baseline USD records.

### Other checks

- `node --check` passed for `app/static/app.js`, `app/static/console.js` and `extension/popup.js`.
- All 19 committed files in `app/ml/models` matched their pre-test SHA-256 hashes. See [hash manifest](docs/vibex/model-hashes-before.json) and [comparison result](docs/vibex/model-integrity-result.json).
- Original clone status was clean at the audited commit after testing.
- V2 tracked application source matches the baseline. Changes are audit documentation, evidence, the audit probe and the README development entry.

## Feature verification matrix

| Feature | Status | Evidence | Limitations |
| --- | --- | --- | --- |
| Mock checkout and capture | Existing implementation tested | Capture and gateway regression tests | Demo identity remains caller-controlled |
| Interrupted capture recovery | Existing implementation tested | `test_self_healing_no_double_charge` | Tests one lost-response scenario. Separate incidents and broader outage handling remain required |
| Signed authorization | Existing implementation tested | Mandate/gateway regression tests | Full V2 authorization review, concurrency and currency checks remain required |
| Signed QR | Existing implementation tested | Signature/replay and format tests | No V2 payment-vs-invoice lifecycle or immutable invoice versioning |
| Refunds and disputes | Existing implementation tested against mock | Refund, seller permission and dispute tests | Live sandbox and item-level partial refunds require further verification |
| Buyer/seller evidence and signed communication | Existing implementation tested | A2A, participant and temporal-graph tests | Authentic session identity still needs implementation |
| Cart policy and budgeting | Existing implementation tested | Cart, classification, bills and budget-related tests | Targeted probe confirms available-balance reconciliation gap |
| Ask, voice and routing | Existing implementation tested in English | Chat, voice and routing tests | Hindi/Kannada and browser microphone behavior remain unverified |
| Notice delivery | Persisted records observed | Probe and source review | Stored delivery status lacks delivery evidence |
| PayPal sandbox | Requires credentials and independent verification | Adapter source inspected | This audit executed mock transport only |
| Market research | Tested with existing fixture | Research/diversification test | Live market data unverified |
| Passkeys | Invalid-input rejection tested | Passkey regression test | Real device enrollment/authentication unverified |
| LoRA policy model | Existing artifacts retained | Hash comparison | Optional inference dependency uninstalled |
| V2 sessions, locales, unified account and ledger | Planned | Phase 1 implementation plan | Awaiting baseline gate |
| V2 frontend, BrightMart invoices and lifecycle | Planned | Phases 2–4 implementation plan | V2 browser test links pending implementation |
| V2 supervisor, notifications and advanced features | Planned | Phases 5–7 implementation plan | Background scheduling and three-language evaluation pending |

## Changed and added files

- `README.md`
- `CHANGES_VIBEX.md`
- `VERIFICATION.md`
- `docs/vibex/PHASE_0.md`
- `docs/vibex/API_BASELINE.md`
- `docs/vibex/baseline_probe.py`
- `docs/vibex/baseline-probe-results.json`
- `docs/vibex/baseline-tests.txt`
- `docs/vibex/baseline-tests.xml`
- `docs/vibex/baseline-tests-sandbox.txt`
- `docs/vibex/baseline-tests-sandbox.xml`
- `docs/vibex/model-hashes-before.json`
- `docs/vibex/model-integrity-result.json`

## Remaining verification and next phase

The existing suite passes in the verified environment. The source findings and targeted probe identify V2 gaps beyond that suite. Browser layout, mobile behavior, real sandbox credentials, PostgreSQL migrations, concurrency, multilingual accuracy, restart-safe recovery and the complete V2 story remain pending.

Next is Phase 1 after the baseline review required by section 37 of the supplied specification. The review can authorize Phase 1 alone or explicitly authorize several phases with verification at each stage.
