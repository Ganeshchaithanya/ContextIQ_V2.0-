"""User-facing automation facts, scoped to the current private workspace."""
from datetime import UTC, datetime
from sqlalchemy import func, select
from .config import settings
from .models import AgentRun, OutboxEntry, WorkerHeartbeat
from .v2_models import PriceWatch


def automation_summary(db, current, profile, allocation):
    from .intelligence import llm
    completed = db.scalar(select(func.count()).select_from(AgentRun).where(
        AgentRun.user_id == current.buyer_id, AgentRun.status == "complete"))
    latest = db.scalar(select(func.max(AgentRun.updated_at)).where(
        AgentRun.user_id == current.buyer_id, AgentRun.status == "complete"))
    tracked = db.scalar(select(func.count()).select_from(PriceWatch).where(
        PriceWatch.user_id == current.buyer_id, PriceWatch.enabled))
    refreshed = db.scalar(select(func.max(OutboxEntry.published_at)).where(
        OutboxEntry.topic == "workspace.refresh", OutboxEntry.aggregate_id == current.token_hash))
    heartbeat = db.get(WorkerHeartbeat, "scheduler")
    beat = heartbeat.at if heartbeat else None
    if beat and beat.tzinfo is None:
        beat = beat.replace(tzinfo=UTC)
    available = bool(beat and (datetime.now(UTC) - beat).total_seconds() <= 180 and settings.worker_mode != "off")
    return {
        "completed_analyses": completed, "latest_analysis_at": latest,
        "tracked_products": tracked, "open_commitments": len(allocation["commitments"]),
        "savings_plans": len(allocation["savings"]), "savings_minor": allocation["savings_minor"],
        "last_workspace_check_at": refreshed, "scheduled_checks_available": available,
        "model_configured": llm.available(), "payment_authority": "human_only",
        "context_enabled": bool(profile.get("context_consent")), "voice_enabled": bool(profile.get("voice_enabled")),
        "basis": "Counts are from this workspace's saved runs, tracked products and current allocation.",
    }
