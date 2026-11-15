# V2 API and data flow

The browser shell and BrightMart run on separate origins. BrightMart has its own browser cart and shares a signed, ten-minute snapshot of product IDs and quantities only when the shopper selects Track or Continue to payment. Requests to `/api/v2` use a hashed session credential stored behind an HttpOnly cookie. Writes require the session CSRF token. The server selects the buyer and fictional seller associated with that session. The legacy header path is enabled only for the isolated original test run.

| Area | Routes under `/api/v2` | Source of record |
| --- | --- | --- |
| Session and setup | `/session`, `/profile`, `/reset` | Demo session and persisted preferences |
| Home and notifications | `/dashboard`, `/notifications/{id}/read` | Ledger, commitments and observations |
| Money and plans | `/history`, `/bills`, `/plans`, `/emi/compare`, `/forecast` | Currency-aware ledger, obligations and estimates |
| Store and QR | `/catalog`, `/cart`, `/invoices`, `/invoices/{id}`, `/scan` | Server catalog, immutable invoice versions and signed references |
| Cart Intelligence | `/watch`, `/watch/{id}/refresh`, `/store-cart/{review,track,checkout}` | Separate watchlist, observed prices and signed store handoff |
| Provider checkout | `/invoices/{id}/provider-order`, `/provider-confirm`, `/provider-status` | Razorpay test order, signed callback and matching provider capture |
| Payment | `/invoices/{id}/authorize`, `/invoices/{id}/reconcile`, `/incidents` | Gateway, provider, case, settlement and incident |
| Post-payment | `/purchases`, `/purchases/{id}/action`, `/purchases/{id}/refund`, `/briefcases/{id}`, `/merchant` | Item lifecycle, case timeline, evidence and seller ledger |
| Relationships and Ask | `/business`, `/notices`, `/ask` | Business records, in-app message states and record-backed LangGraph responses |

Cart prices and line quantities produce an immutable INR invoice. Its QR contains a signed workspace-scoped reference. A review supplies the exact fingerprint, version and explicit approval before the existing commerce service creates a provider order. A verified capture creates one buyer settlement and a matching seller sale. Post-payment records share the case identifier. Linked observations refresh from persisted records while the server is running. Ask and notices do not authorize payment.

`app/migrations.py` applies an additive version 1 migration on startup. It adds the ledger currency, integer minor units and unique settlement key. Currency is read from the linked case when available. Original standalone legacy records default to USD. The original amount is retained. Back up the database before migrating an existing instance. A rollback can restore the backup and the old code. SQLite is the verified preview database.

## Preview limits

- The mock provider works without credentials. Set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` on the ContextIQ server to enable Razorpay test checkout for UPI, cards and net banking. Hosted checkout uses the test account's method availability. The application checks the signed response and server-side captured amount, currency, order and method before writing the ledger. Live Razorpay keys are disabled in this fictional preview. Original PayPal adapter and sandbox code remain in the clone. INR checkout through PayPal is unavailable in this preview.
- A valid fixed-amount external UPI QR can open a compatible UPI app. No payment status or ledger entry is inferred from that handoff.
- Cart Intelligence checks tracked sources about every four hours while the preview is running. It reads explicitly tracked public product pages with a single supported structured offer, without access to signed-in carts. A low is measured from the first price stored for the same product, currency and source. It is not a market-wide historical claim.
- A preview session lasts seven days. Reset revokes its access and starts a new workspace. The earlier records remain in the local database.
- Ask uses deterministic, localized explanations of supported intents. Some interface and source evidence text remains in English. Speech and camera QR scanning depend on browser support and permissions. Clipboard QR paste works without camera access.
- EMI schedules use user-entered estimates on a 30-day basis. Real financing agreements, provider approvals, imports, and automatic financing cancellation are outside this preview.
- Delivery and replacement use simulated seller records. Partial fulfilment tracks quantities and uses the first line delivery date for the policy window. An independent per-unit policy clock is not implemented.
- Location, external notices, market research/news, production scheduling and public hosting are not configured.
