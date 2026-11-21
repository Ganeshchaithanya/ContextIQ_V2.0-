# Current demo storage — 22 November 2026

The owner selected normal SQLite instead of an external database. The Render
Blueprint sets `DATABASE_URL=sqlite:///data/contextiq.db`. On the existing free
web service this file, agent checkpoints and demo sessions can reset on a restart
or redeploy. Start a fresh demo session afterward. The previous PostgreSQL resource
is untouched and no longer connected. PostgreSQL instructions below are optional
deployment guidance, not the current demo configuration. Do not add a separate
worker against another SQLite file: the embedded worker shares the web process's
local database. No paid storage was provisioned.

# ContextIQ operational reliability

This release preserves the V2 pages, Tara tour, business accounts, budgets, store handoff and human payment approvals. It hardens the execution backbone. It does not turn the fictional-data demonstration into a regulated payment service or claim a penetration-test certification.

## Optional PostgreSQL architecture and migration guidance

Vercel serves ContextIQ and BrightMart separately. The existing Render API uses its configured database as the authority for money, permissions, inbox events, queued work and agent runs. `CONTEXTIQ_WORKER_MODE=embedded` runs a leased database-queue consumer inside that service. No additional paid resource is created by the default Blueprint.

Jobs survive process restarts in PostgreSQL. Consumers claim them with an atomic conditional update, a unique lease token and a 180-second lease. Failed jobs retry with backoff, then remain in a dead-letter list. A missing handler is a failure, never a successful acknowledgement. A stale consumer cannot acknowledge a newer lease. Handlers must remain idempotent: delivery is at least once.

The worker refreshes workspace observations and tracked prices, reconciles existing interrupted payments, processes verified webhook inbox entries, resumes interrupted Tara analyses, and records internal payment follow-ups. It never creates a new payment approval, initiates a new capture, sends a client reminder or buys a product on behalf of the user.

Financial state transitions reject unknown states and regressions. Approvals bind actor, participant role, case, operation, amount, payee and expiry. One-time consumption uses a database compare-and-set. Confirmation codes are HMAC protected in storage and demo codes are only returned in mock demo mode. They are demonstrations, not production MFA. Real-account mode requires independent verification such as the existing WebAuthn integration for step-up; it does not expose demo codes.

## Identity and roles

The audit's header-only identity finding describes the legacy interface. V2 already strips browser-supplied `X-User-Id` and derives ownership from an HttpOnly session, checks CSRF on browser writes, scopes queries and uses server-side participant roles. The isolated legacy regression-test bypass is forbidden in hosted mode and verified-account mode.

`CONTEXTIQ_AUTH_MODE=demo` remains active for the public hackathon prototype. It creates private fictional workspaces, not verified customer accounts.

An optional verified identity boundary is available with `CONTEXTIQ_AUTH_MODE=oidc`, `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL` and a strong `SERVER_SECRET`. An identity-provider frontend must obtain a valid access token and exchange it through `POST /api/v2/auth/exchange` using `Authorization: Bearer ...`. The API verifies the signature, pinned algorithm, issuer, audience, subject, issued-at and expiry; it ignores client role claims. Verified accounts start with no fictional funds or invoices. Sessions last at most one hour and never beyond token expiry. Signing in rotates the previous account session; `DELETE /api/v2/session` revokes it. Browser writes still need the returned CSRF token.

Do not enable verified-account mode until a real identity provider and its sign-in UI are configured and tested. It rejects demo login and cannot enable real payment execution. Merchant membership provisioning, independent MFA enrollment, payment-provider onboarding and a full production security review remain release requirements for handling real customer funds.

## Schema deployment and rollback

Startup runs `alembic upgrade head` through `init_db()`, serialized by a PostgreSQL advisory transaction lock. Revision `20261121_01` adopts the pre-existing schema and currency migration without removing records, then adds the reliability tables and indexes. `create_all()` is confined to this initial adoption migration; future schema changes require a new Alembic revision. LangGraph's official saver maintains its own checkpoint-schema migrations.

The baseline is additive. For an application rollback, redeploy the previous compatible commit and leave the added tables intact. Do not drop financial tables or stamp a revision to hide a failed migration. The baseline downgrade deliberately refuses to destroy data. Test both old and new application code against the schema before future destructive changes.

Before production migration, retain a provider-managed snapshot or encrypted backup and rehearse restoration into an isolated database. CI runs the real migrations and native checkpoints on isolated PostgreSQL, backs it up with `pg_dump`, restores into a separate database, and compares ledger counts/totals, agent runs, checkpoints and schema version. This synthetic drill does not certify restoration of the live hosted database.

Local recovery tools:

```text
python tools/backup_restore.py backup <new-backup-file>
python tools/backup_restore.py restore <backup-file>
```

The first command reads `DATABASE_URL`; the second requires a separately configured `RESTORE_DATABASE_URL`. Restore refuses an existing SQLite target or a PostgreSQL target containing public tables. PostgreSQL requires matching supported `pg_dump`/`pg_restore` tools and sufficient provider permissions. Connection secrets travel in subprocess environment variables, never command arguments or logs. Store backups encrypted with restricted access. SQLite development checkpoints use a separate `data/checkpoints-<database-hash>.db` file; back up that file too if local agent-resume history matters.

## Workers and hosting limits

`render.worker.yaml` prepares a separate worker using `python -m app.worker`. Review its paid compute plan before provisioning it. Configure the same PostgreSQL `DATABASE_URL`, `SERVER_SECRET` and required model settings as the API. After its heartbeat is healthy, switch the API to `CONTEXTIQ_WORKER_MODE=external`. Stop the embedded consumer only after the external worker is running. Both can overlap during rollout: queue leases prevent double claims, and handlers remain idempotent.

The default free Render web service may sleep. Its embedded consumer cannot run while the service is asleep. Durable storage preserves pending work; it does not provide always-on execution. A separately deployed always-on worker is required for continuous monitoring. SQLite files on ephemeral hosted disks are not a durable production queue; use managed PostgreSQL. No Redis, Temporal, RabbitMQ or Kubernetes is required for this deployment.

## Health, monitoring and recovery

`GET /health/live` reports process liveness. `GET /health/ready` checks database access, the expected migration revision, and a fresh scheduler heartbeat when worker mode is enabled. It returns only ready/not-ready. Optional AI and telemetry outages do not make payment authorization permissive. `/api/health` is a readiness alias.

The committed Render Blueprint specifies `healthCheckPath: /health/ready` and CI-gated deploys. Services created manually do not automatically inherit subsequent Blueprint setting changes. Verify the actual service setting in Render after rollout; the current connector can inspect/deploy services but cannot directly edit that existing web-service setting. If it still uses TCP checks, set the HTTP path in Dashboard → Settings → Health Checks.

`GET /api/metrics` requires an explicitly configured `ADMIN_TOKEN` as a Bearer token. It reports process-local request latency and optional-model usage, circuit states, queue depth/dead letters/oldest age, webhook backlog and worker heartbeat age. It does not return job payloads or customer balances. `GET /api/operations/dead-letters` uses the same operator authentication. After investigating and correcting a failure, an operator can explicitly `POST /api/operations/jobs/<id>/retry`; active or completed jobs cannot be requeued through this endpoint. The retry is audited.

Useful alerts: readiness failures; no heartbeat for three minutes; growing webhook/queue age; dead letters; repeated circuit openings; sustained provider errors. Request responses carry bounded, validated `X-Request-Id` values. Structured request logs contain correlation ID, method, status and duration, without query strings or customer content. HTTP timeouts, bounded AI concurrency, a single circuit recovery probe and bounded retry budgets limit slow-dependency overload.

## Agent persistence and opt-in tracing

Tara uses the existing LangGraph nodes with official PostgreSQL/SQLite checkpointers and synchronous checkpoint durability. Database sessions stay in runtime context and are never serialized. A persisted agent-run record and delayed recovery job let a worker resume an interrupted graph. Completed conversation rows use the run ID as a unique key. Checkpoints do not grant payment permission, and the explanation graph contains no payment-execution node.

Tracing is disabled until explicitly configured. For Langfuse set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_BASE_URL`. Alternatively configure `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`. Metadata-only OTLP export runs through the retry queue with HTTPS, bounded timeouts and deterministic trace IDs. It exports topic, routing, status/timing and request correlation; no question text, answer text, balances, invoice/customer content or identity tokens. Optional tracing failure cannot skip gateway policy or authorize payments.

Provider credentials, real sign-in, independent MFA and external trace collection are not activated merely by committing integration code. Keep the app labelled as a demo until the relevant integrations and operational requirements are verified.

## References

The implementation follows the [Alembic baseline guidance](https://alembic.sqlalchemy.org/en/latest/cookbook.html), [LangGraph persistence model](https://docs.langchain.com/oss/python/langgraph/persistence), [PyJWT validation API](https://pyjwt.readthedocs.io/en/latest/api.html), [Render health-check guidance](https://render.com/docs/health-checks), [Render Blueprint specification](https://render.com/docs/blueprint-spec), and [Langfuse OTLP ingestion documentation](https://langfuse.com/docs/api-and-data-platform/features/public-api). These sources describe the mechanisms; the test suite and deployment checks establish what this repository actually verifies.
