"""
Celery tasks for the Full-Funnel Attribution Agent.

Tasks:
- run_attribution_agent: Analyze a single merchant and save results to agent_logs
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from celery import Celery

from core.config import settings
from core.database import AsyncSessionLocal
from models.agent_log import AgentLog
from agent.attribution import analyze_merchant


# Initialize Celery app
celery_app = Celery(
    "d2c_agent",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=240,  # 4 minutes soft limit
)


@celery_app.task(name="agent.run_attribution_agent")
def run_attribution_agent(merchant_id: str) -> dict:
    """
    Run full-funnel attribution analysis for a merchant.

    This is the main Celery task that:
    1. Calls analyze_merchant() to run detection logic
    2. Saves the result to agent_logs table
    3. Returns a summary for monitoring

    Args:
        merchant_id: UUID of the merchant (as string)

    Returns:
        dict with:
        - merchant_id: str
        - detection_mode: str
        - status: str (completed, failed, skipped)
        - log_id: str (UUID of agent_log record)
    """
    merchant_uuid = UUID(merchant_id)

    async def _run():
        result = await analyze_merchant(merchant_uuid)
        log_id = await _save_agent_log(merchant_uuid, result)
        return result, log_id

    result, log_id = asyncio.run(_run())

    # Return summary for monitoring
    return {
        "merchant_id": merchant_id,
        "detection_mode": result["detection_mode"],
        "status": result["status"],
        "log_id": str(log_id),
    }


async def _save_agent_log(merchant_id: UUID, result: dict) -> UUID:
    """
    Save agent analysis result to agent_logs table.
    
    Args:
        merchant_id: Merchant UUID
        result: Result dict from analyze_merchant()
    
    Returns:
        UUID of the created agent_log record
    """
    # Convert UUID objects to strings for JSON serialization
    cited_ids = result["cited_metric_ids"]
    cited_ids_serializable = [str(uuid) for uuid in cited_ids] if cited_ids else []
    
    async with AsyncSessionLocal() as session:
        log = AgentLog(
            merchant_id=merchant_id,
            run_at=datetime.now(timezone.utc),
            trigger="scheduled_daily",  # TODO: pass as parameter for manual runs
            detection_mode=result["detection_mode"],
            data_snapshot=result["data_snapshot"],
            reasoning=result["reasoning"],
            recommendation=result["recommendation"],
            confidence_score=result["confidence_score"],
            cited_metric_ids=cited_ids_serializable,
            status=result["status"],
            error=result["error"],
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log.id
