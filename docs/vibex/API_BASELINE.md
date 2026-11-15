# Baseline API contracts

Generated from `app/main.py` at the audited source commit. Function signatures identify request schemas and dependencies. The current `user_dep` trusts a caller-supplied demo header.

| Method | Route | Handler and dependencies | Source line |
| --- | --- | --- | --- |
| GET | `/` | `index()` | 118 |
| GET | `/{name}.html` | `google_site_verification(name: str)` | 124 |
| GET | `/checkout/return` | `paypal_return(case: str)` | 137 |
| GET | `/checkout/cancel` | `paypal_cancel(case: str)` | 142 |
| GET | `/api/config` | `config()` | 163 |
| GET | `/api/users` | `users(db=Depends(db_dep, scope='function'))` | 171 |
| POST | `/api/chat` | `chat(body: ChatIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 177 |
| POST | `/api/voice` | `voice(body: VoiceIn, x_voice_token: str=Header(''), x_user_id: str=Header('alex'), db=Depends(db_dep, scope='function'))` | 189 |
| POST | `/api/cart/analyze` | `cart_analyze(body: CartIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 209 |
| POST | `/api/checkout` | `checkout(body: CartIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 219 |
| POST | `/api/cases/{case_id}/capture` | `capture(case_id: str, body: CaptureIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 227 |
| GET | `/api/bills` | `bills(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 262 |
| POST | `/api/bills/{bill_id}/checkout` | `bill_checkout(bill_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 277 |
| GET | `/api/notices` | `get_notices(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 361 |
| POST | `/api/notices/auto-sweep` | `trigger_auto_sweep(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 370 |
| POST | `/api/notices` | `create_notice(body: NoticeIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 377 |
| POST | `/api/reset` | `reset_everything(x_admin_token: str=Header(''), db=Depends(db_dep, scope='function'))` | 405 |
| GET | `/api/recommendations` | `recommendations(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 436 |
| POST | `/api/cases/{case_id}/approve-mock` | `approve_mock(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 443 |
| POST | `/api/cases/{case_id}/simulate-drop` | `simulate_drop(case_id: str, body: CaptureIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 456 |
| POST | `/api/cases/{case_id}/ship` | `ship(case_id: str, body: ShipIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 475 |
| POST | `/api/disputes/sync` | `disputes_sync(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 494 |
| GET | `/api/cases/{case_id}/dispute` | `dispute_get(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 502 |
| GET | `/api/cases/{case_id}/dispute-readiness` | `dispute_readiness(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 509 |
| POST | `/api/cases/{case_id}/dispute/draft` | `dispute_draft(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 517 |
| POST | `/api/cases/{case_id}/dispute/submit` | `dispute_submit(case_id: str, body: DisputeSubmitIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 528 |
| POST | `/api/cases/{case_id}/dispute/accept` | `dispute_accept(case_id: str, body: DisputeAcceptIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 542 |
| POST | `/api/cases/{case_id}/dispute/sandbox-decide` | `dispute_sandbox_decide(case_id: str, body: DecideIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 562 |
| POST | `/api/mock/open-dispute/{case_id}` | `mock_open_dispute(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 570 |
| GET | `/api/cases/{case_id}/mandate` | `mandate_get(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 585 |
| POST | `/api/cases/{case_id}/mandate/revoke` | `mandate_revoke(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 596 |
| POST | `/api/cases/{case_id}/mandate/overspend-test` | `mandate_overspend_test(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 606 |
| POST | `/api/cases/{case_id}/delivered` | `delivered(case_id: str, days_ago: int=0, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 614 |
| POST | `/api/accounts/classify` | `accounts_classify(body: ClassifyIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 629 |
| POST | `/api/accounts/remember` | `accounts_remember(body: RememberIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 641 |
| POST | `/api/qr/interpret` | `qr_interpret(body: RawIn, user: User=Depends(user_dep))` | 652 |
| POST | `/api/cases/{case_id}/claims` | `add_claim(case_id: str, body: ClaimIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 665 |
| GET | `/api/cases/{case_id}/compare` | `compare_claims(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 672 |
| GET | `/api/graph` | `graph(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 681 |
| POST | `/api/a2a/sessions` | `a2a_start(body: A2AStart, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 694 |
| POST | `/api/a2a/sessions/{session_id}/sync` | `a2a_sync(session_id: str, simulate_failure: bool=False, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 702 |
| POST | `/a2a/inbox` | `a2a_inbox(env: dict, db=Depends(db_dep, scope='function'))` | 714 |
| POST | `/api/a2a/rotate` | `a2a_rotate(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 727 |
| GET | `/api/kg/retrieve` | `kg_retrieve(q: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 735 |
| GET | `/api/kg/as-of` | `kg_as_of(case_id: str, at: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 742 |
| GET | `/api/kg/contradictions` | `kg_contradictions(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 755 |
| GET | `/api/invest/research` | `invest_research(symbol: str, user: User=Depends(user_dep))` | 763 |
| POST | `/api/invest/diversification` | `invest_div(body: HoldingsIn, user: User=Depends(user_dep))` | 774 |
| GET | `/api/plugins` | `plugin_registry()` | 781 |
| GET | `/api/passkeys/status` | `passkey_status(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 789 |
| POST | `/api/passkeys/register/options` | `passkey_reg_options(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 796 |
| POST | `/api/passkeys/register/verify` | `passkey_reg_verify(credential: dict, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 803 |
| POST | `/api/passkeys/auth/options` | `passkey_auth_options(body: PasskeyAuthIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 818 |
| POST | `/api/passkeys/auth/verify` | `passkey_auth_verify(body: PasskeyAuthIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 828 |
| GET | `/api/profile` | `profile(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 851 |
| POST | `/api/balance` | `set_balance(body: BalanceIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 868 |
| POST | `/api/profile/paypal` | `set_paypal_account(body: PayPalAccountIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 880 |
| POST | `/api/profile/setup` | `profile_setup(body: SetupIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 887 |
| GET | `/api/insights` | `insights(hour: int \| None=None, weekday: int \| None=None, lat: float \| None=None, lon: float \| None=None, account: str \| None=None, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 910 |
| GET | `/api/cart/watch` | `cart_watch(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 925 |
| GET | `/console` | `console()` | 939 |
| GET | `/api/features` | `features()` | 944 |
| GET | `/api/cases` | `cases(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 952 |
| GET | `/api/cases/{case_id}` | `case_view(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 957 |
| POST | `/api/cases/{case_id}/investigate` | `investigate(case_id: str, claim: str='payment not received', user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 968 |
| GET | `/api/cases/{case_id}/refund-eligibility` | `refund_elig(case_id: str, issue: str='', user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 974 |
| POST | `/api/cases/{case_id}/refund/approve` | `refund_approve(case_id: str, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 986 |
| POST | `/api/cases/{case_id}/refund` | `refund(case_id: str, body: RefundIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 993 |
| POST | `/api/cases/{case_id}/resolution` | `case_resolution(case_id: str, body: ResolutionIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1005 |
| POST | `/api/webhooks/paypal` | `paypal_webhook(request: Request, db=Depends(db_dep, scope='function'))` | 1012 |
| POST | `/api/mock/deliver-webhooks` | `deliver_mock_webhooks(db=Depends(db_dep, scope='function'))` | 1045 |
| POST | `/api/qr/create` | `qr_create(body: QRIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1065 |
| POST | `/api/qr/scan` | `qr_scan(body: ScanIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1075 |
| POST | `/api/invoice/check` | `invoice_check(body: InvoiceIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1087 |
| GET | `/api/budget` | `budget(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1093 |
| POST | `/api/budget` | `set_budget(body: BudgetIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1105 |
| GET | `/api/whatif` | `whatif(amount: float, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1115 |
| GET | `/api/obligations` | `obligations(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1120 |
| POST | `/api/invest` | `invest(body: InvestIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1136 |
| POST | `/api/fraud/score` | `fraud(body: RiskIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1151 |
| GET | `/api/home` | `home(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1160 |
| POST | `/api/feedback` | `feedback(body: FeedbackIn, user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1183 |
| GET | `/api/metrics` | `metrics(db=Depends(db_dep, scope='function'))` | 1189 |
| POST | `/api/cache/{state}` | `cache_toggle(state: str)` | 1202 |
| GET | `/api/audit` | `audit(user: User=Depends(user_dep), db=Depends(db_dep, scope='function'))` | 1208 |

## Request models

### Item

```python
class Item(BaseModel):
    name: str
    unit_price: float
    quantity: int = 1
```

### CartIn

```python
class CartIn(BaseModel):
    merchant: str
    items: list[Item]
    currency: str = Field(default_factory=lambda: settings.currency)
    policy_text: str = ''
    policy_url: str = ''
    page_url: str = ''
    channel: str = 'online'
    seller_id: str | None = None
    purpose: str | None = None
```

### ChatIn

```python
class ChatIn(BaseModel):
    message: str
    case_id: str | None = None
```

### CaptureIn

```python
class CaptureIn(BaseModel):
    approval_token: str
    step_up_code: str | None = None
    signals: dict = {}
```

### VoiceIn

```python
class VoiceIn(BaseModel):
    text: str
```

### NoticeIn

```python
class NoticeIn(BaseModel):
    recipient: str
    channel: str = 'paypal_notice'
    notice_type: str = 'payment_reminder'
    subject: str = ''
    message: str
    amount: float | None = None
```

### ShipIn

```python
class ShipIn(BaseModel):
    tracking_number: str = Field(default='9400111899223344556677', min_length=4, max_length=40)
    carrier: str = Field(default='USPS', max_length=30)
```

### DisputeSubmitIn

```python
class DisputeSubmitIn(BaseModel):
    draft_hash: str
```

### DisputeAcceptIn

```python
class DisputeAcceptIn(BaseModel):
    approval_token: str
    step_up_code: str | None = None
    note: str = ''
```

### DecideIn

```python
class DecideIn(BaseModel):
    outcome: str = Field(default='SELLER_FAVOR', pattern='^(SELLER_FAVOR|BUYER_FAVOR)$')
```

### ClassifyIn

```python
class ClassifyIn(BaseModel):
    payee: str
    description: str = ''
    channel: str = 'online'
    amount: float
```

### RememberIn

```python
class RememberIn(BaseModel):
    payee: str
    purpose: str
```

### RawIn

```python
class RawIn(BaseModel):
    raw: str
```

### ClaimIn

```python
class ClaimIn(BaseModel):
    topic: str
    value: bool
    note: str = ''
```

### A2AStart

```python
class A2AStart(BaseModel):
    case_id: str
    tamper: str | None = None
```

### HoldingsIn

```python
class HoldingsIn(BaseModel):
    holdings: list[dict]
```

### PasskeyAuthIn

```python
class PasskeyAuthIn(BaseModel):
    approval_token: str
    credential: dict | None = None
```

### SetupIn

```python
class SetupIn(BaseModel):
    uses: str = 'personal'
    monthly_budget: float | None = None
    monthly_income: float | None = None
    pay_day: int | None = None
    work_start_hour: int | None = None
    work_end_hour: int | None = None
    goals: list[str] = []
    location_ok: bool = False
    home_lat: float | None = None
    home_lon: float | None = None
```

### BalanceIn

```python
class BalanceIn(BaseModel):
    balance: float
```

### PayPalAccountIn

```python
class PayPalAccountIn(BaseModel):
    email: str
```

### RefundIn

```python
class RefundIn(BaseModel):
    amount: float | None = None
    reason: str = ''
    approval_token: str | None = None
    step_up_code: str | None = None
```

### ResolutionIn

```python
class ResolutionIn(BaseModel):
    action: str
    issue: str = ''
```

### QRIn

```python
class QRIn(BaseModel):
    items: list[Item]
    currency: str = Field(default_factory=lambda: settings.currency)
    policy_text: str = ''
```

### ScanIn

```python
class ScanIn(BaseModel):
    token: str
```

### InvoiceIn

```python
class InvoiceIn(BaseModel):
    supplier: str
    po: dict
    invoice: dict
    text: str = ''
```

### BudgetIn

```python
class BudgetIn(BaseModel):
    category: str = 'total'
    limit: float
```

### InvestIn

```python
class InvestIn(BaseModel):
    amount: float
    horizon_months: int = 12
```

### RiskIn

```python
class RiskIn(BaseModel):
    payee: str
    amount: float
    text: str = ''
    new_device: bool = False
    ip_country_mismatch: bool = False
    payee_changed_recently: bool = False
    session_age_min: float = 30
```

### FeedbackIn

```python
class FeedbackIn(BaseModel):
    context: str = 'home'
    arm: str
    reward: float
```

## Lifecycle integration

Cart analysis reads merchant terms and affordability. Checkout returns a case ID, provider order, approval token, amount, currency and classification. Capture accepts `CaptureIn`. Cases and their participant-scoped evidence are retrieved through the case endpoints. QR scan currently creates a checkout. Bill checkout reuses the existing payment path. Exact runtime response schemas and representative success/error fixtures will be added with V2 contract tests.
