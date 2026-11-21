"""Opt-in, metadata-only OTLP traces. Prompts, balances and record contents are never exported."""
import hashlib
import logging
import os
from datetime import UTC, datetime
from urllib.parse import urlparse
import httpx
from .outbox import publish


def configure_logging():
    logger = logging.getLogger("contextiq.requests")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def destinations():
    result = []
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
    if endpoint:
        result.append((endpoint, None))
    public, secret = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
    if public and secret:
        base = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com").rstrip("/")
        result.append((base + "/api/public/otel/v1/traces", (public, secret)))
    for endpoint, _ in result:
        if urlparse(endpoint).scheme != "https":
            raise ValueError("Telemetry endpoints must use HTTPS")
    return result


def enqueue_agent_trace(db, run):
    try:
        configured = destinations()
    except ValueError:
        logging.getLogger(__name__).warning("invalid_telemetry_configuration")
        return
    if not configured:
        return
    stamp = datetime.now(UTC)
    result = run.state["result"]
    payload = {"trace_id": hashlib.sha256(run.id.encode()).hexdigest()[:32],
               "start_ns": str(int(run.state.get("started_at", stamp.timestamp()) * 1e9)),
               "end_ns": str(int(stamp.timestamp() * 1e9)), "topic": result["topic"],
               "routing": result["routing"], "request_id": run.state.get("request_id", "")}
    publish(db, topic="telemetry.agent", aggregate_id=run.id, aggregate_type="trace",
            payload=payload, dedupe_key="trace:" + run.id)


def export_trace(payload):
    span = {"traceId": payload["trace_id"], "spanId": payload["trace_id"][:16], "name": "tara.analysis",
            "kind": 1, "startTimeUnixNano": payload["start_ns"], "endTimeUnixNano": payload["end_ns"],
            "status": {"code": 1}, "attributes": [
                {"key": key, "value": {"stringValue": value}} for key, value in (
                    ("contextiq.topic", payload["topic"]), ("contextiq.routing", payload["routing"]),
                    ("contextiq.request_id", payload["request_id"]), ("langfuse.observation.type", "agent"))]}
    body = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "contextiq"}}]},
             "scopeSpans": [{"scope": {"name": "contextiq.agent"}, "spans": [span]}]}]}
    for endpoint, auth in destinations():
        response = httpx.post(endpoint, json=body, auth=auth, timeout=4, follow_redirects=False)
        response.raise_for_status()
        if response.content and response.json().get("partialSuccess", {}).get("rejectedSpans", 0):
            raise RuntimeError("Telemetry rejected")
